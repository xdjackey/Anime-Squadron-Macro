"""
screen.py
----------
Looks at your screen and checks whether a specific picture (a button,
a screen, etc.) is currently showing - and if so, where. Nothing about
moving the mouse or clicking lives here (that's mouse.py).

Given a set of named pictures saved in launcher_assets/ (made using
capture_icons.py), this answers one question: "is this thing on
screen right now, and if so, where?"

Requires: mss, numpy, opencv-python

Tip: if you erase the background of one of your saved pictures to be
see-through (using an image editor), this will automatically ignore
that see-through part when checking for a match - useful if a
picture's corners or background were making it harder to match
correctly.
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
# Widened back out from (0.85, 1.15) - that assumed capture-time and
# run-time always match, which only holds if everyone's on the same
# monitor size/resolution as whoever captured the icons. Users on other
# setups (not a 27" 1440p) were getting real icons that just never
# matched because their scale fell outside that narrow window.
DEFAULT_SCALE_RANGE = (0.65, 1.30)
CAPTURE_REFERENCE_WRITE_PATH = app_paths.path("capture_reference.json")
CAPTURE_REFERENCE_READ_PATH = app_paths.bundled_path("capture_reference.json")


def save_capture_reference(roblox_width, roblox_height):
    """Called by capture_icons.py right after docking, so
    icon matching later knows what size Roblox actually was when these
    icons were captured. Without this, matching only ever searches near
    1.0x scale - correct only if the current window happens to be the
    same size it was at capture time, which isn't true across different
    monitors/resolutions."""
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
    """If we know both the window size icons were captured at AND the
    window's current size, narrows the multi-scale search to center
    around the ACTUAL ratio between them, instead of always searching
    near 1.0x. This is what lets one set of captured icons keep working
    across different monitors/resolutions - a bigger current window
    means icons render bigger too, in roughly the same proportion, so
    centering the search on that expected ratio (rather than assuming
    capture-time and run-time sizes match) is what finds them."""
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

# Per-icon threshold overrides. Some icons (rounded buttons with a lot of
# shared background/corner noise, or subtle pulse/glow animations) settle
# at a lower natural match ceiling than others - forcing everything to
# one global threshold means those icons sit right at the cutoff and fail
# intermittently from tiny frame-to-frame variation. Add an entry here for
# any icon that keeps failing right around the default threshold.
THRESHOLD_OVERRIDES = {
    "create_room": 0.48,
    # Chapter buttons are nearly identical to EACH OTHER - same box, same
    # font, same "Chapter " prefix, differing only in one digit. Even with
    # a digit-only crop, visually similar digits (3 vs 8 in particular)
    # can still cross-match at a real-world score around 0.79 - so 0.85
    # sits comfortably above that false-positive range while staying
    # below the ~0.95-1.00 true matches actually observed in testing.
    "chapter_1": 0.85, "chapter_2": 0.85, "chapter_3": 0.85, "chapter_4": 0.85,
    "chapter_5": 0.85, "chapter_6": 0.85, "chapter_7": 0.85, "chapter_8": 0.85,
    "chapter_9": 0.85, "chapter_10": 0.85,
    # Leave still gets its own slightly stricter threshold - it's a bold-
    # white-text-on-colored-pill button, same family as Replay/Next which
    # sit right next to it on the result screen, so a loose threshold
    # risks a false match on one of those instead.
    "leave_button": 0.8,
    # Victory/Defeat banners share almost the same checkered background
    # and jagged banner shape - only the word itself differs, and that
    # word is a smaller fraction of the crop than the shared chrome. A
    # loose crop/threshold can match one banner against the OTHER
    # banner's shared background rather than its own text, misreporting
    # a win as a loss (or vice versa). Bumped up defensively; if this
    # still misfires, recrop both TIGHTER around just the word itself
    # (see check_icon.py / compare_icons.py to verify scores directly).
    "victory_screen": 0.8,
    "defeat_screen": 0.8,
}

# Masked matches (icons with a transparent background) use a different
# OpenCV method (TM_CCORR_NORMED) that tends to read a bit higher than the
# unmasked TM_CCOEFF_NORMED for the same visual match quality - so masked
# icons get their own slightly stricter baseline unless overridden above.
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
    """Returns the raw picture bytes for this key - from the single
    packed asset_data.py file if one exists, otherwise from the
    individual picture file in launcher_assets/. Returns None if
    neither has this key."""
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
    opaque crop (the common case) - it's only set if the PNG actually has
    a transparent background, in which case matching will ignore those
    transparent pixels entirely instead of comparing them."""
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


def _best_match(frame_gray, template, mask, scale_range, scale_steps):
    """Multi-scale template match. Returns (score, top_left, width, height).
    Uses masked matching (ignoring transparent pixels) when a mask is
    given, otherwise the normal unmasked comparison."""
    best_val = -1
    best_loc = None
    best_w, best_h = 0, 0
    th, tw = template.shape[:2]
    method = cv2.TM_CCORR_NORMED if mask is not None else cv2.TM_CCOEFF_NORMED

    for scale in np.linspace(scale_range[0], scale_range[1], scale_steps):
        rw_target = max(1, int(tw * scale))
        rh_target = max(1, int(th * scale))
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

    return best_val, best_loc, best_w, best_h


def find_icon_bbox(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE):
    """Like find_icon, but returns the match's top-left corner and size
    instead of just its center - (found, left, top, w, h, score). Useful
    when some OTHER piece of the screen needs to be located relative to
    this icon (e.g. the trait shard count printed next to the shard
    icon) rather than clicking the icon itself."""
    template, mask = _load_template(key)
    threshold = _threshold_for(key, threshold, masked=mask is not None)
    effective_range = _effective_scale_range(scale_range)
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        frame_gray = _grab_screen_gray(sct, monitor)
        score, loc, w, h = _best_match(frame_gray, template, mask, effective_range, SCALE_STEPS)
        if score >= threshold and loc is not None:
            left = monitor["left"] + loc[0]
            top = monitor["top"] + loc[1]
            return True, left, top, w, h, score
        return False, None, None, None, None, score


def find_icon(key, threshold=None, scale_range=DEFAULT_SCALE_RANGE):
    """Looks for one icon on screen right now (no scrolling, no clicking).
    Returns (found: bool, x: int, y: int, score: float) - x/y are the
    center of the match, in absolute screen coordinates."""
    template, mask = _load_template(key)
    threshold = _threshold_for(key, threshold, masked=mask is not None)
    effective_range = _effective_scale_range(scale_range)
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        frame_gray = _grab_screen_gray(sct, monitor)
        score, loc, w, h = _best_match(frame_gray, template, mask, effective_range, SCALE_STEPS)
        if score >= threshold and loc is not None:
            x = monitor["left"] + loc[0] + w // 2
            y = monitor["top"] + loc[1] + h // 2
            return True, x, y, score
        return False, None, None, score
