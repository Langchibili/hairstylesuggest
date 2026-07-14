"""
Webhook client — calls the Strapi internal webhook endpoints.

Strapi exposes:
  POST /internal/jobs/:id/complete   { results: [...], face_analysis: {...} }
  POST /internal/jobs/:id/failed     { error_message: "...", attempt_count: N }

Both are protected by the X-Internal-Key header.
We retry up to 3 times with exponential backoff on network failures.
"""

import asyncio

import httpx
from loguru import logger

from config import settings


_HEADERS = {
    "Content-Type": "application/json",
    "X-Internal-Key": settings.internal_service_key,
}

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds


async def call_webhook_complete(job_id: str, result: dict) -> bool:
    """
    POST to /internal/jobs/:id/complete.

    result dict should contain whatever the handler produced:
      - preview_batch/focus_render: { results: [...], face_analysis: {...}, runpod_job_id: "..." }
      - style_extraction: { custom_upload_id: "...", extracted_style_prompt: "...", extracted_mask_key: "..." }

    Returns True if Strapi acknowledged, False if all retries exhausted.
    """
    url = f"{settings.strapi_webhook_url}/{job_id}/complete"
    return await _post_with_retry(url, result, label=f"complete/{job_id}")


async def call_webhook_failed(
    job_id: str, error_message: str, attempt_count: int
) -> bool:
    """
    POST to /internal/jobs/:id/failed.

    Returns True if Strapi acknowledged, False if all retries exhausted.
    """
    url = f"{settings.strapi_webhook_url}/{job_id}/failed"
    body = {"error_message": error_message, "attempt_count": attempt_count}
    return await _post_with_retry(url, body, label=f"failed/{job_id}")


async def _post_with_retry(url: str, body: dict, label: str) -> bool:
    """
    POST with exponential backoff retry.

    Retries on connection errors and 5xx responses.
    Does NOT retry on 4xx — those are programming errors.
    """
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=body, headers=_HEADERS)

            if response.is_success:
                logger.info(
                    f"[webhook] {label} → HTTP {response.status_code} "
                    f"(attempt {attempt})"
                )
                return True

            if response.status_code < 500:
                # 4xx — don't retry, log and give up
                logger.error(
                    f"[webhook] {label} → HTTP {response.status_code} "
                    f"(non-retryable): {response.text[:200]}"
                )
                return False

            # 5xx — Strapi is unhappy, retry
            logger.warning(
                f"[webhook] {label} → HTTP {response.status_code} "
                f"(attempt {attempt}/{_MAX_RETRIES}): {response.text[:200]}"
            )
            last_exc = Exception(f"HTTP {response.status_code}")

        except httpx.RequestError as exc:
            logger.warning(
                f"[webhook] {label} → network error "
                f"(attempt {attempt}/{_MAX_RETRIES}): {exc}"
            )
            last_exc = exc

        if attempt < _MAX_RETRIES:
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.debug(f"[webhook] Retrying {label} in {delay}s...")
            await asyncio.sleep(delay)

    logger.error(
        f"[webhook] {label} — all {_MAX_RETRIES} attempts failed. "
        f"Last error: {last_exc}"
    )
    return False