"""Timer skill for setting non-blocking desktop reminders and alarms."""

from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from assistent.skills.base import tool


def trigger_alarm(label: str = "Timer") -> None:
    """Execute desktop notification and audio alarm when timer expires."""
    try:
        subprocess.run(["notify-send", "Timer Expired", label], check=False)
    except Exception:
        pass

    played = False
    if shutil.which("canberra-gtk-play"):
        try:
            res = subprocess.run(
                ["canberra-gtk-play", "-i", "alarm-clock-elapsed"],
                capture_output=True,
                check=False,
            )
            if res.returncode == 0:
                played = True
        except Exception:
            pass

    if not played:
        sound_candidates = [
            "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
            "/usr/share/sounds/freedesktop/stereo/complete.oga",
            "/usr/share/sounds/freedesktop/stereo/bell.oga",
        ]
        player = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
        if player:
            for sound in sound_candidates:
                if Path(sound).is_file():
                    try:
                        subprocess.run([player, sound], check=False)
                        played = True
                        break
                    except Exception:
                        pass

    if not played:
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass


def _timer_worker(seconds: int, label: str) -> None:
    """Worker function that sleeps then triggers alarm."""
    time.sleep(seconds)
    trigger_alarm(label)


@tool
def set_timer(seconds: int, label: str = "Timer") -> str:
    """Set a non-blocking countdown timer in seconds with an optional label."""
    if seconds < 0:
        return "Timer seconds cannot be negative."

    thread = threading.Thread(
        target=_timer_worker,
        args=(seconds, label),
        daemon=True,
    )
    thread.start()
    return f"Timer set for {seconds} seconds ({label})."
