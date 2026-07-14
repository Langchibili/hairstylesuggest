"""
RunPod Serverless client — async.

Submits a generation payload to the RunPod endpoint and polls until
the job completes, fails, or times out.

RunPod Serverless API:
  POST https://api.runpod.io/v2/{endpoint_id}/run
    → { id: "job-id", status: "IN_QUEUE" }

  GET  https://api.runpod.io/v2/{endpoint_id}/status/{job_id}
    → { id: "...", status: "COMPLETED" | "FAILED" | "IN_PROGRESS" | "IN_QUEUE",
        output: {...} }

Authentication: Bearer token via Authorization header.
"""

import asyncio

import httpx
from loguru import logger

from config import settings


_BASE_URL = "https://api.runpod.io/v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


async def submit_job(payload: dict) -> str:
    """
    Submit a job to the RunPod serverless endpoint.

    Args:
        payload: The JSON body to send as the RunPod job input.
                 Will be wrapped in {"input": payload}.

    Returns:
        RunPod job ID string

    Raises:
        RuntimeError: If the submission fails
    """
    url = f"{_BASE_URL}/{settings.runpod_endpoint_id}/run"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            json={"input": payload},
            headers=_headers(),
        )

    if not response.is_success:
        raise RuntimeError(
            f"RunPod job submission failed: HTTP {response.status_code} — "
            f"{response.text[:300]}"
        )

    data = response.json()
    job_id = data.get("id")
    if not job_id:
        raise RuntimeError(f"RunPod returned no job ID: {data}")

    logger.info(f"[runpod] Job submitted → id={job_id}")
    return job_id


async def wait_for_completion(runpod_job_id: str) -> dict:
    """
    Poll the RunPod status endpoint until the job finishes.

    Args:
        runpod_job_id: The ID returned by submit_job()

    Returns:
        The output dict from the completed job

    Raises:
        RuntimeError: If the job fails or times out
    """
    url = f"{_BASE_URL}/{settings.runpod_endpoint_id}/status/{runpod_job_id}"
    deadline = asyncio.get_event_loop().time() + settings.runpod_timeout_seconds
    poll_count = 0

    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise RuntimeError(
                f"RunPod job {runpod_job_id} timed out after "
                f"{settings.runpod_timeout_seconds}s"
            )

        await asyncio.sleep(settings.runpod_poll_interval)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=_headers())
        except httpx.RequestError as exc:
            logger.warning(f"[runpod] Poll network error (will retry): {exc}")
            continue

        if not response.is_success:
            logger.warning(
                f"[runpod] Poll HTTP {response.status_code} — retrying"
            )
            continue

        data = response.json()
        status = data.get("status", "UNKNOWN")
        poll_count += 1

        logger.debug(
            f"[runpod] Job {runpod_job_id} status={status} "
            f"(poll #{poll_count})"
        )

        if status == "COMPLETED":
            output = data.get("output")
            if output is None:
                raise RuntimeError(
                    f"RunPod job {runpod_job_id} COMPLETED but output is null"
                )
            logger.info(
                f"[runpod] Job {runpod_job_id} completed "
                f"after {poll_count} polls"
            )
            return output

        if status == "FAILED":
            error = data.get("error") or "No error detail provided"
            raise RuntimeError(f"RunPod job {runpod_job_id} FAILED: {error}")

        # IN_QUEUE or IN_PROGRESS — keep polling


async def run_job(payload: dict) -> tuple[str, dict]:
    """
    Convenience wrapper: submit + wait.

    Returns:
        (runpod_job_id, output_dict) tuple
    """
    runpod_id = await submit_job(payload)
    output = await wait_for_completion(runpod_id)
    return runpod_id, output