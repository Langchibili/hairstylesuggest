"""
prompt_builder.py
─────────────────
Assembles positive and negative FLUX prompts from:
  - face_analysis dict (from face_analysis.py)
  - hairstyle dict (from the hairstyles DB table)

The prompt structure follows the order:
  [subject] + [skin description] + [hairstyle description] + [quality tags]

Usage:
  from prompt_builder import build_prompt
  result = build_prompt(face_analysis, hairstyle)
  # result: { positive_prompt: "...", negative_prompt: "..." }
"""

from loguru import logger

# ── Quality and style suffix appended to every positive prompt ────────────────
_QUALITY_SUFFIX = (
    "photorealistic, professional portrait photography, sharp focus, "
    "studio lighting, high detail skin texture, 8k resolution"
)

# ── Negative prompt shared across all hairstyle types ─────────────────────────
_BASE_NEGATIVE = (
    "cartoon, anime, illustration, painting, sketch, drawing, render, 3d, "
    "deformed face, disfigured, bad anatomy, extra fingers, mutation, "
    "poorly drawn face, blurry, out of focus, low quality, watermark, "
    "text, logo, signature, ugly, bad proportions, duplicate, cloned face, "
    "multiple people, crowd, hat covering hair, hair covering face"
)

# ── Head pose → ControlNet angle descriptor ───────────────────────────────────
def _pose_to_angle_descriptor(head_pose: dict) -> str:
    yaw = head_pose.get("yaw", 0)
    pitch = head_pose.get("pitch", 0)

    if abs(yaw) < 15:
        angle = "front-facing portrait, direct eye contact"
    elif yaw > 15:
        angle = "three-quarter left profile portrait"
    else:
        angle = "three-quarter right profile portrait"

    if pitch > 10:
        angle += ", slight upward gaze"
    elif pitch < -10:
        angle += ", slight downward gaze"

    return angle


# ── Hairstyle-specific negative additions ─────────────────────────────────────
_CATEGORY_NEGATIVES = {
    "fade":       "uneven fade, patchy hair, untidy edges, overgrown sides",
    "braids":     "tangled braids, messy braids, uneven braid size, frizzy braids",
    "locs":       "tangled locs, unformed locs, frizzy locs",
    "afro":       "flat afro, matted afro, uneven shape",
    "waves":      "no wave pattern, straight hair, uneven waves",
    "beard":      "patchy beard, uneven beard line, messy beard",
    "protective": "loose ends, unraveling style",
    "custom":     "",
}


def build_prompt(face_analysis: dict, hairstyle: dict) -> dict:
    """
    Build positive and negative prompts for FLUX generation.

    Args:
        face_analysis: Output from face_analysis.analyse_face()
        hairstyle:     Row from the hairstyles table (dict)

    Returns:
        { positive_prompt: str, negative_prompt: str }
    """
    # ── Subject and identity line ────────────────────────────────────────────
    skin_descriptor = face_analysis.get("skin_tone_descriptor", "medium complexion")
    fitz_type       = face_analysis.get("skin_tone_fitzpatrick", "IV")
    head_pose       = face_analysis.get("head_pose", {"yaw": 0, "pitch": 0, "roll": 0})

    angle_descriptor = _pose_to_angle_descriptor(head_pose)

    subject_line = (
        f"a close-up {angle_descriptor} of a person with {skin_descriptor}, "
        f"Fitzpatrick skin type {fitz_type}"
    )

    # ── Hairstyle description ─────────────────────────────────────────────────
    hairstyle_base_prompt = (hairstyle.get("base_prompt") or "").strip()
    if not hairstyle_base_prompt:
        # Fallback: generate a basic description from available metadata
        hairstyle_base_prompt = (
            f"{hairstyle.get('display_name', 'stylish hairstyle')}, "
            f"{hairstyle.get('category', 'modern')} style hair"
        )
        logger.warning(
            f"[prompt_builder] Hairstyle {hairstyle.get('slug')} has no base_prompt — using fallback"
        )

    # ── Assemble positive prompt ──────────────────────────────────────────────
    positive_parts = [
        subject_line,
        hairstyle_base_prompt,
        _QUALITY_SUFFIX,
    ]
    positive_prompt = ", ".join(p.strip().rstrip(",") for p in positive_parts if p.strip())

    # ── Assemble negative prompt ──────────────────────────────────────────────
    category = hairstyle.get("category", "custom")
    category_negative = _CATEGORY_NEGATIVES.get(category, "")

    hairstyle_negative = (hairstyle.get("negative_prompt") or "").strip()

    negative_parts = [_BASE_NEGATIVE]
    if hairstyle_negative:
        negative_parts.append(hairstyle_negative)
    if category_negative:
        negative_parts.append(category_negative)

    negative_prompt = ", ".join(p.strip().rstrip(",") for p in negative_parts if p.strip())

    logger.debug(
        f"[prompt_builder] Built prompt for {hairstyle.get('slug')} | "
        f"positive_len={len(positive_prompt)} negative_len={len(negative_prompt)}"
    )

    return {
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
    }


# ── CLI test harness ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    sample_face = {
        "head_pose":             {"yaw": 2.1, "pitch": -3.5, "roll": 0.8},
        "skin_tone_hex":         "#8D5524",
        "skin_tone_fitzpatrick": "V",
        "skin_tone_descriptor":  "dark brown skin, rich complexion",
    }

    sample_hairstyle = {
        "slug":            "box-braids-medium",
        "display_name":    "Medium Box Braids",
        "category":        "braids",
        "base_prompt":     "medium length box braids, neatly parted, smooth texture, dark brown color",
        "negative_prompt": "thin braids, micro braids",
        "lora_checkpoint": None,
        "lora_weight":     0.85,
    }

    result = build_prompt(sample_face, sample_hairstyle)
    print("=== POSITIVE ===")
    print(result["positive_prompt"])
    print("\n=== NEGATIVE ===")
    print(result["negative_prompt"])
