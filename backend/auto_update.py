"""
auto_update.py
-----------------
Checks GitHub for a newer release of this app on startup, and - if the
user agrees - downloads the new .exe and swaps it in for the one
currently running.

Windows won't let a running .exe overwrite itself, so the actual swap
happens via a small batch script: it waits for this process to fully
exit, replaces the old .exe with the newly-downloaded one, relaunches
it, then deletes itself. launcher.py is responsible for shutting the
app down cleanly (closing the UI, unhooking hotkeys) right after
calling launch_swap_script() here, so the process actually exits and
the script's wait-loop can proceed.

Only does anything when running as a packaged .exe (sys.frozen) -
there's nothing to self-update when running from plain source.

Bump CURRENT_VERSION here every time a new release is tagged/published -
this is the only place that number lives.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request

CURRENT_VERSION = "1.6.5"
REPO = "xdjackey/Anime-Squadron-Macro"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "AnimeSquadronMacro.exe"
REQUEST_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 120


def _parse_version(v):
    """'v1.6.0' -> (1, 6, 0), so versions compare numerically instead of
    as strings (which would sort '1.10.0' before '1.9.0')."""
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update(log=print):
    """Hits the GitHub releases API once. Returns (version, download_url)
    if a newer release is available, or None if already up to date, the
    check failed (no internet, GitHub unreachable, rate-limited), or the
    release has no matching .exe asset attached. Never raises - a failed
    check should never stop the app from starting normally."""
    try:
        req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.load(resp)

        latest_tag = data.get("tag_name", "")
        if not latest_tag or _parse_version(latest_tag) <= _parse_version(CURRENT_VERSION):
            return None

        for asset in data.get("assets", []):
            if asset.get("name") == ASSET_NAME:
                return latest_tag, asset["browser_download_url"]

        log(f"[update] Found {latest_tag} but it has no {ASSET_NAME} asset attached - skipping.", "warning")
        return None
    except Exception as e:
        log(f"[update] Update check failed (non-fatal): {e}", "warning")
        return None


def check_for_update_async(on_update_found, log=print):
    """Runs check_for_update() on a background thread so it can never
    delay app startup. Calls on_update_found(version, url) FROM THAT
    BACKGROUND THREAD if an update is available - the caller must hop
    back to the main thread (e.g. root.after) before touching any UI
    from it."""
    def worker():
        result = check_for_update(log=log)
        if result:
            on_update_found(*result)
    threading.Thread(target=worker, daemon=True).start()


def download_update(download_url, log=print):
    """Downloads the new .exe to the same folder as the current one
    (named *_new.exe - doesn't touch the running one) and returns its
    path. Raises on failure; the caller decides how to report that."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("not running as a packaged .exe - nothing to update")

    app_dir = os.path.dirname(sys.executable)
    new_exe = os.path.join(app_dir, "AnimeSquadronMacro_new.exe")

    log("[update] Downloading update...", "info")
    req = urllib.request.Request(download_url, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        next_log_pct = 25
        with open(new_exe, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    if pct >= next_log_pct:
                        log(f"[update] Downloaded {next_log_pct}%...", "info")
                        next_log_pct += 25

    log("[update] Download complete.", "success")
    return new_exe


def launch_swap_script(new_exe_path, log=print):
    """Writes a small batch script that waits for THIS process to exit,
    replaces the running .exe with the newly-downloaded one, relaunches
    it, then deletes itself - and launches that script detached (so it
    keeps running after this process exits). Does NOT exit this process
    itself - the caller must shut the app down cleanly right after
    calling this (see LauncherApp.on_close), so the process actually
    exits and the script's wait-loop can proceed."""
    current_exe = sys.executable
    pid = os.getpid()

    bat_path = os.path.join(tempfile.gettempdir(), "asm_update.bat")
    bat_contents = (
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'move /y "{new_exe_path}" "{current_exe}" >nul\r\n'
        f'start "" "{current_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    with open(bat_path, "w") as f:
        f.write(bat_contents)

    log("[update] Restarting to finish updating...", "success")
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
