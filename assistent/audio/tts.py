"""Text-to-Speech (TTS) module with Microsoft Edge TTS and espeak-ng fallback.

Features:
- Primary: Microsoft Edge TTS via WebSocket protocol.
- Multi-language voice routing:
    - 'en' -> en-US-ChristopherNeural
    - 'pl' -> pl-PL-MarekNeural
    - 'de' -> de-DE-ConradNeural
- Plays synthesized audio via pw-play, aplay, or ffmpeg.
- Fallback: EspeakFallbackTTS using local espeak-ng when offline or on failure.
"""

import asyncio
import concurrent.futures
import datetime
import inspect
import io
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Dict, List, Optional, Tuple, Union
import uuid
import xml.sax.saxutils
import websockets

from assistent.config import get_config

logger = logging.getLogger(__name__)

EDGE_WSS_URL = (
    "wss://speech.platform.bing.com/consumer/speech/synthesize/readahead/edge/v1"
)
TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
CHROME_EXTENSION_ORIGIN = (
    "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like"
    " Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)

DEFAULT_VOICE_MAPPING: Dict[str, str] = {
    "en": "en-US-ChristopherNeural",
    "pl": "pl-PL-MarekNeural",
    "de": "de-DE-ConradNeural",
}
DEFAULT_VOICE = "en-US-ChristopherNeural"

ESPEAK_VOICE_MAPPING: Dict[str, str] = {
    "en": "en-us",
    "pl": "pl",
    "de": "de",
}
ESPEAK_DEFAULT_VOICE = "en-us"


def convert_audio_to_wav(audio_data: bytes) -> bytes:
    """Ensure audio is standard WAV PCM format using ffmpeg if needed."""
    if not audio_data:
        return b""
    if audio_data.startswith(b"RIFF"):
        return audio_data

    # Try ffmpeg conversion from MP3/other to WAV
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        try:
            proc = subprocess.Popen(
                [ffmpeg_bin, "-v", "error", "-i", "pipe:0", "-f", "wav", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            wav_bytes, _ = proc.communicate(input=audio_data)
            if wav_bytes and wav_bytes.startswith(b"RIFF"):
                return wav_bytes
        except Exception as e:
            logger.debug("ffmpeg audio conversion failed: %s", e)

    return audio_data


def play_audio(
    audio_data: bytes,
    non_blocking: bool = False,
) -> Optional[Union[threading.Thread, subprocess.Popen]]:
    """Play audio bytes using pw-play, aplay, or ffplay/ffmpeg.

    Args:
        audio_data: Raw audio bytes (WAV or MP3).
        non_blocking: Whether to play asynchronously in background thread.

    Returns:
        Thread if non_blocking=True and started, else None.
    """
    if not audio_data:
        return None

    wav_data = convert_audio_to_wav(audio_data)

    player_cmd: Optional[List[str]] = None
    pw_play = shutil.which("pw-play")
    aplay = shutil.which("aplay")
    ffplay = shutil.which("ffplay")

    if pw_play:
        player_cmd = [pw_play, "-"]
    elif aplay:
        player_cmd = [aplay, "-q", "-"]
    elif ffplay:
        player_cmd = [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-"]

    if not player_cmd:
        logger.warning("No audio player found to play synthesized speech.")
        return None

    def _play_worker() -> None:
        try:
            proc = subprocess.Popen(
                player_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=wav_data)
        except Exception as e:
            logger.debug("Playback error with %s: %s", player_cmd[0], e)

    if non_blocking:
        thread = threading.Thread(
            target=_play_worker,
            name="TTSPlayerThread",
            daemon=True,
        )
        thread.start()
        return thread
    else:
        _play_worker()
        return None


class EspeakFallbackTTS:
    """Offline Text-to-Speech fallback using espeak-ng."""

    def __init__(
        self,
        voices: Optional[Dict[str, str]] = None,
        default_voice: str = ESPEAK_DEFAULT_VOICE,
    ):
        self.voices = voices or dict(ESPEAK_VOICE_MAPPING)
        self.default_voice = default_voice
        self.espeak_bin = shutil.which("espeak-ng") or shutil.which("espeak")

    def get_voice(self, language: Optional[str] = None) -> str:
        """Route language code to appropriate espeak voice."""
        if not language:
            return self.default_voice
        lang_code = language.strip().lower()
        if lang_code in self.voices:
            return self.voices[lang_code]
        # Check first 2 characters
        prefix = lang_code[:2]
        return self.voices.get(prefix, self.default_voice)

    def synthesize(self, text: str, language: Optional[str] = None) -> bytes:
        """Synthesize text to WAV bytes via espeak-ng --stdout."""
        if not self.espeak_bin:
            raise RuntimeError("espeak-ng executable not found on system.")

        voice = self.get_voice(language)
        cmd = [self.espeak_bin, "-v", voice, "--stdout", text]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = proc.communicate()
        except Exception as e:
            raise RuntimeError(f"Failed to execute {self.espeak_bin}: {e}") from e

        if proc.returncode != 0:
            err_msg = err.decode("utf-8", errors="replace")
            raise RuntimeError(f"espeak-ng failed (code {proc.returncode}): {err_msg}")

        return out

    def speak(
        self,
        text: str,
        language: Optional[str] = None,
        non_blocking: bool = False,
    ) -> Optional[Union[threading.Thread, subprocess.Popen]]:
        """Synthesize and speak text via espeak-ng."""
        wav_bytes = self.synthesize(text, language=language)
        return play_audio(wav_bytes, non_blocking=non_blocking)


class EdgeTTS:
    """Microsoft Edge Neural Text-to-Speech client with espeak-ng fallback."""

    def __init__(
        self,
        voices: Optional[Dict[str, str]] = None,
        default_voice: Optional[str] = None,
        audio_format: str = "audio-24khz-48kbitrate-mono-mp3",
        connect_timeout: float = 8.0,
        receive_timeout: float = 15.0,
        fallback_tts: Optional[EspeakFallbackTTS] = None,
        fallback_enabled: bool = True,
    ):
        """Initialize EdgeTTS.

        Loads default voice configuration from config.yaml if available.
        """
        try:
            cfg = get_config().tts
        except Exception:
            cfg = None

        self.voices = voices or (cfg.voices if cfg else None) or dict(DEFAULT_VOICE_MAPPING)
        self.default_voice = (
            default_voice or (cfg.default_voice if cfg else None) or DEFAULT_VOICE
        )
        self.audio_format = audio_format
        self.connect_timeout = connect_timeout
        self.receive_timeout = receive_timeout
        self.fallback_enabled = fallback_enabled
        self.fallback_tts = fallback_tts or EspeakFallbackTTS()

    def get_voice(self, language: Optional[str] = None) -> str:
        """Resolve voice name from language code ('en', 'pl', 'de')."""
        if not language:
            return self.default_voice
        code = language.strip().lower()
        if code in self.voices:
            return self.voices[code]
        # Check first 2 characters
        prefix = code[:2]
        return self.voices.get(prefix, self.default_voice)

    def _get_lang_tag(self, voice: str) -> str:
        """Extract language tag (e.g. 'en-US', 'pl-PL', 'de-DE') from voice name."""
        parts = voice.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        return "en-US"

    def _make_config_message(self) -> str:
        """Build initial speech.config message."""
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"
        )
        return (
            f"X-Timestamp:{now_str}\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n\r\n"
            f'{{"context":{{"synthesis":{{"audio":{{"metadataoptions":{{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"}},"outputFormat":"{self.audio_format}"}}}}}}}}\r\n'
        )

    def _make_ssml_message(self, text: str, voice: str) -> str:
        """Build SSML synthesis message."""
        request_id = uuid.uuid4().hex
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"
        )
        lang_tag = self._get_lang_tag(voice)
        escaped_text = xml.sax.saxutils.escape(text)

        ssml = (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xml:lang='{lang_tag}'>"
            f"<voice name='{voice}'>"
            f"{escaped_text}"
            f"</voice></speak>"
        )

        return (
            f"X-RequestId:{request_id}\r\n"
            "Content-Type:application/ssml+xml\r\n"
            f"X-Timestamp:{now_str}\r\n"
            "Path:ssml\r\n\r\n"
            f"{ssml}\r\n"
        )

    async def _synthesize_edge(self, text: str, voice: str) -> bytes:
        """Connect to Microsoft Edge TTS WebSocket and stream audio bytes."""
        conn_id = uuid.uuid4().hex
        url = (
            f"{EDGE_WSS_URL}?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"
            f"&ConnectionId={conn_id}"
        )

        headers = {
            "Origin": CHROME_EXTENSION_ORIGIN,
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }

        # Inspect websockets.connect parameter compatibility
        connect_kwargs = {}
        sig = inspect.signature(websockets.connect)
        if "additional_headers" in sig.parameters:
            connect_kwargs["additional_headers"] = headers
            if "user_agent_header" in sig.parameters:
                connect_kwargs["user_agent_header"] = DEFAULT_USER_AGENT
        elif "extra_headers" in sig.parameters:
            h = dict(headers)
            h["User-Agent"] = DEFAULT_USER_AGENT
            connect_kwargs["extra_headers"] = h

        audio_buffer = bytearray()

        async with asyncio.timeout(self.connect_timeout + self.receive_timeout):
            async with websockets.connect(url, **connect_kwargs) as ws:
                # 1. Send speech.config
                await ws.send(self._make_config_message())

                # 2. Send SSML request
                await ws.send(self._make_ssml_message(text, voice))

                # 3. Receive audio stream
                async for message in ws:
                    if isinstance(message, str):
                        if "Path:turn.end" in message:
                            break
                    elif isinstance(message, (bytes, bytearray)):
                        if len(message) > 2:
                            header_len = int.from_bytes(message[:2], "big")
                            header = message[2 : 2 + header_len]
                            if b"Path:audio" in header:
                                audio_chunk = message[2 + header_len :]
                                audio_buffer.extend(audio_chunk)

        if not audio_buffer:
            raise RuntimeError("Edge TTS returned no audio data.")

        return bytes(audio_buffer)

    async def synthesize_async(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> bytes:
        """Synthesize text asynchronously, with fallback on failure."""
        chosen_voice = voice or self.get_voice(language)
        try:
            return await self._synthesize_edge(text, chosen_voice)
        except Exception as e:
            if self.fallback_enabled and self.fallback_tts:
                logger.warning(
                    "Edge TTS failed (%s). Falling back to espeak-ng.",
                    e,
                )
                return self.fallback_tts.synthesize(text, language=language)
            raise

    def synthesize(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> bytes:
        """Synthesize text synchronously with fallback on failure."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an event loop (e.g. Jupyter or async runner)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    self.synthesize_async(text, language=language, voice=voice),
                )
                return future.result()
        else:
            return asyncio.run(
                self.synthesize_async(text, language=language, voice=voice)
            )

    def speak(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
        non_blocking: bool = False,
    ) -> Optional[Union[threading.Thread, subprocess.Popen]]:
        """Synthesize speech and play it through audio output."""
        audio_data = self.synthesize(text, language=language, voice=voice)
        return play_audio(audio_data, non_blocking=non_blocking)
