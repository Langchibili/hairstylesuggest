"""
Cloudflare R2 uploader — Python (FastAPI AI service).

Handles uploading generated images and downloading source images.
"""

import base64
import io
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from loguru import logger

from config import settings


def _build_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def cdn_url(key: str) -> str:
    return f"{settings.cdn_base_url}/{key}"


def upload_bytes(data: bytes, key: str, content_type: str = "image/png") -> str:
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


def upload_file(local_path: str | Path, key: str, content_type: str = "image/png") -> str:
    with open(local_path, "rb") as f:
        data = f.read()
    return upload_bytes(data, key, content_type)


def upload_base64_image(b64_data: str, key: str, content_type: str = "image/png") -> str:
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    raw = base64.b64decode(b64_data)
    return upload_bytes(raw, key, content_type)


def download_bytes(key: str) -> bytes:
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
    data = download_bytes(key)
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.debug(f"[r2] Saved {key} → {path}")
    return path


def build_result_key(session_id: str, job_type: str, hairstyle_id: str, angle: str) -> str:
    return f"sessions/{session_id}/results/{job_type}/{hairstyle_id}/{angle}.png"


def build_mask_key(session_id: str, upload_id: str) -> str:
    return f"sessions/{session_id}/custom-style/{upload_id}_mask.png"


def build_training_mask_key(sample_id: str) -> str:
    return f"training-samples/masks/{sample_id}_mask.png"
