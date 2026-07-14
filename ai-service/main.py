"""
HairstyleSuggest AI Service — FastAPI entry point.

Startup sequence:
  1. Validate environment variables
  2. Initialise MySQL connection pool
  3. Launch background job worker (asyncio task)
  4. Expose /health and /metrics endpoints
"""

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from config import settings
from database import close_pool, init_pool, get_pool
from worker import run_worker


_metrics: dict = {
    "jobs_claimed": 0,
    "jobs_completed": 0,
    "jobs_failed": 0,
    "jobs_retried": 0,
    "total_gpu_seconds": 0.0,
    "total_cost_usd": 0.0,
    "worker_start_time": None,
}


def increment_metric(key: str, amount: float = 1.0) -> None:
    _metrics[key] = _metrics.get(key, 0) + amount


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("  HairstyleSuggest AI Service starting")
    logger.info(f"  Environment     : {settings.environment}")
    logger.info(f"  DB Host         : {settings.database_host}:{settings.database_port}")
    logger.info(f"  Poll interval   : {settings.job_poll_interval_seconds}s")
    logger.info(f"  Max concurrent  : {settings.max_concurrent_jobs}")
    logger.info("=" * 60)

    settings.validate()
    await init_pool()

    _metrics["worker_start_time"] = time.time()

    worker_task = asyncio.create_task(
        run_worker(metrics_callback=increment_metric),
        name="job-worker",
    )
    logger.info("Job worker started")

    yield  # FastAPI serves requests here

    logger.info("Shutting down job worker...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    await close_pool()
    logger.info("MySQL pool closed. Goodbye.")


app = FastAPI(
    title="HairstyleSuggest AI Service",
    version="1.0.0",
    description="FastAPI job worker + AI pipeline for hairstyle generation",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness probe. Returns 200 if the service is running."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        db_ok = True
    except Exception as exc:
        logger.warning(f"[health] DB check failed: {exc}")
        db_ok = False

    uptime = (
        round(time.time() - _metrics["worker_start_time"], 1)
        if _metrics["worker_start_time"] else 0
    )

    return {
        "status": "ok" if db_ok else "degraded",
        "uptime_seconds": uptime,
        "database": "ok" if db_ok else "unreachable",
    }


@app.get("/metrics", tags=["ops"])
async def metrics():
    """Basic operational metrics."""
    uptime = (
        round(time.time() - _metrics["worker_start_time"], 1)
        if _metrics["worker_start_time"] else 0
    )

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) as c FROM jobs WHERE status IN ('queued', 'retrying')"
                )
                row = await cur.fetchone()
                queue_depth = row["c"] if row else 0
    except Exception:
        queue_depth = -1

    return {"uptime_seconds": uptime, "queue_depth": queue_depth, **_metrics}
