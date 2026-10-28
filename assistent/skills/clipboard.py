"""Clipboard management skill using wl-paste and wl-copy."""

import subprocess
from assistent.skills.base import tool


@tool
def read_clipboard() -> str:
    """Read current content from Wayland clipboard via wl-paste."""
    try:
        res = subprocess.run(
            ["wl-paste"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout
        return f"Failed to read clipboard: {res.stderr.strip() or 'Clipboard is empty or inaccessible.'}"
    except Exception as e:
        return f"Error reading clipboard: {e}"


@tool
def write_clipboard(text: str) -> str:
    """Write text to Wayland clipboard via wl-copy."""
    try:
        res = subprocess.run(
            ["wl-copy"],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return "Copied to clipboard."
        return f"Failed to write to clipboard: {res.stderr.strip() or 'wl-copy exited with error.'}"
    except Exception as e:
        return f"Error writing to clipboard: {e}"
