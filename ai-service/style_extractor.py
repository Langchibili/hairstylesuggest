"""
style_extractor.py
──────────────────
Two functions used by the style_extraction job handler:

  extract_hair_mask(image_path, output_dir) → mask_path
    Runs BiSeNet on the image, isolates class 17 (hair), saves the mask PNG.

  describe_hairstyle(mask_path) → str
    Analyses the cropped hair region and returns a text description.
    On Day 2 this uses a simple heuristic; swap in a CLIP/vision model in V2.

Both are blocking (CPU-bound) functions meant to be run in an executor:
  await loop.run_in_executor(None, extract_hair_mask, img_path, out_dir)
"""

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from PIL import Image

# ── Lazy BiSeNet loader (shared with face_analysis.py) ────────────────────────
_BISENET_MODEL = None


def _load_bisenet():
    global _BISENET_MODEL
    model_path = os.getenv("BISENET_MODEL_PATH", "")
    if model_path and Path(model_path).exists():
        try:
            import torch
            _BISENET_MODEL = torch.jit.load(model_path, map_location="cpu")
            _BISENET_MODEL.eval()
            logger.info(f"[style_extractor] BiSeNet loaded from {model_path}")
        except Exception as e:
            logger.error(f"[style_extractor] Failed to load BiSeNet: {e}")
    else:
        logger.warning(
            "[style_extractor] BISENET_MODEL_PATH not set or file missing — "
            "using stub hair mask (upper-third of image)"
        )


def _run_bisenet(image_bgr: np.ndarray) -> np.ndarray | None:
    """Run BiSeNet and return a label map. Returns None if model unavailable."""
    if _BISENET_MODEL is None:
        return None

    try:
        import torch
        import torchvision.transforms as T

        transform = T.Compose([
            T.Resize((512, 512)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        img_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        tensor = transform(Image.fromarray(img_rgb)).unsqueeze(0)

        with torch.no_grad():
            out = _BISENET_MODEL(tensor)[0]
            label_map = out.squeeze(0).argmax(0).numpy().astype(np.uint8)

        label_map = cv2.resize(
            label_map,
            (image_bgr.shape[1], image_bgr.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        return label_map
    except Exception as e:
        logger.error(f"[style_extractor] BiSeNet inference error: {e}")
        return None


# ── Heuristic descriptors for the stub describe path ─────────────────────────

def _dominant_color_name(bgr_pixels: np.ndarray) -> str:
    """Map the median BGR color to a simple color name."""
    if len(bgr_pixels) == 0:
        return "dark"
    median = np.median(bgr_pixels, axis=0).astype(int)
    b, g, r = median

    brightness = int(0.299 * r + 0.587 * g + 0.114 * b)
    if brightness < 40:
        return "jet black"
    if brightness < 80:
        return "dark brown"
    if brightness < 130:
        return "medium brown"
    if brightness < 180:
        return "light brown"
    if r > 180 and g < 120:
        return "red"
    if r > 180 and g > 120:
        return "blonde"
    return "light"


def _estimate_hair_length(mask: np.ndarray) -> str:
    """Rough length estimate from mask height relative to image."""
    h = mask.shape[0]
    rows_with_hair = np.where(mask.any(axis=1))[0]
    if len(rows_with_hair) == 0:
        return "short"
    span = rows_with_hair[-1] - rows_with_hair[0]
    ratio = span / h
    if ratio < 0.20:
        return "very short"
    if ratio < 0.35:
        return "short"
    if ratio < 0.55:
        return "medium length"
    return "long"


def _estimate_texture(mask_region_bgr: np.ndarray) -> str:
    """Estimate texture by local variance (proxy for curl/wave)."""
    if len(mask_region_bgr) == 0:
        return "smooth"
    gray = cv2.cvtColor(mask_region_bgr, cv2.COLOR_BGR2GRAY)
    variance = float(gray.var())
    if variance < 200:
        return "very smooth, straight"
    if variance < 500:
        return "smooth with slight wave"
    if variance < 1000:
        return "wavy, medium texture"
    return "highly textured, coily or curly"


# ── Public API ────────────────────────────────────────────────────────────────

def extract_hair_mask(image_path: str, output_dir: str) -> str:
    """
    Extract the hair region from a reference image using BiSeNet (class 17).

    Args:
        image_path: Path to the reference photo (JPEG or PNG)
        output_dir: Directory to save the mask PNG

    Returns:
        Path to the saved hair mask PNG
    """
    if _BISENET_MODEL is None:
        _load_bisenet()

    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        raise ValueError(f"Could not read image: {image_path}")

    h, w = image_bgr.shape[:2]
    label_map = _run_bisenet(image_bgr)

    if label_map is not None:
        # Real BiSeNet: class 17 = hair
        hair_mask = (label_map == 17).astype(np.uint8) * 255
        # Also keep class 18 (hat) since it sits in the hair area
        hat_mask  = (label_map == 18).astype(np.uint8) * 255
        hair_mask = cv2.bitwise_or(hair_mask, hat_mask)
    else:
        # Stub: use upper-third of the image as a rough hair region
        logger.warning("[style_extractor] BiSeNet unavailable — using stub hair mask")
        hair_mask = np.zeros((h, w), dtype=np.uint8)
        hair_mask[: h // 3, :] = 255

    # Clean up the mask with morphological ops
    kernel    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    hair_mask = cv2.morphologyEx(hair_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    hair_mask = cv2.morphologyEx(hair_mask, cv2.MORPH_OPEN,  kernel, iterations=1)

    out_path = Path(output_dir) / "hair_mask.png"
    cv2.imwrite(str(out_path), hair_mask)
    logger.info(f"[style_extractor] Hair mask saved: {out_path}")
    return str(out_path)


def describe_hairstyle(mask_path: str) -> str:
    """
    Generate a text description of the hairstyle from the hair mask image.

    On Day 2 this uses heuristics (color + length + texture estimates).
    In V2, replace the body of this function with a CLIP/vision model call.

    Args:
        mask_path: Path to the hair mask PNG produced by extract_hair_mask()

    Returns:
        A natural language description such as:
        "medium length box braids, smooth texture, dark brown color"
    """
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        logger.error(f"[style_extractor] Could not read mask: {mask_path}")
        return "stylish hairstyle"

    # Try to load the original image alongside the mask (same directory, named reference.jpg)
    mask_dir  = Path(mask_path).parent
    orig_path = mask_dir / "reference.jpg"
    orig_bgr  = cv2.imread(str(orig_path)) if orig_path.exists() else None

    # ── Length estimate from mask ─────────────────────────────────────────────
    length = _estimate_hair_length(mask)

    # ── Color and texture from masked pixels ──────────────────────────────────
    if orig_bgr is not None and orig_bgr.shape[:2] == mask.shape:
        hair_pixels = orig_bgr[mask > 128]
        color       = _dominant_color_name(hair_pixels)
        texture     = _estimate_texture(
            orig_bgr[mask > 128].reshape(-1, 1, 3).astype(np.uint8)
            if len(orig_bgr[mask > 128]) > 0
            else np.zeros((1, 1, 3), dtype=np.uint8)
        )
    else:
        color   = "dark"
        texture = "smooth"

    description = f"{length} hair, {texture}, {color} color"

    logger.info(f"[style_extractor] Generated description: '{description}'")
    return description


# ── CLI test harness ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, tempfile

    if len(sys.argv) < 2:
        print("Usage: python style_extractor.py <image_path>")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        mask = extract_hair_mask(sys.argv[1], tmpdir)
        print(f"Mask saved: {mask}")
        desc = describe_hairstyle(mask)
        print(f"Description: {desc}")
