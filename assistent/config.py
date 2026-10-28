"""Configuration management for the personal voice assistant."""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env if present
load_dotenv()


class AssistantSettings(BaseModel):
    name: str = "Assistant"
    trigger_mode: str = "push_to_talk"
    notes_dir: str = "./notes"


class LLMSettings(BaseModel):
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    fallback_model: str = "llama-3.1-8b-instant"
    temperature: float = 0.2
    api_key: Optional[str] = None


class STTSettings(BaseModel):
    provider: str = "groq"
    model: str = "whisper-large-v3"
    language: Optional[str] = None
    api_key: Optional[str] = None


class TTSSettings(BaseModel):
    provider: str = "edge"
    voices: Dict[str, str] = Field(
        default_factory=lambda: {
            "en": "en-US-ChristopherNeural",
            "pl": "pl-PL-MarekNeural",
            "de": "de-DE-ConradNeural",
        }
    )
    default_voice: str = "en-US-ChristopherNeural"


class AudioSettings(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    silence_threshold_rms: int = 350
    silence_duration_seconds: float = 1.2
    max_recording_seconds: int = 30


class IPCSettings(BaseModel):
    socket_path: str = "/tmp/assistent.sock"


class AppConfig(BaseModel):
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    ipc: IPCSettings = Field(default_factory=IPCSettings)

    @classmethod
    def load(cls, config_path: Optional[str | Path] = None) -> "AppConfig":
        data: Dict[str, Any] = {}
        target_path = Path(config_path or "config.yaml")
        if target_path.exists():
            with open(target_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data = loaded

        config = cls(**data)

        # Environment variable overrides
        groq_api_key = os.getenv("GROQ_API_KEY")
        if groq_api_key:
            config.llm.api_key = groq_api_key
            config.stt.api_key = groq_api_key

        return config


# Global configuration instance
_config_instance: Optional[AppConfig] = None


def get_config(config_path: Optional[str | Path] = None) -> AppConfig:
    global _config_instance
    if _config_instance is None or config_path is not None:
        _config_instance = AppConfig.load(config_path)
    return _config_instance
