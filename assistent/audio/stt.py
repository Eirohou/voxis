"""Speech-to-Text (STT) implementation using the Groq Whisper API.

Features:
- Uses Groq's high-speed Whisper Large v3 endpoint.
- Captures spoken text and detected language via verbose_json format.
- Normalizes language codes ('en', 'pl', 'de', etc.).
- Provides both synchronous and asynchronous transcription methods.
- Graceful handling of missing API keys, network issues, and HTTP errors.
"""

from dataclasses import dataclass
import io
import logging
import os
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union
import httpx

from assistent.config import get_config

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"

# Common language names to 2-letter ISO 639-1 mapping
LANGUAGE_MAP: Dict[str, str] = {
    "english": "en",
    "polish": "pl",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "ukrainian": "uk",
    "russian": "ru",
    "portuguese": "pt",
    "dutch": "nl",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "czech": "cs",
    "slovak": "sk",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
}


class STTError(Exception):
    """Raised when Speech-to-Text transcription fails."""

    pass


@dataclass
class STTResult:
    """Result of speech-to-text transcription."""

    text: str
    language: Optional[str] = None
    duration: Optional[float] = None
    segments: Optional[List[Dict[str, Any]]] = None
    raw_response: Optional[Dict[str, Any]] = None


class GroqSTT:
    """Groq Whisper STT client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        endpoint: str = GROQ_TRANSCRIPTION_ENDPOINT,
        default_language: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """Initialize GroqSTT.

        Args:
            api_key: Groq API key (defaults to config / GROQ_API_KEY env var).
            model: Whisper model name (default "whisper-large-v3").
            endpoint: API endpoint URL.
            default_language: Optional language hint (e.g. "en", "pl", "de").
            timeout: HTTP request timeout in seconds.
        """
        try:
            cfg = get_config().stt
        except Exception:
            cfg = None

        self.api_key = api_key or (cfg.api_key if cfg else None) or os.getenv("GROQ_API_KEY")
        self.model = model or (cfg.model if cfg else None) or "whisper-large-v3"
        self.endpoint = endpoint
        self.default_language = default_language or (cfg.language if cfg else None)
        self.timeout = timeout

    def _normalize_language(self, lang: Optional[str]) -> Optional[str]:
        """Normalize language name or code to lowercase 2-letter code."""
        if not lang:
            return None
        cleaned = str(lang).strip().lower()
        if cleaned in LANGUAGE_MAP:
            return LANGUAGE_MAP[cleaned]
        # Already a 2-character code (e.g. 'en', 'pl')
        if len(cleaned) == 2:
            return cleaned
        return cleaned

    def _prepare_audio_bytes(self, audio: Union[bytes, str, Path, BinaryIO]) -> bytes:
        """Convert various audio inputs into raw bytes."""
        if isinstance(audio, bytes):
            return audio
        elif isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.exists():
                raise FileNotFoundError(f"Audio file not found: {path}")
            return path.read_bytes()
        elif hasattr(audio, "read"):
            return audio.read()
        else:
            raise TypeError(f"Unsupported audio input type: {type(audio)}")

    def _validate_api_key(self) -> str:
        """Validate presence of the API key."""
        key = self.api_key or os.getenv("GROQ_API_KEY")
        if not key or not key.strip():
            raise ValueError(
                "Groq API key not found. Please set the GROQ_API_KEY environment "
                "variable or pass api_key to GroqSTT."
            )
        return key.strip()

    def transcribe(
        self,
        audio: Union[bytes, str, Path, BinaryIO],
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> STTResult:
        """Transcribe audio synchronously via Groq Whisper API.

        Args:
            audio: Audio data as bytes, file path, or file-like object.
            language: Optional language hint (e.g. "en", "pl", "de").
            prompt: Optional transcription guide prompt.

        Returns:
            STTResult: Result containing transcribed text and detected language.
        """
        api_key = self._validate_api_key()
        audio_bytes = self._prepare_audio_bytes(audio)

        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        data = {
            "model": self.model,
            "response_format": "verbose_json",
        }
        target_lang = language or self.default_language
        if target_lang:
            data["language"] = target_lang
        if prompt:
            data["prompt"] = prompt

        files = {
            "file": ("audio.wav", audio_bytes, "audio/wav"),
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint,
                    headers=headers,
                    data=data,
                    files=files,
                )
        except httpx.RequestError as e:
            logger.error("Groq STT network error: %s", e)
            raise STTError(f"Network error connecting to Groq STT: {e}") from e

        if response.status_code != 200:
            msg = f"Groq STT request failed ({response.status_code}): {response.text}"
            logger.error(msg)
            raise STTError(msg)

        try:
            res_data = response.json()
        except Exception as e:
            raise STTError(f"Invalid JSON returned by Groq STT: {e}") from e

        text = res_data.get("text", "").strip()
        detected_lang = self._normalize_language(res_data.get("language"))
        duration = res_data.get("duration")
        segments = res_data.get("segments")

        return STTResult(
            text=text,
            language=detected_lang,
            duration=duration,
            segments=segments,
            raw_response=res_data,
        )

    async def transcribe_async(
        self,
        audio: Union[bytes, str, Path, BinaryIO],
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> STTResult:
        """Transcribe audio asynchronously via Groq Whisper API.

        Args:
            audio: Audio data as bytes, file path, or file-like object.
            language: Optional language hint (e.g. "en", "pl", "de").
            prompt: Optional transcription guide prompt.

        Returns:
            STTResult: Result containing transcribed text and detected language.
        """
        api_key = self._validate_api_key()
        audio_bytes = self._prepare_audio_bytes(audio)

        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        data = {
            "model": self.model,
            "response_format": "verbose_json",
        }
        target_lang = language or self.default_language
        if target_lang:
            data["language"] = target_lang
        if prompt:
            data["prompt"] = prompt

        files = {
            "file": ("audio.wav", audio_bytes, "audio/wav"),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    data=data,
                    files=files,
                )
        except httpx.RequestError as e:
            logger.error("Groq STT network error: %s", e)
            raise STTError(f"Network error connecting to Groq STT: {e}") from e

        if response.status_code != 200:
            msg = f"Groq STT request failed ({response.status_code}): {response.text}"
            logger.error(msg)
            raise STTError(msg)

        try:
            res_data = response.json()
        except Exception as e:
            raise STTError(f"Invalid JSON returned by Groq STT: {e}") from e

        text = res_data.get("text", "").strip()
        detected_lang = self._normalize_language(res_data.get("language"))
        duration = res_data.get("duration")
        segments = res_data.get("segments")

        return STTResult(
            text=text,
            language=detected_lang,
            duration=duration,
            segments=segments,
            raw_response=res_data,
        )
