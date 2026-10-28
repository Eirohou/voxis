"""Notes skill for saving, searching, reading, and listing notes."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from assistent.config import get_config
from assistent.skills.base import tool


def _get_notes_dir() -> Path:
    """Retrieve and ensure the notes directory exists."""
    notes_dir = Path(get_config().assistant.notes_dir).expanduser()
    notes_dir.mkdir(parents=True, exist_ok=True)
    return notes_dir


@tool
def save_note(type_or_topic: str, content: str) -> str:
    """Save or append a note to a topic file or daily log."""
    notes_dir = _get_notes_dir()
    clean_topic = (type_or_topic or "").strip().lower()

    # If empty, 'quick', 'daily', or 'general', append to daily note
    is_daily = not clean_topic or clean_topic in ("quick", "daily", "general", "today")

    if is_daily:
        now = datetime.now()
        filename = f"{now.strftime('%Y-%m-%d')}.md"
        entry = f"[{now.strftime('%H:%M')}] {content.strip()}"
    else:
        # Sanitize topic to avoid path traversal
        clean_name = Path(type_or_topic.strip()).name
        if clean_name.endswith(".md"):
            clean_name = clean_name[:-3]
        filename = f"{clean_name}.md"
        entry = content.strip()

    file_path = notes_dir / filename
    if file_path.exists() and file_path.stat().st_size > 0:
        existing = file_path.read_text(encoding="utf-8")
        separator = "\n" if not existing.endswith("\n") else ""
        file_path.write_text(existing + separator + entry + "\n", encoding="utf-8")
        return f"Appended note to {filename}."
    else:
        file_path.write_text(entry + "\n", encoding="utf-8")
        return f"Saved note to {filename}."


@tool
def search_notes(query: str) -> str:
    """Search for matching lines and file names across all markdown notes."""
    notes_dir = _get_notes_dir()
    query_str = (query or "").strip()
    if not query_str:
        return "Query cannot be empty."

    md_files = sorted(notes_dir.glob("*.md"))
    if not md_files:
        return "No notes found to search."

    results = []
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            for line_no, line in enumerate(lines, start=1):
                if query_str.lower() in line.lower():
                    results.append(f"{md_file.name}:{line_no}: {line.strip()}")
        except Exception:
            continue

    if not results:
        return f"No matches found for '{query_str}'."
    return "\n".join(results)


@tool
def read_note(topic: str) -> str:
    """Read the contents of a note by topic name or date (YYYY-MM-DD)."""
    notes_dir = _get_notes_dir()
    clean = (topic or "").strip()
    if not clean:
        return "Topic or date must be specified."

    if clean.lower() in ("today", "daily"):
        clean = datetime.now().strftime("%Y-%m-%d")

    target_name = Path(clean).name
    if not target_name.endswith(".md"):
        target_name = f"{target_name}.md"

    file_path = notes_dir / target_name
    if not file_path.is_file():
        return f"Note '{topic}' not found."

    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            return f"Note '{target_name}' is empty."
        return content
    except Exception as e:
        return f"Error reading note '{target_name}': {e}"


@tool
def list_notes() -> str:
    """List all markdown notes in the notes directory."""
    notes_dir = _get_notes_dir()
    md_files = sorted(notes_dir.glob("*.md"))
    if not md_files:
        return "No notes found."

    lines = [f"- {f.name}" for f in md_files]
    return f"Notes ({len(md_files)}):\n" + "\n".join(lines)
