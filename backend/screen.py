"""
screen.py
----------
Checks whether a named picture (from launcher_assets/, made with
capture_icons.py) is currently showing on screen, and where. No mouse
or click logic here - see mouse.py.

Tip: an erased (transparent) background in a saved picture is
automatically ignored when matching - useful if a picture's background
was making it harder to match correctly.
"""

import json
import os
import numpy as np
import cv2
import mss

import display_info
import app_paths

ASSETS_DIR = app_paths.path("launcher_assets")

DEFAULT_THRESHOLD = 0.55
# Wide on purpose - covers users on a different monitor/resolution than
# whoever captured the icons, not just an exact capture-time match.
DEFAULT_SCALE_RANGE = (0.65, 1.30)
CAPTURE_REFERENCE_WRITE_PATH = app_paths.path("capture_reference.json")
CAPTURE_REFERENCE_READ_PATH = app_paths.bundled_path("capture_reference.json")


def save_capture_reference(roblox_width, roblox_height):
    """Called by capture_icons.py right after docking, so matching later
    knows what size Roblox was at capture time - without this, matching
    only ever searches near 1.0x scale."""
    with open(CAPTURE_REFERENCE_WRITE_PATH, "w") as f:
        json.dump({"roblox_width": roblox_width, "roblox_height": roblox_height}, f, indent=2)


def _load_capture_reference():
    if not os.path.exists(CAPTURE_REFERENCE_READ_PATH):
        return None
    try:
        with open(CAPTURE_REFERENCE_READ_PATH, "r") as f:
            data = json.load(f)
        return data["roblox_width"], data["roblox_height"]
    except Exception:
        return None


def _effective_scale_range(scale_range):
    """If we know both the capture-time and current Roblox window size,
    centers the multi-scale search on their actual ratio instead of
    1.0x - lets one set of captured icons work across resolutions."""
    reference = _load_capture_reference()
    if reference is None:
        return scale_range
    ref_w, _ = reference
    if not ref_w:
        return scale_range

    current = display_info.get_roblox_window_rect()
    if current is None:
        return scale_range
    _, _, cur_w, _ = current

    factor = cur_w / ref_w
    span = (scale_range[1] - scale_range[0]) / 2
    return (max(0.1, factor - span), factor + span)
SCALE_STEPS = 16

# Per-icon threshold overrides, for icons that keep failing/misfiring
# right around the default threshold.
THRESHOLD_OVERRIDES = {
    "create_room": 0.48,
    # Chapter buttons are near-identical except one digit - similar
    # digits (3 vs 8) can cross-match around 0.79, so 0.85 stays safely
    # above that while below the ~0.95+ true matches seen in testing.
    "chapter_1": 0.85, "chapter_2": 0.85, "chapter_3": 0.85, "chapter_4": 0.85,
    "chapter_5": 0.85, "chapter_6": 0.85, "chapter_7": 0.85, "chapter_8": 0.85,
    "chapter_9": 0.85, "chapter_10": 0.85,
    # Same family as Replay/Next on the result screen - stricter to avoid
    # a false match on those.
    "leave_button": 0.8,
    "retry_button": 0.8,
    # Victory/Defeat share almost the same banner background - only the
    # word differs, so a loose threshold can misread a win as a loss.
    "victory_screen": 0.8,
    "defeat_screen": 0.8,
    # Same "near-identical except one digit" problem as chapter_N above.
    "trait_shard_x1": 0.8,
    "trait_shard_x2": 0.8,
}

# Masked matches use TM_CCORR_NORMED, which reads a bit higher than the
# unmasked method for the same visual quality - hence the stricter baseline.
MASKED_DEFAULT_THRESHOLD = 0.92

_template_cache = {}  # key -> (gray_template, mask_or_None)


def _threshold_for(key, threshold, masked):
    """Resolves the threshold to use: an explicitly passed value always
    wins, otherwise a per-icon override, otherwise the appropriate
    default for whether this icon is using a mask."""
    if threshold is not None:
        return threshold
    if key in THRESHOLD_OVERRIDES:
        return THRESHOLD_OVERRIDES[key]
    return MASKED_DEFAULT_THRESHOLD if masked else DEFAULT_THRESHOLD


def _template_path(key):
    return os.path.join(ASSETS_DIR, f"{key}.png")


def _load_raw_image_bytes(key):
    """Raw picture bytes for this key - from packed asset_data.py if it
    exists, else the individual file in launcher_assets/. None if
    neither has it."""
    try:
        import asset_data
        encoded = asset_data.ASSETS.get(key)
        if encoded is not None:
            import base64
            return base64.b64decode(encoded)
    except ImportError:
        pass  # no packed asset_data.py - fall through to individual files

    path = _template_path(key)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _load_template(key):
    """Loads an icon as (gray_template, mask). mask is None for a normal
    opaque crop; only set if the PNG has a transparent background."""
    if key in _template_cache:
        return _template_cache[key]

    raw_bytes = _load_raw_image_bytes(key)
    if raw_bytes is None:
        raise FileNotFoundError(
            f"Missing picture for '{key}' - not in asset_data.py or "
            f"{_template_path(key)}. Run capture_icons.py to capture it."
        )
    raw = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise FileNotFoundError(
            f"Found data for '{key}' but couldn't read it as an image - it may be corrupted. "
            f"Run capture_icons.py to recapture it."
        )

    mask = None
    if raw.ndim == 3 and raw.shape[2] == 4:
        bgr = raw[:, :, :3]
        alpha = raw[:, :, 3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        _, alpha_mask = cv2.threshold(alpha, 10, 255, cv2.THRESH_BINARY)
        if cv2.countNonZero(alpha_mask) < alpha_mask.size:
            mask = alpha_mask  # only bother masking if it's NOT fully opaque
    else:
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY) if raw.ndim == 3 else raw

    _template_cache[key] = (gray, mask)
    return gray, mask


def _grab_screen_gray(sct, monitor):
    frame = np.array(sct.grab(monitor))
    return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)


def _best_match(frame_gray, template, mask, scale_range, scale_steps, downscale=1.0):
    """Multi-scale template match. Returns (score, top_left, width,
    height). Uses masked matching if a mask is given.

    downscale, if < 1.0, shrinks the frame (and the template by the same
    factor, so the scale_range's meaning is unchanged) before matching -
    matchTemplate's cost scales with pixel count, so this is a big win
    on a large search area where exact-pixel precision doesn't matter
    (just detecting presence/rough location). Returned coordinates are
    scaled back up to full resolution."""
    best_val = -1
    best_loc = None
    best_w, best_h = 0, 0
    th, tw = template.shape[:2]
    method = cv2.TM_CCORR_NORMED if mask is not None else cv2.TM_CCOEFF_NORMED

    if downscale != 1.0:
        fh, fw = frame_gray.shape[:2]
        frame_gray = cv2.resize(frame_gray, (max(1, int(fw * downscale)), max(1, int(fh * downscale))))

    for scale in np.linspace(scale_range[0], scale_range[1], scale_steps):
        eff_scale = scale * downscale
        rw_target = max(1, int(tw * eff_scale))
        rh_target = max(1, int(th * eff_scale))
        resized = cv2.resize(template, (rw_target, rh_target))
        rh, rw = resized.shape[:2]
        if rh >= frame_gray.shape[0] or rw >= frame_gray.shape[1]:
            continue

        if mask is not None:
            resized_mask = cv2.resize(mask, (rw_target, rh_target), interpolation=cv2.INTER_NEAREST)
            result = cv2.matchTemplate(frame_gray, resized, method, mask=resized_mask)
        else:
            result = cv2.matchTemplate(frame_gray, resized, method)

        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if not np.isfinite(max_val):
            continue

        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc
            best_w, best_h = rw, rh

    if downscale != 1.0 and best_loc is not None:
        best_loc = (int(best_loc[0] / downscale), int(best_loc[1] / downscale))
        best_w = int(best_w / downscale)
        best_h = int(best_h / downscale)

    return best_val, best_loc, best_w, best_h


def find_icon_bbox(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE, region=None, scale_steps=None,
                    downscale=1.0):
    """Like find_icon, but returns the match's top-left corner and size
    instead of just its center - (found, left, top, w, h, score). Useful
    for locating something relative to an icon rather than clicking it.

    region, if given, is (left, top, width, height) - restricts the
    search to that box, e.g. to search near an already-found anchor
    icon instead of risking a match elsewhere on screen.

    scale_steps, if given, overrides SCALE_STEPS for callers confident
    in a narrow scale_range, trading search precision for speed.

    downscale, if < 1.0, searches a shrunk copy of the frame - see
    _best_match. Useful when scanning a large region (a whole game
    window) where exact-pixel precision isn't needed."""
    template, mask = _load_template(key)
    threshold = _threshold_for(key, threshold, masked=mask is not None)
    effective_range = _effective_scale_range(scale_range)
    steps = scale_steps if scale_steps is not None else SCALE_STEPS
    with mss.mss() as sct:
        if region is not None:
            region_left, region_top, region_w, region_h = region
            monitor = {"left": region_left, "top": region_top, "width": region_w, "height": region_h}
        else:
            monitor = sct.monitors[0]
        frame_gray = _grab_screen_gray(sct, monitor)
        score, loc, w, h = _best_match(frame_gray, template, mask, effective_range, steps, downscale=downscale)
        if score >= threshold and loc is not None:
            left = monitor["left"] + loc[0]
            top = monitor["top"] + loc[1]
            return True, left, top, w, h, score
        return False, None, None, None, None, score


def find_icon(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE, region=None, scale_steps=None,
              downscale=1.0):
    """Looks for one icon on screen right now (no scrolling, no clicking).
    Returns (found: bool, x: int, y: int, score: float) - x/y are the
    center of the match, in absolute screen coordinates.

    region, scale_steps, downscale: same meaning as in find_icon_bbox -
    all default to the original whole-screen/full-precision behavior."""
    template, mask = _load_template(key)
    threshold = _threshold_for(key, threshold, masked=mask is not None)
    effective_range = _effective_scale_range(scale_range)
    steps = scale_steps if scale_steps is not None else SCALE_STEPS
    with mss.mss() as sct:
        if region is not None:
            region_left, region_top, region_w, region_h = region
            monitor = {"left": region_left, "top": region_top, "width": region_w, "height": region_h}
        else:
            monitor = sct.monitors[0]
        frame_gray = _grab_screen_gray(sct, monitor)
        score, loc, w, h = _best_match(frame_gray, template, mask, effective_range, steps, downscale=downscale)
        if score >= threshold and loc is not None:
            x = monitor["left"] + loc[0] + w // 2
            y = monitor["top"] + loc[1] + h // 2
            return True, x, y, score
        return False, None, None, score
