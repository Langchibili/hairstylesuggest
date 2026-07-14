"""
handlers/focus_render.py

Handles a focus_render job — single hairstyle, 3 angles, higher quality.
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
    payload              = job["payload"]
    session_id           = payload["session_id"]
    hairstyle_id         = payload["hairstyle_id"]
    hairstyle            = payload["hairstyle"]
    source_images        = payload.get("source_images", [])
    angles               = payload.get("angles", ["left", "front", "right"])
    stored_face_analysis = payload.get("face_analysis")
    job_id               = str(job["id"])

    logger.info(
        f"[focus_render] Job {job_id} | session={session_id} "
        f"| hairstyle={hairstyle_id} | angles={angles}"
    )

    with tempfile.TemporaryDirectory(prefix="hs_focus_") as tmpdir:
        tmp = Path(tmpdir)

        # ── Download source images ────────────────────────────────────────────
        source_paths: dict[str, Path] = {}
        for img in source_images:
            angle      = img["angle"]
            local_path = tmp / f"{angle}.jpg"
            await asyncio.get_event_loop().run_in_executor(
                None, r2_uploader.download_to_file, img["key"], local_path
            )
            source_paths[angle] = local_path

        # ── Face analysis (reuse stored if available) ─────────────────────────
        if stored_face_analysis:
            face_analysis = stored_face_analysis
            logger.debug("[focus_render] Using stored face analysis")
        else:
            front_path = source_paths.get("front") or next(iter(source_paths.values()))
            face_analysis = await asyncio.get_event_loop().run_in_executor(
                None, analyse_face, str(front_path)
            )

        # ── Build prompt ──────────────────────────────────────────────────────
        prompt_data = build_prompt(face_analysis, hairstyle)

        # ── Encode sources ────────────────────────────────────────────────────
        source_b64 = {}
        for angle, path in source_paths.items():
            source_b64[angle] = base64.b64encode(path.read_bytes()).decode()

        ip_strength = _face_strength_for_tone(face_analysis.get("skin_tone_fitzpatrick", "IV"))

        runpod_payload = {
            "session_id":        session_id,
            "source_images_b64": source_b64,
            "face_analysis":     face_analysis,
            "hairstyle_jobs": [{
                "hairstyle_id":    hairstyle_id,
                "hairstyle_slug":  hairstyle.get("slug", ""),
                "positive_prompt": prompt_data["positive_prompt"],
                "negative_prompt": prompt_data["negative_prompt"],
                "lora_checkpoint": hairstyle.get("lora_checkpoint"),
                "lora_weight":     float(hairstyle.get("lora_weight") or 0.85),
                "render_tier":     "focus",
                "angles":          angles,
            }],
            "generation_config": {
                "steps":                          35,
                "guidance_scale":                 4.0,
                "width":                          832,
                "height":                         1152,
                "ip_adapter_face_strength":       ip_strength,
                "controlnet_conditioning_scale":  0.75,
            },
        }

        # ── Submit to RunPod ──────────────────────────────────────────────────
        t0 = time.time()
        runpod_job_id, runpod_output = await run_job(runpod_payload)
        gpu_seconds = round(time.time() - t0, 2)

        # ── Upload results ────────────────────────────────────────────────────
        result_item = runpod_output.get("results", [{}])[0]
        angles_b64  = result_item.get("angles", {})

        uploaded_angles = []
        for angle, b64_img in angles_b64.items():
            r2_key = r2_uploader.build_result_key(session_id, "focus", hairstyle_id, angle)
            cdn = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda k=r2_key, b=b64_img: r2_uploader.upload_base64_image(b, k),
            )
            uploaded_angles.append({"angle": angle, "cdn_url": cdn, "r2_key": r2_key})

    cost_usd = round(result_item.get("cost_usd", 0.025), 6)

    return {
        "results": [{
            "hairstyle_id":      hairstyle_id,
            "render_tier":       "focus",
            "angles":            uploaded_angles,
            "identity_score":    result_item.get("identity_score"),
            "generation_params": runpod_payload["generation_config"],
            "gpu_seconds":       gpu_seconds,
            "cost_usd":          cost_usd,
        }],
        "runpod_job_id": runpod_job_id,
        "gpu_seconds":   gpu_seconds,
        "cost_usd":      cost_usd,
    }


def _face_strength_for_tone(fitzpatrick: str) -> float:
    mapping = {"I": 0.80, "II": 0.82, "III": 0.84, "IV": 0.86, "V": 0.88, "VI": 0.90}
    return mapping.get(str(fitzpatrick).upper(), 0.85)
