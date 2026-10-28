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


def save_api_key(key: str, env_path: Optional[str | Path] = None) -> Path:
    """Save GROQ_API_KEY to .env file and update environment and global configuration."""
    clean_key = key.strip().strip("'\"")
    path = Path(env_path or ".env")

    lines = []
    found = False
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("GROQ_API_KEY=") or stripped.startswith("export GROQ_API_KEY="):
                    lines.append(f"GROQ_API_KEY={clean_key}\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"GROQ_API_KEY={clean_key}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    os.environ["GROQ_API_KEY"] = clean_key

    # Reload global configuration instance
    global _config_instance
    _config_instance = AppConfig.load()

    return path


def ensure_api_key_interactive(console: Optional[Any] = None) -> Optional[str]:
    """Check if GROQ_API_KEY is configured. If missing and interactive, prompt the user."""
    import sys

    config = get_config()
    current_key = config.llm.api_key or os.getenv("GROQ_API_KEY")

    # If key is already configured and not placeholder, return it
    if current_key and current_key.strip() != "your_groq_api_key_here":
        return current_key.strip()

    # Don't block if not running in an interactive terminal
    if not sys.stdin.isatty():
        return None

    try:
        from rich.panel import Panel
        from rich.text import Text
        from assistent.ui.console import console as default_console

        out = console or default_console

        content = Text()
        content.append("No Groq API key found.\n\n", style="bold yellow")
        content.append(
            "Groq provides a 100% free tier for Whisper STT and Llama 3.3 70B with sub-second speed.\n",
            style="dim",
        )
        content.append("Get your free key in 30 seconds at: ", style="white")
        content.append("https://console.groq.com/keys\n\n", style="bold cyan underline")
        content.append("Paste your key below (or press Enter to skip):", style="bold green")

        out.print(
            Panel(
                content,
                title="🔑 First-Time Setup: Groq API Key",
                border_style="yellow",
                expand=False,
            )
        )

        user_input = out.input("[bold cyan]Enter GROQ_API_KEY > [/]").strip()
        if user_input and user_input != "your_groq_api_key_here":
            save_api_key(user_input)
            out.print("[bold green]✓ API key successfully saved to .env![/]\n")
            return user_input

        out.print("[dim]Continuing without API key (cloud STT/LLM will be disabled until set)...\n[/]")
        return None
    except (KeyboardInterrupt, EOFError):
        return None

