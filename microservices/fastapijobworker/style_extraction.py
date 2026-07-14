"""
style_extraction handler.

Handles two modes:
  1. custom_upload — user uploaded a reference hairstyle photo
  2. training_sample — admin uploaded a training image

Flow:
  1. Download the reference image from R2
  2. Run BiSeNet segmentation to extract the hair mask (class 17)
  3. Generate a text description of the hairstyle from the masked region
  4. Upload the mask image to R2
  5. Return extracted_style_prompt + extracted_mask_key for the Strapi webhook

payload shape (custom_upload mode):
{
    "session_id": "...",
    "custom_upload_id": "...",
    "r2_image_key": "sessions/.../custom-style/UUID.jpg",
    "cdn_url": "..."
}

payload shape (training_sample mode):
{
    "training_sample_id": "...",
    "r2_image_key": "training-samples/braids/TIMESTAMP_sample.jpg",
    "cdn_url": "...",
    "mode": "training_sample"
}
"""

import asyncio
import tempfile
from pathlib import Path

import aiomysql
from loguru import logger

import r2_uploader
from style_extractor import describe_hairstyle, extract_hair_mask


async def run(job: dict, pool: aiomysql.Pool) -> dict:
    """Entry point called by the worker dispatcher."""
    payload = job["payload"]
    mode = payload.get("mode", "custom_upload")
    r2_image_key = payload["r2_image_key"]
    job_id = str(job["id"])

    logger.info(
        f"[style_extraction] Job {job_id} | mode={mode} | key={r2_image_key}"
    )

    with tempfile.TemporaryDirectory(prefix="hs_extract_") as tmpdir:
        tmp = Path(tmpdir)

        # ── Step 1: Download reference image ──────────────────────────────────
        local_img = tmp / "reference.jpg"
        await asyncio.get_event_loop().run_in_executor(
            None, r2_uploader.download_to_file, r2_image_key, local_img
        )
        logger.debug(f"[style_extraction] Downloaded reference image to {local_img}")

        # ── Step 2: Extract hair mask (BiSeNet class 17) ──────────────────────
        mask_path = await asyncio.get_event_loop().run_in_executor(
            None, extract_hair_mask, str(local_img), str(tmp)
        )
        logger.info(f"[style_extraction] Hair mask saved to {mask_path}")

        # ── Step 3: Generate text description ────────────────────────────────
        style_prompt = await asyncio.get_event_loop().run_in_executor(
            None, describe_hairstyle, mask_path
        )
        logger.info(
            f"[style_extraction] Extracted prompt: '{style_prompt[:80]}...'"
        )

        # ── Step 4: Upload mask to R2 ─────────────────────────────────────────
        if mode == "training_sample":
            sample_id = payload.get("training_sample_id", "unknown")
            mask_key = r2_uploader.build_training_mask_key(sample_id)
        else:
            session_id = payload.get("session_id", "unknown")
            upload_id = payload.get("custom_upload_id", "unknown")
            mask_key = r2_uploader.build_mask_key(session_id, upload_id)

        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: r2_uploader.upload_file(mask_path, mask_key, "image/png"),
        )
        logger.info(f"[style_extraction] Mask uploaded → {mask_key}")

    # ── Step 5: Build result for Strapi webhook ───────────────────────────────
    if mode == "training_sample":
        return {
            "training_sample_id": payload.get("training_sample_id"),
            "extracted_style_prompt": style_prompt,
            "extracted_mask_key": mask_key,
            "mode": "training_sample",
        }
    else:
        return {
            "custom_upload_id": payload.get("custom_upload_id"),
            "extracted_style_prompt": style_prompt,
            "extracted_mask_key": mask_key,
        }