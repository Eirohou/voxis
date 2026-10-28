"""Assistent skills package exposing all registered tools and registries."""

from assistent.skills.base import Tool, ToolRegistry, default_registry, tool
from assistent.skills.notes import save_note, search_notes, read_note, list_notes
from assistent.skills.app_launcher import launch_app, list_apps
from assistent.skills.media import media_control
from assistent.skills.volume import volume_control
from assistent.skills.clipboard import read_clipboard, write_clipboard
from assistent.skills.timer import set_timer

__all__ = [
    "tool",
    "Tool",
    "ToolRegistry",
    "default_registry",
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
]
