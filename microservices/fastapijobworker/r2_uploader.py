"""
Cloudflare R2 uploader — Python (FastAPI AI service).

Counterpart to r2-uploader.js in Strapi.
This module is responsible for:
  1. Uploading processed result images to R2 after generation
  2. Downloading source images from R2 for processing
  3. Building CDN URLs for uploaded assets

Uses boto3 with a custom endpoint pointing at Cloudflare R2.
R2 is S3-compatible, so boto3 works without modification.
"""

import io
import os
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger

from config import settings


def _build_client():
    """Build a boto3 S3 client pointed at Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def cdn_url(key: str) -> str:
    """Build the public CDN URL for an R2 object key."""
    return f"{settings.cdn_base_url}/{key}"


def upload_bytes(
    data: bytes,
    key: str,
    content_type: str = "image/png",
) -> str:
    """
    Upload raw bytes to R2.

    Args:
        data: The file content as bytes
        key: R2 object key (e.g. "sessions/abc/results/front.png")
        content_type: MIME type

    Returns:
        CDN URL for the uploaded object

    Raises:
        RuntimeError: If the upload fails after logging the error
    """
    client = _build_client()
    try:
        client.put_object(
            Bucket=settings.r2_bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        url = cdn_url(key)
        logger.debug(f"[r2] Uploaded {len(data)} bytes → {key}")
        return url

    except (BotoCoreError, ClientError) as exc:
        logger.error(f"[r2] Failed to upload {key}: {exc}")
        raise RuntimeError(f"R2 upload failed for key '{key}': {exc}") from exc


def upload_file(
    local_path: str | Path,
    key: str,
    content_type: str = "image/png",
) -> str:
    """
    Upload a local file to R2.

    Returns:
        CDN URL for the uploaded object
    """
    with open(local_path, "rb") as f:
        data = f.read()
    return upload_bytes(data, key, content_type)


def upload_base64_image(
    b64_data: str,
    key: str,
    content_type: str = "image/png",
) -> str:
    """
    Upload a base64-encoded image string to R2.
    Strips any data: URL prefix before decoding.

    Returns:
        CDN URL for the uploaded object
    """
    import base64

    # Strip "data:image/png;base64," prefix if present
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]

    raw = base64.b64decode(b64_data)
    return upload_bytes(raw, key, content_type)


def download_bytes(key: str) -> bytes:
    """
    Download an object from R2 as bytes.

    Args:
        key: R2 object key

    Returns:
        File contents as bytes

    Raises:
        RuntimeError: If download fails
    """
    client = _build_client()
    try:
        response = client.get_object(Bucket=settings.r2_bucket_name, Key=key)
        data = response["Body"].read()
        logger.debug(f"[r2] Downloaded {len(data)} bytes ← {key}")
        return data

    except (BotoCoreError, ClientError) as exc:
        logger.error(f"[r2] Failed to download {key}: {exc}")
        raise RuntimeError(f"R2 download failed for key '{key}': {exc}") from exc


def download_to_file(key: str, local_path: str | Path) -> Path:
    """
    Download an R2 object to a local file.

    Returns:
        Path to the downloaded file
    """
    data = download_bytes(key)
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.debug(f"[r2] Saved {key} → {path}")
    return path


def build_result_key(session_id: str, job_type: str, hairstyle_id: str, angle: str) -> str:
    """
    Build a deterministic R2 key for a generation result image.

    Pattern: sessions/{session_id}/results/{job_type}/{hairstyle_id}/{angle}.png
    """
    return f"sessions/{session_id}/results/{job_type}/{hairstyle_id}/{angle}.png"


def build_mask_key(session_id: str, upload_id: str) -> str:
    """Build R2 key for a custom style extraction mask."""
    return f"sessions/{session_id}/custom-style/{upload_id}_mask.png"


def build_training_mask_key(sample_id: str) -> str:
    """Build R2 key for a training sample hair mask."""
    return f"training-samples/masks/{sample_id}_mask.png"