"""Audio recorder module using arecord and RMS-based voice activity detection (VAD).

Provides:
- 16kHz mono 16-bit PCM recording via `arecord` subprocess.
- Pure Python RMS energy calculation for audio chunks.
- Silence VAD: automatically terminates recording when speech ends and silence persists.
- Push-to-talk support via explicit start() and stop() methods.
- Packaging raw PCM into standard WAV format and saving to file or memory.
"""

import io
import logging
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time
from typing import IO, Any, List, Optional, Union
import wave

from assistent.config import get_config

logger = logging.getLogger(__name__)


def calculate_rms(pcm_data: bytes) -> float:
    """Calculate the Root Mean Square (RMS) energy of 16-bit signed mono PCM.

    Args:
        pcm_data: Raw 16-bit signed little-endian PCM bytes.

    Returns:
        float: RMS energy value (0.0 to 32767.0).
    """
    if not pcm_data or len(pcm_data) < 2:
        return 0.0

    num_samples = len(pcm_data) // 2
    samples = struct.unpack(f"<{num_samples}h", pcm_data[: num_samples * 2])
    sum_squares = sum(s * s for s in samples)
    return math.sqrt(sum_squares / num_samples)


def wav_bytes_from_pcm(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap raw PCM bytes into a standard WAV audio container.

    Args:
        pcm_data: Raw PCM audio bytes.
        sample_rate: Audio sampling rate in Hz (default 16000).
        channels: Number of audio channels (default 1).
        sample_width: Sample width in bytes (default 2 for 16-bit).

    Returns:
        bytes: Complete WAV file bytes.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


class AudioRecorder:
    """Manages audio recording via arecord with silence VAD and push-to-talk."""

    def __init__(
        self,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        silence_threshold_rms: Optional[int] = None,
        silence_duration_seconds: Optional[float] = None,
        max_recording_seconds: Optional[int] = None,
        chunk_duration_ms: int = 20,
        arecord_cmd: Optional[List[str]] = None,
    ):
        """Initialize the AudioRecorder.

        Reads defaults from config.yaml / AppConfig if not explicitly specified.
        """
        try:
            cfg = get_config().audio
        except Exception:
            cfg = None

        self.sample_rate = sample_rate or (cfg.sample_rate if cfg else 16000)
        self.channels = channels or (cfg.channels if cfg else 1)
        self.silence_threshold_rms = silence_threshold_rms or (
            cfg.silence_threshold_rms if cfg else 350
        )
        self.silence_duration_seconds = silence_duration_seconds or (
            cfg.silence_duration_seconds if cfg else 1.2
        )
        self.max_recording_seconds = max_recording_seconds or (
            cfg.max_recording_seconds if cfg else 30
        )
        self.chunk_duration_ms = chunk_duration_ms
        self.arecord_cmd = arecord_cmd

        # 20ms chunk size in bytes for 16-bit mono PCM:
        # (sample_rate * 0.02) * channels * 2 bytes/sample
        self.chunk_samples = int(self.sample_rate * (self.chunk_duration_ms / 1000.0))
        self.chunk_bytes = self.chunk_samples * self.channels * 2

        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_recording = False
        self._lock = threading.Lock()
        self._last_wav_bytes: bytes = b""

    @property
    def is_recording(self) -> bool:
        """Check if recording is currently active."""
        return self._is_recording

    @property
    def last_wav_bytes(self) -> bytes:
        """Return the most recently recorded WAV audio bytes."""
        return self._last_wav_bytes

    def _build_command(self) -> List[str]:
        """Build arecord command line."""
        if self.arecord_cmd:
            return self.arecord_cmd
        return [
            "arecord",
            "-q",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-f",
            "S16_LE",
            "-t",
            "raw",
        ]

    def _record_loop(
        self,
        stream_in: IO[bytes],
        use_vad: bool,
        max_duration: float,
    ) -> bytes:
        """Internal recording loop reading PCM chunks and running VAD."""
        pcm_buffer = bytearray()
        speech_started = False
        consecutive_silent_chunks = 0
        silence_chunks_needed = max(
            1,
            int(round(self.silence_duration_seconds / (self.chunk_duration_ms / 1000.0)))
        )
        start_time = time.monotonic()
        first_chunk = True

        while not self._stop_event.is_set():
            # Check maximum duration timeout
            elapsed = time.monotonic() - start_time
            if elapsed >= max_duration:
                logger.debug("Max recording duration reached (%.1fs)", elapsed)
                break

            chunk = stream_in.read(self.chunk_bytes)
            if not chunk:
                # End of stream / process closed
                break

            # Handle possible WAV header if arecord was run without -t raw
            if first_chunk:
                first_chunk = False
                if chunk.startswith(b"RIFF") and len(chunk) >= 44:
                    chunk = chunk[44:]

            if not chunk:
                continue

            pcm_buffer.extend(chunk)

            # Silence VAD logic
            if use_vad:
                rms = calculate_rms(chunk)
                if rms >= self.silence_threshold_rms:
                    speech_started = True
                    consecutive_silent_chunks = 0
                else:
                    if speech_started:
                        consecutive_silent_chunks += 1
                        if consecutive_silent_chunks >= silence_chunks_needed:
                            logger.debug(
                                "Silence detected (%d chunks, %.2fs) after speech. Stopping recording.",
                                consecutive_silent_chunks,
                                self.silence_duration_seconds,
                            )
                            break

        return wav_bytes_from_pcm(
            bytes(pcm_buffer),
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=2,
        )

    def record(
        self,
        max_duration: Optional[float] = None,
        use_vad: bool = True,
    ) -> bytes:
        """Record audio synchronously until silence is detected or max duration is reached.

        Args:
            max_duration: Maximum recording time in seconds (default from config).
            use_vad: Whether to automatically stop after speech stops (default True).

        Returns:
            bytes: Recorded audio in standard WAV format.
        """
        duration_limit = max_duration or self.max_recording_seconds
        self._stop_event.clear()
        self._is_recording = True

        cmd = self._build_command()
        logger.debug("Starting arecord: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except Exception as e:
            self._is_recording = False
            logger.error("Failed to start arecord process: %s", e)
            raise RuntimeError(f"Could not start arecord: {e}") from e

        try:
            if self._process.stdout is None:
                raise RuntimeError("arecord stdout was not opened")
            wav_bytes = self._record_loop(
                self._process.stdout,
                use_vad=use_vad,
                max_duration=duration_limit,
            )
        finally:
            self._terminate_process()
            self._is_recording = False

        self._last_wav_bytes = wav_bytes
        return wav_bytes

    def start(self, use_vad: bool = False) -> None:
        """Start asynchronous recording in a background thread (for push-to-talk).

        Args:
            use_vad: Whether to terminate on silence even during background recording.
        """
        with self._lock:
            if self._is_recording:
                logger.warning("Recorder is already recording.")
                return

            self._stop_event.clear()
            self._is_recording = True

            cmd = self._build_command()
            logger.debug("Starting background arecord: %s", " ".join(cmd))
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
            except Exception as e:
                self._is_recording = False
                logger.error("Failed to start arecord process: %s", e)
                raise RuntimeError(f"Could not start arecord: {e}") from e

            def _thread_target():
                try:
                    if self._process and self._process.stdout:
                        self._last_wav_bytes = self._record_loop(
                            self._process.stdout,
                            use_vad=use_vad,
                            max_duration=self.max_recording_seconds,
                        )
                finally:
                    self._terminate_process()
                    self._is_recording = False

            self._thread = threading.Thread(
                target=_thread_target,
                name="AudioRecorderThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> bytes:
        """Stop active recording (push-to-talk release) and return WAV bytes.

        Returns:
            bytes: Recorded audio in standard WAV format.
        """
        with self._lock:
            self._stop_event.set()
            self._terminate_process()

            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
                self._thread = None

            self._is_recording = False
            return self._last_wav_bytes

    def _terminate_process(self) -> None:
        """Safely terminate the arecord subprocess."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=0.5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            finally:
                self._process = None

    def save_to_file(
        self,
        path: Union[str, Path],
        wav_bytes: Optional[bytes] = None,
    ) -> Path:
        """Save WAV bytes to a designated file path.

        Args:
            path: Destination file path.
            wav_bytes: Audio bytes to write (defaults to self.last_wav_bytes).

        Returns:
            Path: The saved file path.
        """
        data = wav_bytes if wav_bytes is not None else self._last_wav_bytes
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def save_to_temp_file(self, wav_bytes: Optional[bytes] = None) -> Path:
        """Save WAV bytes to a temporary file.

        Args:
            wav_bytes: Audio bytes to write (defaults to self.last_wav_bytes).

        Returns:
            Path: Path to the newly created temporary .wav file.
        """
        data = wav_bytes if wav_bytes is not None else self._last_wav_bytes
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(data)
            return Path(tf.name)
