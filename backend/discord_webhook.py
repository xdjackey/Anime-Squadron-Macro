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
    """bbox is (left, top, width, height) in absolute screen coordinates -
    this should be the Roblox window's own rect, not the full monitor,
    so the control panel/logs never end up in the screenshot."""
    left, top, width, height = bbox
    with mss.mss() as sct:
        region = {"left": left, "top": top, "width": width, "height": height}
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def send_screenshot(webhook_url, bbox, message=None, log=print):
    """Captures the given screen region and posts it to a Discord
    webhook as an image attachment, with an optional text message.
    Runs synchronously (blocks on the network call) - use
    send_screenshot_async from the automation thread so a slow upload
    can't stall the actual mission sequence.

    Returns True on success, False on any failure (missing URL, capture
    error, or a non-2xx response from Discord) - failures are logged,
    not raised, since a missed screenshot shouldn't abort a mission."""
    if not webhook_url:
        log("[discord] No webhook URL set - skipping screenshot.")
        return False

    try:
        buf = _capture_region(bbox)
    except Exception as e:
        log(f"[discord] Couldn't capture the Roblox window: {e}")
        return False

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


def send_screenshot_async(webhook_url, bbox, message=None, log=print):
    """Fire-and-forget version of send_screenshot - runs the capture and
    upload on a background thread so the caller (the automation loop)
    doesn't wait on a Discord network round-trip between runs."""
    threading.Thread(
        target=send_screenshot, args=(webhook_url, bbox, message, log), daemon=True,
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
