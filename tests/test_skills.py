"""Unit tests for media, volume, clipboard, and timer skills."""

import subprocess
import threading
from unittest.mock import MagicMock, patch
import pytest

from assistent.skills import (
    default_registry,
    media_control,
    volume_control,
    read_clipboard,
    write_clipboard,
    set_timer,
)
from assistent.skills.timer import trigger_alarm, _timer_worker


# --- Media Control Tests ---

def test_media_control_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["playerctl", "play"], returncode=0, stdout="", stderr=""
        )

        res = media_control("play")
        assert "executed" in res
        mock_run.assert_called_once_with(
            ["playerctl", "play"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_media_control_action_aliases():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["playerctl", "play-pause"], returncode=0, stdout="", stderr=""
        )

        media_control("toggle")
        mock_run.assert_called_with(
            ["playerctl", "play-pause"],
            capture_output=True,
            text=True,
            check=False,
        )

        media_control("prev")
        mock_run.assert_called_with(
            ["playerctl", "previous"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_media_control_no_player():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["playerctl", "pause"],
            returncode=1,
            stdout="",
            stderr="No players found",
        )

        res = media_control("pause")
        assert "no active media player found" in res.lower()


def test_media_control_invalid_action():
    with patch("subprocess.run") as mock_run:
        res = media_control("dance")
        assert "unsupported media action" in res.lower()
        mock_run.assert_not_called()


def test_media_control_silent_feedback():
    tool_obj = default_registry.get_tool("media_control")
    assert tool_obj is not None
    assert tool_obj.silent_feedback is True


# --- Volume Control Tests ---

def test_volume_control_adjust():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wpctl"], returncode=0, stdout="", stderr=""
        )

        # Standard relative volume change
        res1 = volume_control("5%+")
        assert "Volume set to 5%+" in res1
        mock_run.assert_called_with(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"],
            capture_output=True,
            text=True,
            check=False,
        )

        # Normalized +/- signs
        volume_control("+10%")
        mock_run.assert_called_with(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"],
            capture_output=True,
            text=True,
            check=False,
        )

        volume_control("-5%")
        mock_run.assert_called_with(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
            capture_output=True,
            text=True,
            check=False,
        )

        # Up / Down aliases
        volume_control("up")
        mock_run.assert_called_with(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"],
            capture_output=True,
            text=True,
            check=False,
        )

        volume_control("down")
        mock_run.assert_called_with(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_volume_control_mute_toggle():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wpctl"], returncode=0, stdout="", stderr=""
        )

        res = volume_control("mute")
        assert "mute toggled" in res.lower()
        mock_run.assert_called_with(
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            capture_output=True,
            text=True,
            check=False,
        )

        res2 = volume_control("toggle")
        assert "mute toggled" in res2.lower()


def test_volume_control_error():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wpctl"], returncode=1, stdout="", stderr="Device not found"
        )
        res = volume_control("5%+")
        assert "volume control failed" in res.lower()
        assert "Device not found" in res


def test_volume_control_silent_feedback():
    tool_obj = default_registry.get_tool("volume_control")
    assert tool_obj is not None
    assert tool_obj.silent_feedback is True


# --- Clipboard Tests ---

def test_read_clipboard_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wl-paste"], returncode=0, stdout="clipboard content", stderr=""
        )
        res = read_clipboard()
        assert res == "clipboard content"
        mock_run.assert_called_once_with(
            ["wl-paste"], capture_output=True, text=True, check=False
        )


def test_read_clipboard_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wl-paste"], returncode=1, stdout="", stderr="Nothing copied"
        )
        res = read_clipboard()
        assert "failed to read clipboard" in res.lower()


def test_write_clipboard_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wl-copy"], returncode=0, stdout="", stderr=""
        )
        res = write_clipboard("test text")
        assert "Copied to clipboard" in res
        mock_run.assert_called_once_with(
            ["wl-copy"], input="test text", capture_output=True, text=True, check=False
        )


def test_write_clipboard_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["wl-copy"], returncode=1, stdout="", stderr="wl-copy failed"
        )
        res = write_clipboard("test text")
        assert "failed to write to clipboard" in res.lower()


# --- Timer Tests ---

def test_set_timer_validation_and_spawn():
    # Negative duration
    assert "cannot be negative" in set_timer(-5).lower()

    # Valid timer spawns background thread
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread_instance = MagicMock()
        mock_thread_cls.return_value = mock_thread_instance

        res = set_timer(60, "Tea")
        assert "Timer set for 60 seconds (Tea)" in res
        mock_thread_cls.assert_called_once()
        mock_thread_instance.start.assert_called_once()


def test_timer_trigger_alarm():
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/bin/canberra-gtk-play"):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        trigger_alarm("Pasta")

        # notify-send and audio playback executed
        calls = mock_run.call_args_list
        assert any(call[0][0][:2] == ["notify-send", "Timer Expired"] for call in calls)
        assert any(call[0][0][:2] == ["canberra-gtk-play", "-i"] for call in calls)


def test_timer_worker_sleep_and_trigger():
    with patch("time.sleep") as mock_sleep, \
         patch("assistent.skills.timer.trigger_alarm") as mock_alarm:
        _timer_worker(10, "Break")
        mock_sleep.assert_called_once_with(10)
        mock_alarm.assert_called_once_with("Break")


# --- Registry Tests ---

def test_registry_contains_all_tools():
    expected_tools = {
        "save_note",
        "search_notes",
        "read_note",
        "list_notes",
        "launch_app",
        "list_apps",
        "media_control",
        "volume_control",
        "read_clipboard",
        "write_clipboard",
        "set_timer",
    }
    registered = set(default_registry.tools.keys())
    assert expected_tools.issubset(registered)

    # Verify each tool has an executable callable and valid schema
    for tool_name in expected_tools:
        tool_item = default_registry.get_tool(tool_name)
        assert tool_item is not None
        assert callable(tool_item.func)
        schema = tool_item.schema
        assert schema["type"] == "function"
        assert schema["function"]["name"] == tool_name
