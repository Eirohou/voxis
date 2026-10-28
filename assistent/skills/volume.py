"""Volume and mute control skill using wpctl."""

import subprocess
from assistent.skills.base import tool


@tool(silent_feedback=True)
def volume_control(change: str) -> str:
    """Control system volume or toggle mute using wpctl."""
    val = (change or "").strip()
    if not val:
        return "Volume change or mute action must be specified."

    val_lower = val.lower()
    if val_lower in ("mute", "toggle", "toggle-mute", "mute-toggle", "unmute"):
        cmd = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]
    else:
        # Normalize relative adjustments
        if val_lower == "up":
            target = "5%+"
        elif val_lower == "down":
            target = "5%-"
        elif val.startswith("+") and val.endswith("%"):
            target = val[1:] + "+"
        elif val.startswith("-") and val.endswith("%"):
            target = val[1:] + "-"
        else:
            target = val
        cmd = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", target]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            if "set-mute" in cmd:
                return "Audio mute toggled."
            return f"Volume set to {cmd[-1]}."
        return f"Volume control failed: {res.stderr.strip() or 'wpctl command returned error.'}"
    except Exception as e:
        return f"Failed to execute volume control: {e}"
