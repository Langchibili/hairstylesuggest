"""
handlers/style_extraction.py

Handles a style_extraction job in two modes:
  - custom_upload:   user reference photo → prompt for their session
  - training_sample: admin upload → mask + prompt stored for LoRA training
"""

import asyncio
import tempfile
from pathlib import Path

import aiomysql
from loguru import logger

import r2_uploader
from style_extractor import describe_hairstyle, extract_hair_mask


async def run(job: dict, pool: aiomysql.Pool) -> dict:
    payload      = job["payload"]
    mode         = payload.get("mode", "custom_upload")
    r2_image_key = payload["r2_image_key"]
    job_id       = str(job["id"])

    logger.info(f"[style_extraction] Job {job_id} | mode={mode} | key={r2_image_key}")

    with tempfile.TemporaryDirectory(prefix="hs_extract_") as tmpdir:
        tmp = Path(tmpdir)

        # ── Download reference image ──────────────────────────────────────────
        local_img = tmp / "reference.jpg"
        await asyncio.get_event_loop().run_in_executor(
            None, r2_uploader.download_to_file, r2_image_key, local_img
        )

        # ── Extract hair mask (BiSeNet class 17) ──────────────────────────────
        mask_path = await asyncio.get_event_loop().run_in_executor(
            None, extract_hair_mask, str(local_img), str(tmp)
        )
        logger.info(f"[style_extraction] Hair mask: {mask_path}")

        # ── Generate text description ─────────────────────────────────────────
        style_prompt = await asyncio.get_event_loop().run_in_executor(
            None, describe_hairstyle, mask_path
        )
        logger.info(f"[style_extraction] Prompt: '{style_prompt[:80]}'")

        # ── Upload mask to R2 ─────────────────────────────────────────────────
        if mode == "training_sample":
            sample_id = payload.get("training_sample_id", "unknown")
            mask_key  = r2_uploader.build_training_mask_key(sample_id)
        else:
            session_id = payload.get("session_id", "unknown")
            upload_id  = payload.get("custom_upload_id", "unknown")
            mask_key   = r2_uploader.build_mask_key(session_id, upload_id)

        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: r2_uploader.upload_file(mask_path, mask_key, "image/png"),
        )
        logger.info(f"[style_extraction] Mask uploaded → {mask_key}")

    if mode == "training_sample":
        return {
            "training_sample_id":    payload.get("training_sample_id"),
            "extracted_style_prompt": style_prompt,
            "extracted_mask_key":    mask_key,
            "mode":                  "training_sample",
        }
    else:
        return {
            "custom_upload_id":       payload.get("custom_upload_id"),
            "extracted_style_prompt": style_prompt,
            "extracted_mask_key":    mask_key,
        }
