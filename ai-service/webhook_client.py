"""
Webhook client — calls the Strapi internal webhook endpoints with retry logic.
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
_RETRY_BASE_DELAY = 2.0


async def call_webhook_complete(job_id: str, result: dict) -> bool:
    url = f"{settings.strapi_webhook_url}/{job_id}/complete"
    return await _post_with_retry(url, result, label=f"complete/{job_id}")


async def call_webhook_failed(job_id: str, error_message: str, attempt_count: int) -> bool:
    url = f"{settings.strapi_webhook_url}/{job_id}/failed"
    body = {"error_message": error_message, "attempt_count": attempt_count}
    return await _post_with_retry(url, body, label=f"failed/{job_id}")


async def _post_with_retry(url: str, body: dict, label: str) -> bool:
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=body, headers=_HEADERS)

            if response.is_success:
                logger.info(f"[webhook] {label} → HTTP {response.status_code} (attempt {attempt})")
                return True

            if response.status_code < 500:
                logger.error(
                    f"[webhook] {label} → HTTP {response.status_code} (non-retryable): "
                    f"{response.text[:200]}"
                )
                return False

            logger.warning(
                f"[webhook] {label} → HTTP {response.status_code} "
                f"(attempt {attempt}/{_MAX_RETRIES})"
            )
            last_exc = Exception(f"HTTP {response.status_code}")

        except httpx.RequestError as exc:
            logger.warning(f"[webhook] {label} → network error (attempt {attempt}/{_MAX_RETRIES}): {exc}")
            last_exc = exc

        if attempt < _MAX_RETRIES:
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            await asyncio.sleep(delay)

    logger.error(f"[webhook] {label} — all {_MAX_RETRIES} attempts failed. Last: {last_exc}")
    return False
