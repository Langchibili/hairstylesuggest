"""
Job Worker — polls MySQL every JOB_POLL_INTERVAL_SECONDS seconds,
claims jobs via SELECT FOR UPDATE SKIP LOCKED, dispatches to handlers.

Concurrency model:
  - Single asyncio event loop (no threads)
  - asyncio.Semaphore limits concurrent jobs to MAX_CONCURRENT_JOBS
  - Each job runs as an asyncio.Task so the poll loop is never blocked

Retry model:
  - Handlers raise exceptions on failure
  - Worker marks job as 'retrying' (attempt < max) or 'failed' (attempt >= max)
  - The poll loop will pick up 'retrying' jobs on the next cycle
  - On final failure, Strapi webhook is called with /jobs/:id/failed

Handler contract:
  Each handler must be an async function:
    async def run(job: dict, pool: Pool) -> dict
  It receives the full job row dict and returns a result dict
  that is forwarded to the Strapi webhook.
"""

import asyncio
import json
from typing import Callable

import aiomysql
from loguru import logger

from config import settings
from database import claim_job, get_pool, mark_job_failed
from webhook_client import call_webhook_complete, call_webhook_failed


# ── Handler registry ───────────────────────────────────────────────────────────
# Import here to keep worker.py free of handler-specific logic
from handlers.preview_batch import run as handle_preview_batch
from handlers.focus_render import run as handle_focus_render
from handlers.style_extraction import run as handle_style_extraction

HANDLERS = {
    "preview_batch": handle_preview_batch,
    "focus_render": handle_focus_render,
    "style_extraction": handle_style_extraction,
}


async def run_worker(metrics_callback: Callable | None = None) -> None:
    """
    Main worker loop. Runs indefinitely until cancelled.

    metrics_callback(key, amount) is called on job events for the /metrics endpoint.
    """
    pool = await get_pool()
    semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    logger.info(
        f"[worker] Started polling every {settings.job_poll_interval_seconds}s "
        f"| max_concurrent={settings.max_concurrent_jobs}"
    )

    while True:
        try:
            # Check if we have capacity before even querying
            if semaphore._value > 0:
                job = await claim_job(pool)
                if job:
                    if metrics_callback:
                        metrics_callback("jobs_claimed")

                    # Fire-and-forget: don't await — let the poll loop continue
                    asyncio.create_task(
                        _run_job_with_semaphore(
                            job=job,
                            pool=pool,
                            semaphore=semaphore,
                            metrics_callback=metrics_callback,
                        ),
                        name=f"job-{job['id']}",
                    )
                else:
                    # Queue empty — wait the full interval
                    await asyncio.sleep(settings.job_poll_interval_seconds)
            else:
                # At capacity — wait a short time and re-check
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("[worker] Poll loop cancelled — shutting down gracefully")
            raise

        except Exception as exc:
            logger.error(f"[worker] Unexpected error in poll loop: {exc}")
            # Don't crash the worker — wait and retry
            await asyncio.sleep(settings.job_poll_interval_seconds)


async def _run_job_with_semaphore(
    job: dict,
    pool: aiomysql.Pool,
    semaphore: asyncio.Semaphore,
    metrics_callback: Callable | None,
) -> None:
    """Run a single job under the concurrency semaphore."""
    job_id = str(job["id"])
    job_type = job["type"]
    attempt = job["attempt_count"]  # already incremented by claim_job

    async with semaphore:
        logger.info(f"[worker] Running job {job_id} | type={job_type} | attempt={attempt}")

        handler = HANDLERS.get(job_type)
        if not handler:
            logger.error(f"[worker] No handler for job type '{job_type}' — marking failed")
            await mark_job_failed(pool, job_id, f"Unknown job type: {job_type}", attempt)
            await call_webhook_failed(job_id, f"Unknown job type: {job_type}", attempt)
            return

        # Parse payload
        payload = job.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}

        job["payload"] = payload

        try:
            result = await handler(job, pool)

            # Handler succeeded — call Strapi complete webhook
            await call_webhook_complete(job_id, result)

            if metrics_callback:
                metrics_callback("jobs_completed")
                if "gpu_seconds" in result:
                    metrics_callback("total_gpu_seconds", result["gpu_seconds"])
                if "cost_usd" in result:
                    metrics_callback("total_cost_usd", result["cost_usd"])

            logger.info(f"[worker] Job {job_id} completed successfully")

        except Exception as exc:
            logger.error(f"[worker] Job {job_id} failed on attempt {attempt}: {exc}")

            await mark_job_failed(pool, job_id, str(exc), attempt)
            await call_webhook_failed(job_id, str(exc), attempt)

            if metrics_callback:
                if attempt >= settings.job_max_attempts:
                    metrics_callback("jobs_failed")
                else:
                    metrics_callback("jobs_retried")