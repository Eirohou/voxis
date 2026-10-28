"""Tests for configuration management and API key onboarding."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from assistent.config import AppConfig, ensure_api_key_interactive, get_config, save_api_key


def test_save_api_key_creates_and_updates_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"
        # Prepopulate with another variable
        env_file.write_text("CUSTOM_VAR=hello\n")

        # Save new key
        saved_path = save_api_key("  gsk_test123456  ", env_path=env_file)
        assert saved_path == env_file

        content = env_file.read_text()
        assert "CUSTOM_VAR=hello" in content
        assert "GROQ_API_KEY=gsk_test123456" in content
        assert os.environ.get("GROQ_API_KEY") == "gsk_test123456"

        # Update key
        save_api_key('"gsk_updated999"', env_path=env_file)
        updated_content = env_file.read_text()
        assert "GROQ_API_KEY=gsk_updated999" in updated_content
        assert "GROQ_API_KEY=gsk_test123456" not in updated_content
        assert os.environ.get("GROQ_API_KEY") == "gsk_updated999"


def test_ensure_api_key_returns_existing_key():
    # When key already present
    with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_existing_key"}):
        # Reset cached config
        cfg = AppConfig.load()
        with patch("assistent.config.get_config", return_value=cfg):
            key = ensure_api_key_interactive()
            assert key == "gsk_existing_key"


def test_ensure_api_key_interactive_prompt_saves_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env"

        mock_console = MagicMock()
        mock_console.input.return_value = "gsk_prompted_key"

        with patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=True):
            cfg = AppConfig.load()
            with patch("assistent.config.get_config", return_value=cfg), \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch("assistent.config.save_api_key") as mock_save:
                key = ensure_api_key_interactive(console=mock_console)
                assert key == "gsk_prompted_key"
                mock_save.assert_called_once_with("gsk_prompted_key")
