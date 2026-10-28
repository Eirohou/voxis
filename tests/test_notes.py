"""Unit tests for the notes skill."""

from datetime import datetime
from pathlib import Path
import pytest

from assistent.config import get_config
from assistent.skills.notes import list_notes, read_note, save_note, search_notes


@pytest.fixture(autouse=True)
def setup_notes_dir(tmp_path, monkeypatch):
    """Point assistant.notes_dir to isolated temporary directory."""
    test_notes_dir = tmp_path / "test_notes"
    monkeypatch.setattr(get_config().assistant, "notes_dir", str(test_notes_dir))
    return test_notes_dir


def test_save_and_append_topic_note(tmp_path):
    # Create new topic note
    res1 = save_note("todo", "- Buy milk")
    assert "todo.md" in res1
    assert "Saved note" in res1

    note_path = Path(get_config().assistant.notes_dir) / "todo.md"
    assert note_path.exists()
    assert note_path.read_text(encoding="utf-8") == "- Buy milk\n"

    # Append to existing topic note
    res2 = save_note("todo", "- Walk the dog")
    assert "todo.md" in res2
    assert "Appended note" in res2

    content = note_path.read_text(encoding="utf-8")
    assert content == "- Buy milk\n- Walk the dog\n"


def test_save_daily_and_quick_notes():
    today_str = datetime.now().strftime("%Y-%m-%d")
    note_path = Path(get_config().assistant.notes_dir) / f"{today_str}.md"

    # Empty topic defaults to daily note with timestamp
    res1 = save_note("", "Quick thought")
    assert today_str in res1
    assert note_path.exists()

    content1 = note_path.read_text(encoding="utf-8")
    assert "Quick thought" in content1
    assert content1.startswith("[")

    # "quick" topic also routes to daily note
    res2 = save_note("quick", "Second thought")
    assert today_str in res2

    # "daily" topic also routes to daily note
    res3 = save_note("daily", "Third thought")
    assert today_str in res3

    final_content = note_path.read_text(encoding="utf-8")
    lines = final_content.strip().splitlines()
    assert len(lines) == 3
    assert "Quick thought" in lines[0]
    assert "Second thought" in lines[1]
    assert "Third thought" in lines[2]


def test_read_note():
    save_note("shopping", "Apples\nBananas")

    # Read without extension
    res1 = read_note("shopping")
    assert res1 == "Apples\nBananas\n"

    # Read with extension
    res2 = read_note("shopping.md")
    assert res2 == "Apples\nBananas\n"

    # Read today / daily
    save_note("daily", "Check mail")
    res_today = read_note("today")
    assert "Check mail" in res_today

    res_daily = read_note("daily")
    assert "Check mail" in res_daily

    # Non-existent note
    res_missing = read_note("non_existent")
    assert "not found" in res_missing.lower()


def test_search_notes():
    save_note("recipes", "Pasta with tomato sauce\nPizza with cheese")
    save_note("groceries", "Tomato paste\nCheese slices")

    # Search query present in both files
    results = search_notes("cheese")
    assert "recipes.md" in results
    assert "groceries.md" in results
    assert "Pizza with cheese" in results
    assert "Cheese slices" in results

    # Search query present in one file
    single_res = search_notes("pasta")
    assert "recipes.md" in single_res
    assert "groceries.md" not in single_res

    # Search with no match
    no_res = search_notes("pineapple")
    assert "no matches found" in no_res.lower()

    # Empty query
    empty_res = search_notes("")
    assert "cannot be empty" in empty_res.lower()


def test_list_notes():
    # Empty directory
    assert "no notes found" in list_notes().lower()

    # Create multiple notes
    save_note("alpha", "Content 1")
    save_note("beta", "Content 2")

    listing = list_notes()
    assert "alpha.md" in listing
    assert "beta.md" in listing
    assert "Notes (2):" in listing


def test_path_traversal_protection():
    save_note("../../secret", "Trapped")
    notes_dir = Path(get_config().assistant.notes_dir)
    assert (notes_dir / "secret.md").exists()
    assert not Path(notes_dir.parent / "secret.md").exists()
