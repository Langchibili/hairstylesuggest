"""
face_analysis.py
────────────────
Analyses a source image using MediaPipe (head pose) and BiSeNet (hair/skin segmentation).

Returns a dict compatible with the prompt_builder.py inputs.

BiSeNet class map (the ones we use):
  1  = skin
  10 = nose
  13 = l/r ear
  17 = hair
  18 = hat
  16 = cloth

Usage:
  from face_analysis import analyse_face
  result = analyse_face("/path/to/image.jpg")
  # result: { head_pose, skin_tone_hex, skin_tone_fitzpatrick, hair_mask_path, face_bbox }
"""

import os
import math
import time
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from loguru import logger

# ── MediaPipe ──────────────────────────────────────────────────────────────────
try:
    import mediapipe as mp
    _mp_face_mesh = mp.solutions.face_mesh
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logger.warning("MediaPipe not installed — head pose estimation unavailable.")

# ── BiSeNet ────────────────────────────────────────────────────────────────────
# BiSeNet is loaded as a TorchScript model or via a lightweight wrapper.
# If you have the full BiSeNet weights, replace this stub with real inference.
BISENET_MODEL = None

def _load_bisenet():
    """
    Attempt to load a BiSeNet model.
    Replace this with your actual model loading logic once you have the weights.
    On Day 2, this can remain as a stub that returns a blank mask — the worker
    will still operate; just the mask will be empty.
    """
    global BISENET_MODEL
    model_path = os.getenv("BISENET_MODEL_PATH", "")
    if model_path and Path(model_path).exists():
        try:
            import torch
            BISENET_MODEL = torch.jit.load(model_path, map_location="cpu")
            BISENET_MODEL.eval()
            logger.info(f"BiSeNet loaded from {model_path}")
        except Exception as e:
            logger.error(f"Failed to load BiSeNet: {e}")
    else:
        logger.warning("BISENET_MODEL_PATH not set or file missing — using stub segmentation.")


def _bisenet_parse(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """
    Run BiSeNet face parsing on a BGR image.
    Returns a label map (H × W) where each pixel is a class index, or None on failure.
    """
    if BISENET_MODEL is None:
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
        pil_img = Image.fromarray(img_rgb)
        tensor  = transform(pil_img).unsqueeze(0)

        with torch.no_grad():
            out = BISENET_MODEL(tensor)[0]
            label_map = out.squeeze(0).argmax(0).numpy().astype(np.uint8)

        # Resize label map back to original image size
        label_map = cv2.resize(
            label_map,
            (image_bgr.shape[1], image_bgr.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
        return label_map

    except Exception as e:
        logger.error(f"BiSeNet inference error: {e}")
        return None


def extract_hair_mask(image_bgr: np.ndarray, label_map: Optional[np.ndarray]) -> np.ndarray:
    """
    Extract a binary mask of the hair region (class 17).
    Returns a uint8 mask (255 = hair, 0 = not hair).
    """
    if label_map is None:
        # Stub: return an upper-third mask as a rough hair approximation
        h, w = image_bgr.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[: h // 3, :] = 255
        return mask

    return (label_map == 17).astype(np.uint8) * 255


def extract_skin_pixels(image_bgr: np.ndarray, label_map: Optional[np.ndarray]) -> np.ndarray:
    """
    Extract skin pixels (class 1) as a flattened RGB array for color analysis.
    """
    if label_map is None:
        # Stub: sample the forehead area
        h, w = image_bgr.shape[:2]
        region = image_bgr[h // 5 : h // 3, w // 4 : 3 * w // 4]
        region_rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
        return region_rgb.reshape(-1, 3)

    skin_mask = (label_map == 1)
    img_rgb   = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    return img_rgb[skin_mask]


# ── Fitzpatrick scale ──────────────────────────────────────────────────────────

# Each entry: (max_L_value_in_LAB, fitzpatrick_type, prompt_descriptor)
FITZPATRICK_MAP = [
    (72,  "I",   "very fair, pale skin, light complexion"),
    (65,  "II",  "fair skin, light beige complexion"),
    (58,  "III", "medium skin, warm olive complexion"),
    (50,  "IV",  "olive skin, medium-dark complexion"),
    (42,  "V",   "dark brown skin, rich complexion"),
    (0,   "VI",  "deep dark skin, very rich complexion"),
]


def skin_tone_to_fitzpatrick(skin_pixels_rgb: np.ndarray) -> tuple[str, str, str]:
    """
    Given an array of skin-region RGB pixels, return:
      (hex_color, fitzpatrick_type, text_descriptor)
    """
    if len(skin_pixels_rgb) == 0:
        return ("#C68642", "IV", "olive skin, medium-dark complexion")

    # Median is more robust than mean against outliers
    median_rgb  = np.median(skin_pixels_rgb, axis=0).astype(np.uint8)
    hex_color   = "#{:02X}{:02X}{:02X}".format(*median_rgb)

    # Convert to CIE L*a*b* for perceptual lightness
    median_bgr  = median_rgb[::-1].reshape(1, 1, 3)
    lab         = cv2.cvtColor(median_bgr.astype(np.uint8), cv2.COLOR_BGR2LAB)
    L_value     = int(lab[0, 0, 0])  # 0–255 in OpenCV LAB

    for max_L, fitz_type, descriptor in FITZPATRICK_MAP:
        if L_value > max_L:
            return (hex_color, fitz_type, descriptor)

    return (hex_color, "VI", "deep dark skin, very rich complexion")


# ── Head pose via MediaPipe ────────────────────────────────────────────────────

# The 3D model points from MediaPipe's canonical face model used for solvePnP.
_MODEL_POINTS = np.array([
    (0.0,    0.0,    0.0),     # Nose tip (landmark 1)
    (0.0,   -330.0, -65.0),   # Chin (landmark 152)
    (-225.0,  170.0, -135.0), # Left eye corner (landmark 33)
    (225.0,  170.0, -135.0),  # Right eye corner (landmark 263)
    (-150.0, -150.0, -125.0), # Left mouth corner (landmark 61)
    (150.0, -150.0, -125.0),  # Right mouth corner (landmark 291)
], dtype=np.float64)

_LANDMARK_INDICES = [1, 152, 33, 263, 61, 291]


def estimate_head_pose(image_bgr: np.ndarray) -> dict:
    """
    Estimate head pose (yaw, pitch, roll) in degrees using MediaPipe Face Mesh
    and OpenCV solvePnP.

    Returns:
      { yaw: float, pitch: float, roll: float }
      yaw   > 0 → facing left; < 0 → facing right
      pitch > 0 → looking up;  < 0 → looking down
      roll  = head tilt
    """
    if not MEDIAPIPE_AVAILABLE:
        return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

    h, w = image_bgr.shape[:2]
    img_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    with _mp_face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as face_mesh:
        results = face_mesh.process(img_rgb)

    if not results.multi_face_landmarks:
        logger.warning("MediaPipe: no face detected in image")
        return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

    landmarks = results.multi_face_landmarks[0].landmark

    image_points = np.array([
        (landmarks[idx].x * w, landmarks[idx].y * h)
        for idx in _LANDMARK_INDICES
    ], dtype=np.float64)

    focal_length  = w
    camera_matrix = np.array([
        [focal_length, 0,            w / 2],
        [0,            focal_length, h / 2],
        [0,            0,            1    ],
    ], dtype=np.float64)

    dist_coeffs = np.zeros((4, 1))  # Assume no lens distortion

    success, rot_vec, _ = cv2.solvePnP(
        _MODEL_POINTS, image_points, camera_matrix, dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )

    if not success:
        return {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}

    rot_mat, _ = cv2.Rodrigues(rot_vec)
    # Decompose to Euler angles
    sy    = math.sqrt(rot_mat[0, 0] ** 2 + rot_mat[1, 0] ** 2)
    pitch = math.degrees(math.atan2(-rot_mat[2, 0], sy))
    yaw   = math.degrees(math.atan2(rot_mat[2, 1], rot_mat[2, 2]))
    roll  = math.degrees(math.atan2(rot_mat[1, 0], rot_mat[0, 0]))

    return {
        "yaw":   round(yaw,   2),
        "pitch": round(pitch, 2),
        "roll":  round(roll,  2),
    }


def detect_face_bbox(image_bgr: np.ndarray) -> Optional[dict]:
    """
    Detect the primary face bounding box using MediaPipe.
    Returns { x, y, width, height } as fractions of image dimensions, or None.
    """
    if not MEDIAPIPE_AVAILABLE:
        return None

    h, w = image_bgr.shape[:2]
    img_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    with _mp_face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        min_detection_confidence=0.5,
    ) as face_mesh:
        results = face_mesh.process(img_rgb)

    if not results.multi_face_landmarks:
        return None

    xs = [lm.x for lm in results.multi_face_landmarks[0].landmark]
    ys = [lm.y for lm in results.multi_face_landmarks[0].landmark]

    return {
        "x":      round(min(xs), 4),
        "y":      round(min(ys), 4),
        "width":  round(max(xs) - min(xs), 4),
        "height": round(max(ys) - min(ys), 4),
    }


# ── Main entrypoint ────────────────────────────────────────────────────────────

def analyse_face(image_path: str, save_hair_mask: bool = True) -> dict:
    """
    Full face analysis pipeline.

    Args:
      image_path     : Path to the input image (JPEG or PNG).
      save_hair_mask : If True, saves the hair mask to a temp file and includes the path.

    Returns:
      {
        head_pose:            { yaw, pitch, roll },
        skin_tone_hex:        "#C68642",
        skin_tone_fitzpatrick: "IV",
        skin_tone_descriptor: "olive skin, medium-dark complexion",
        hair_mask_path:       "/tmp/hair_mask_abc123.png" | None,
        face_bbox:            { x, y, width, height } | None,
        analysis_time_ms:     123,
      }
    """
    t0 = time.time()

    if not Path(image_path).exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image_bgr = cv2.imread(str(image_path))
    if image_bgr is None:
        raise ValueError(f"Could not read image: {image_path}")

    logger.info(f"[face_analysis] Processing {image_path} ({image_bgr.shape[1]}×{image_bgr.shape[0]})")

    # Load BiSeNet lazily
    if BISENET_MODEL is None:
        _load_bisenet()

    # Run BiSeNet segmentation
    label_map   = _bisenet_parse(image_bgr)

    # Extract hair mask
    hair_mask   = extract_hair_mask(image_bgr, label_map)
    mask_path   = None
    if save_hair_mask and hair_mask is not None:
        tmp = tempfile.NamedTemporaryFile(suffix="_hair_mask.png", delete=False)
        cv2.imwrite(tmp.name, hair_mask)
        mask_path = tmp.name
        logger.debug(f"[face_analysis] Hair mask saved to {mask_path}")

    # Skin tone classification
    skin_pixels = extract_skin_pixels(image_bgr, label_map)
    hex_color, fitz_type, fitz_descriptor = skin_tone_to_fitzpatrick(skin_pixels)

    # Head pose estimation
    head_pose   = estimate_head_pose(image_bgr)

    # Face bounding box
    face_bbox   = detect_face_bbox(image_bgr)

    elapsed_ms  = round((time.time() - t0) * 1000, 1)

    result = {
        "head_pose":             head_pose,
        "skin_tone_hex":         hex_color,
        "skin_tone_fitzpatrick": fitz_type,
        "skin_tone_descriptor":  fitz_descriptor,
        "hair_mask_path":        mask_path,
        "face_bbox":             face_bbox,
        "analysis_time_ms":      elapsed_ms,
    }

    logger.info(
        f"[face_analysis] Done in {elapsed_ms}ms — "
        f"pose: yaw={head_pose['yaw']}°, pitch={head_pose['pitch']}° — "
        f"skin: {fitz_type} ({hex_color})"
    )
    return result


# ── CLI test harness ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python face_analysis.py <image_path>")
        sys.exit(1)

    result = analyse_face(sys.argv[1])
    print(json.dumps(result, indent=2))
