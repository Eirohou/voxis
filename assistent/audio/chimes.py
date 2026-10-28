"""Pure Python audio synthesizer and chime player for Assistent.

Generates soft, pleasant chime sounds in memory using math, struct, and wave.
Plays audio via pw-play or aplay in a non-blocking background thread or subprocess.
"""

import io
import logging
import math
import shutil
import struct
import subprocess
import threading
from typing import List, Optional, Tuple, Union
import wave

logger = logging.getLogger(__name__)


def generate_tone(
    freq_start: float,
    freq_end: float,
    duration_ms: int,
    sample_rate: int = 16000,
    volume: float = 0.45,
    envelope: str = "hann",
) -> bytes:
    """Synthesize a single frequency sweep or steady tone into WAV bytes.

    Args:
        freq_start: Starting frequency in Hz.
        freq_end: Ending frequency in Hz.
        duration_ms: Duration in milliseconds.
        sample_rate: Audio sampling rate in Hz (default 16000).
        volume: Amplitude multiplier between 0.0 and 1.0 (default 0.45).
        envelope: Smoothing envelope ("hann", "cosine", or "trapezoid").

    Returns:
        bytes: Complete WAV file binary data (16-bit PCM mono).
    """
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    if num_samples <= 0:
        return b""

    T = duration_ms / 1000.0
    samples: List[int] = []

    for i in range(num_samples):
        t = i / sample_rate

        # Envelope calculation for click-free start and finish
        if envelope == "hann":
            env = 0.5 * (1.0 - math.cos(2.0 * math.pi * i / (num_samples - 1))) if num_samples > 1 else 1.0
        elif envelope == "trapezoid":
            attack_samples = min(int(sample_rate * 0.01), num_samples // 4)
            decay_samples = min(int(sample_rate * 0.02), num_samples // 4)
            if i < attack_samples and attack_samples > 0:
                env = i / attack_samples
            elif i > num_samples - decay_samples and decay_samples > 0:
                env = (num_samples - i) / decay_samples
            else:
                env = 1.0
        else:
            # Default cosine taper
            env = math.sin(math.pi * i / (num_samples - 1)) if num_samples > 1 else 1.0

        # Frequency sweep phase calculation: integral of (f0 + (f1 - f0)/T * tau) d_tau
        phase = 2.0 * math.pi * (freq_start * t + ((freq_end - freq_start) / (2.0 * T)) * (t**2))
        raw_val = volume * env * math.sin(phase) * 32767.0
        sample_val = int(max(-32768, min(32767, round(raw_val))))
        samples.append(sample_val)

    packed_data = struct.pack(f"<{len(samples)}h", *samples)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(packed_data)

    return buf.getvalue()


def generate_tones_sequence(
    tone_specs: List[Tuple[float, float, int, float]],
    sample_rate: int = 16000,
    pause_ms: int = 40,
) -> bytes:
    """Generate a sequence of tones with optional pause into a single WAV file.

    Args:
        tone_specs: List of tuples (freq_start, freq_end, duration_ms, volume).
        sample_rate: Audio sampling rate in Hz.
        pause_ms: Pause duration between tones in milliseconds.

    Returns:
        bytes: Complete WAV file binary data.
    """
    all_samples: List[int] = []
    pause_samples_count = int(sample_rate * (pause_ms / 1000.0))

    for idx, (f_start, f_end, dur_ms, vol) in enumerate(tone_specs):
        num_samples = int(sample_rate * (dur_ms / 1000.0))
        T = dur_ms / 1000.0
        for i in range(num_samples):
            t = i / sample_rate
            env = 0.5 * (1.0 - math.cos(2.0 * math.pi * i / (num_samples - 1))) if num_samples > 1 else 1.0
            phase = 2.0 * math.pi * (f_start * t + ((f_end - f_start) / (2.0 * T)) * (t**2))
            val = int(max(-32768, min(32767, round(vol * env * math.sin(phase) * 32767.0))))
            all_samples.append(val)

        # Insert silence between tones (not after the final tone)
        if idx < len(tone_specs) - 1 and pause_samples_count > 0:
            all_samples.extend([0] * pause_samples_count)

    packed_data = struct.pack(f"<{len(all_samples)}h", *all_samples)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(packed_data)

    return buf.getvalue()


# Specific Chime Generators


def generate_start_chime(sample_rate: int = 16000) -> bytes:
    """Generate soft ascending tone (520Hz -> 660Hz, 120ms)."""
    return generate_tone(520.0, 660.0, duration_ms=120, sample_rate=sample_rate, volume=0.45)


def generate_stop_chime(sample_rate: int = 16000) -> bytes:
    """Generate soft descending tone (660Hz -> 440Hz, 120ms)."""
    return generate_tone(660.0, 440.0, duration_ms=120, sample_rate=sample_rate, volume=0.45)


def generate_action_chime(sample_rate: int = 16000) -> bytes:
    """Generate very brief subtle click/blip (750Hz, 40ms) for volume/media changes."""
    return generate_tone(750.0, 750.0, duration_ms=40, sample_rate=sample_rate, volume=0.35)


def generate_alert_chime(sample_rate: int = 16000) -> bytes:
    """Generate two-tone chime for timer expiration (D5 587Hz -> A5 880Hz)."""
    return generate_tones_sequence(
        [
            (587.33, 587.33, 140, 0.45),
            (880.0, 880.0, 220, 0.45),
        ],
        sample_rate=sample_rate,
        pause_ms=40,
    )


# Playback Engine


def _find_audio_player() -> Optional[Tuple[str, List[str]]]:
    """Find available audio player command line."""
    pw_play = shutil.which("pw-play")
    if pw_play:
        return pw_play, [pw_play, "-"]
    aplay = shutil.which("aplay")
    if aplay:
        return aplay, [aplay, "-q", "-"]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        # ffmpeg output to system default if nothing else
        return ffmpeg, [ffmpeg, "-v", "quiet", "-i", "pipe:0", "-f", "alsa", "default"]
    return None


def play_wav_bytes(
    wav_bytes: bytes,
    non_blocking: bool = True,
) -> Optional[Union[threading.Thread, subprocess.Popen]]:
    """Play WAV audio bytes using pw-play or aplay.

    Args:
        wav_bytes: Binary WAV data to play.
        non_blocking: Whether to play in a background thread/process (default True).

    Returns:
        threading.Thread if non_blocking=True and started, else None.
    """
    player_info = _find_audio_player()
    if not player_info:
        logger.warning("No audio player found (pw-play, aplay, ffmpeg). Cannot play chime.")
        return None

    _, cmd = player_info

    def _play_worker() -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=wav_bytes)
        except Exception as e:
            logger.debug("Audio playback error: %s", e)

    if non_blocking:
        thread = threading.Thread(target=_play_worker, name="ChimePlayerThread", daemon=True)
        thread.start()
        return thread
    else:
        _play_worker()
        return None


def play_start_chime(non_blocking: bool = True) -> Optional[Union[threading.Thread, subprocess.Popen]]:
    """Play soft ascending chime (assistant started listening)."""
    wav_bytes = generate_start_chime()
    return play_wav_bytes(wav_bytes, non_blocking=non_blocking)


def play_stop_chime(non_blocking: bool = True) -> Optional[Union[threading.Thread, subprocess.Popen]]:
    """Play soft descending chime (assistant stopped listening)."""
    wav_bytes = generate_stop_chime()
    return play_wav_bytes(wav_bytes, non_blocking=non_blocking)


def play_action_chime(non_blocking: bool = True) -> Optional[Union[threading.Thread, subprocess.Popen]]:
    """Play brief subtle blip (action triggered, volume change, etc.)."""
    wav_bytes = generate_action_chime()
    return play_wav_bytes(wav_bytes, non_blocking=non_blocking)


def play_alert_chime(non_blocking: bool = True) -> Optional[Union[threading.Thread, subprocess.Popen]]:
    """Play two-tone alert chime (timer expired or alarm)."""
    wav_bytes = generate_alert_chime()
    return play_wav_bytes(wav_bytes, non_blocking=non_blocking)
