"""
discord_webhook.py
--------------------
Sends a screenshot of JUST the Roblox window (not the control panel or
logs) to a Discord webhook, with an optional text message attached.

Requires: requests, mss, pillow   (pip install requests mss pillow --break-system-packages)
"""

import io
import threading

import mss
import requests
from PIL import Image


def _capture_region(bbox):
    """bbox is (left, top, width, height) - pass Roblox's own window
    rect, not the full monitor, so the panel/logs stay out of the shot."""
    left, top, width, height = bbox
    with mss.mss() as sct:
        region = {"left": left, "top": top, "width": width, "height": height}
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _upload_screenshot(webhook_url, buf, message, log):
    try:
        files = {"file": ("roblox.png", buf, "image/png")}
        data = {"content": message} if message else {}
        resp = requests.post(webhook_url, data=data, files=files, timeout=15)
        if resp.status_code >= 300:
            log(f"[discord] Webhook responded with {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"[discord] Failed to send screenshot: {e}")
        return False


def send_screenshot(webhook_url, bbox, message=None, log=print):
    """Captures bbox and posts it to a Discord webhook as an image, with
    an optional message. Runs synchronously - use send_screenshot_async
    from the automation thread. Returns True/False; never raises."""
    if not webhook_url:
        log("[discord] No webhook URL set - skipping screenshot.")
        return False

    try:
        buf = _capture_region(bbox)
    except Exception as e:
        log(f"[discord] Couldn't capture the Roblox window: {e}")
        return False

    return _upload_screenshot(webhook_url, buf, message, log)


def send_screenshot_async(webhook_url, bbox, message=None, log=print):
    """Captures bbox IMMEDIATELY, on the calling thread - only the
    (slow) network upload is deferred to a background thread.

    This matters: the caller confirms the results screen, then calls
    this, then goes on to read trait shards and let the game auto-
    replay into the NEXT match - all within a few seconds. Capturing on
    a background thread meant the actual mss.grab() didn't happen until
    that thread got scheduled, which could land AFTER the next match had
    already started, screenshotting the wrong thing entirely."""
    if not webhook_url:
        log("[discord] No webhook URL set - skipping screenshot.")
        return
    try:
        buf = _capture_region(bbox)
    except Exception as e:
        log(f"[discord] Couldn't capture the Roblox window: {e}")
        return
    threading.Thread(
        target=_upload_screenshot, args=(webhook_url, buf, message, log), daemon=True,
    ).start()


def send_message(webhook_url, message, log=print):
    """Posts a plain text message to a Discord webhook - no screenshot.
    Runs synchronously; use send_message_async from the automation
    thread. Returns True on success, False on any failure (same
    failure handling as send_screenshot)."""
    if not webhook_url:
        log("[discord] No webhook URL set - skipping message.")
        return False
    try:
        resp = requests.post(webhook_url, json={"content": message}, timeout=15)
        if resp.status_code >= 300:
            log(f"[discord] Webhook responded with {resp.status_code}: {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"[discord] Failed to send message: {e}")
        return False


def send_message_async(webhook_url, message, log=print):
    """Fire-and-forget version of send_message."""
    threading.Thread(
        target=send_message, args=(webhook_url, message, log), daemon=True,
    ).start()
