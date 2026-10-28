"""Media control skill using playerctl."""

import subprocess
from assistent.skills.base import tool

ACTION_MAP = {
    "play": "play",
    "pause": "pause",
    "play-pause": "play-pause",
    "play_pause": "play-pause",
    "playpause": "play-pause",
    "toggle": "play-pause",
    "next": "next",
    "previous": "previous",
    "prev": "previous",
    "stop": "stop",
}


@tool(silent_feedback=True)
def media_control(action: str) -> str:
    """Control media playback using playerctl (play, pause, play-pause, next, previous)."""
    clean_action = (action or "").strip().lower()
    if clean_action not in ACTION_MAP:
        return (
            f"Unsupported media action: '{action}'. "
            "Supported actions: play, pause, play-pause, next, previous."
        )

    cmd_action = ACTION_MAP[clean_action]
    try:
        res = subprocess.run(
            ["playerctl", cmd_action],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return f"Media {cmd_action} executed."

        stderr_msg = res.stderr.strip()
        if "No players found" in stderr_msg or "Could not connect" in stderr_msg:
            return "No active media player found."
        return f"Media control failed: {stderr_msg or 'Playerctl exited with error.'}"
    except Exception as e:
        return f"Failed to execute media control: {e}"
