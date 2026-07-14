"""
handlers/preview_batch.py

Handles a preview_batch job:
  1. Download source images from R2
  2. Face analysis (MediaPipe + BiSeNet) on the front image
  3. Build prompts for all hairstyles
  4. Submit one batch job to RunPod
  5. Upload results to R2
  6. Return result dict for the Strapi webhook
"""

import asyncio
import base64
import tempfile
import time
from pathlib import Path

import aiomysql
from loguru import logger

import r2_uploader
from face_analysis import analyse_face
from prompt_builder import build_prompt
from runpod_client import run_job


async def run(job: dict, pool: aiomysql.Pool) -> dict:
    payload       = job["payload"]
    session_id    = payload["session_id"]
    source_images = payload.get("source_images", [])
    hairstyles    = payload.get("hairstyles", [])
    job_id        = str(job["id"])

    logger.info(
        f"[preview_batch] Job {job_id} | session={session_id} "
        f"| hairstyles={len(hairstyles)} | images={len(source_images)}"
    )

    if not source_images:
        raise ValueError("No source images in payload")
    if not hairstyles:
        raise ValueError("No hairstyles in payload")

    with tempfile.TemporaryDirectory(prefix="hs_preview_") as tmpdir:
        tmp = Path(tmpdir)

        # ── Step 1: Download source images ────────────────────────────────────
        source_paths: dict[str, Path] = {}
        for img in source_images:
            angle      = img["angle"]
            local_path = tmp / f"{angle}.jpg"
            logger.debug(f"[preview_batch] Downloading: {img['key']}")
            await asyncio.get_event_loop().run_in_executor(
                None, r2_uploader.download_to_file, img["key"], local_path
            )
            source_paths[angle] = local_path

        # ── Step 2: Face analysis ─────────────────────────────────────────────
        front_path  = source_paths.get("front") or next(iter(source_paths.values()))
        face_analysis = await asyncio.get_event_loop().run_in_executor(
            None, analyse_face, str(front_path)
        )
        logger.info(
            f"[preview_batch] Face: skin={face_analysis.get('skin_tone_fitzpatrick')} "
            f"pose={face_analysis.get('head_pose')}"
        )

        # ── Step 3: Build batch payload for RunPod ────────────────────────────
        hairstyle_jobs = []
        for hs in hairstyles:
            prompt_data = build_prompt(face_analysis, hs)
            hairstyle_jobs.append({
                "hairstyle_id":     str(hs["id"]),
                "hairstyle_slug":   hs["slug"],
                "positive_prompt":  prompt_data["positive_prompt"],
                "negative_prompt":  prompt_data["negative_prompt"],
                "lora_checkpoint":  hs.get("lora_checkpoint"),
                "lora_weight":      float(hs.get("lora_weight") or 0.85),
                "render_tier":      "preview",
            })

        source_b64 = {}
        for angle, path in source_paths.items():
            source_b64[angle] = base64.b64encode(path.read_bytes()).decode()

        ip_strength = _face_strength_for_tone(
            face_analysis.get("skin_tone_fitzpatrick", "IV")
        )

        runpod_payload = {
            "session_id":        session_id,
            "source_images_b64": source_b64,
            "face_analysis":     face_analysis,
            "hairstyle_jobs":    hairstyle_jobs,
            "generation_config": {
                "steps":                           28,
                "guidance_scale":                  3.5,
                "width":                           768,
                "height":                          1024,
                "ip_adapter_face_strength":        ip_strength,
                "controlnet_conditioning_scale":   0.7,
            },
        }

        # ── Step 4: Submit to RunPod ──────────────────────────────────────────
        t0 = time.time()
        logger.info(f"[preview_batch] Submitting {len(hairstyle_jobs)} hairstyles to RunPod")
        runpod_job_id, runpod_output = await run_job(runpod_payload)
        gpu_seconds = round(time.time() - t0, 2)
        logger.info(f"[preview_batch] RunPod done in {gpu_seconds}s | id={runpod_job_id}")

        # ── Step 5: Upload results to R2 ──────────────────────────────────────
        results    = []
        total_cost = 0.0

        for item in runpod_output.get("results", []):
            hairstyle_id = item["hairstyle_id"]
            angles_b64   = item.get("angles", {})

            uploaded_angles = []
            for angle, b64_img in angles_b64.items():
                r2_key = r2_uploader.build_result_key(session_id, "preview", hairstyle_id, angle)
                cdn = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda k=r2_key, b=b64_img: r2_uploader.upload_base64_image(b, k),
                )
                uploaded_angles.append({"angle": angle, "cdn_url": cdn, "r2_key": r2_key})

            item_cost   = round(item.get("cost_usd", 0.008), 6)
            total_cost += item_cost

            results.append({
                "hairstyle_id":      hairstyle_id,
                "render_tier":       "preview",
                "angles":            uploaded_angles,
                "identity_score":    item.get("identity_score"),
                "generation_params": runpod_payload["generation_config"],
                "gpu_seconds":       round(gpu_seconds / max(len(hairstyle_jobs), 1), 2),
                "cost_usd":          item_cost,
            })

    return {
        "results":        results,
        "face_analysis":  face_analysis,
        "runpod_job_id":  runpod_job_id,
        "gpu_seconds":    gpu_seconds,
        "cost_usd":       round(total_cost, 6),
    }


def _face_strength_for_tone(fitzpatrick: str) -> float:
    """Higher IP-Adapter strength for darker skin tones to preserve identity."""
    mapping = {"I": 0.80, "II": 0.82, "III": 0.84, "IV": 0.86, "V": 0.88, "VI": 0.90}
    return mapping.get(str(fitzpatrick).upper(), 0.85)
