"""Unit tests for the application launcher skill."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from assistent.skills.app_launcher import (
    DesktopApp,
    clean_exec_cmd,
    find_app,
    launch_app,
    list_apps,
    parse_desktop_file,
    scan_desktop_apps,
)


@pytest.fixture
def fake_desktop_dir(tmp_path):
    """Create a temporary directory with various .desktop files for testing."""
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)

    # 1. Firefox
    (apps_dir / "firefox.desktop").write_text(
        """[Desktop Entry]
Version=1.0
Type=Application
Name=Firefox
GenericName=Web Browser
Comment=Browse the Web
Exec=/usr/lib/firefox/firefox %u
Keywords=web;browser;internet;
NoDisplay=false
""",
        encoding="utf-8",
    )

    # 2. Code OSS
    (apps_dir / "code-oss.desktop").write_text(
        """[Desktop Entry]
Type=Application
Name=Code - OSS
GenericName=Text Editor
Comment=Code Editing. Redefined.
Exec=code-oss %F
Keywords=vscode;code;editor;
""",
        encoding="utf-8",
    )

    # 3. Cosmic Terminal
    (apps_dir / "cosmic-term.desktop").write_text(
        """[Desktop Entry]
Type=Application
Name=Cosmic Terminal
GenericName=Terminal
Exec=cosmic-term
Keywords=shell;prompt;command;
""",
        encoding="utf-8",
    )

    # 4. Cosmic Files
    (apps_dir / "cosmic-files.desktop").write_text(
        """[Desktop Entry]
Type=Application
Name=Cosmic Files
GenericName=File Manager
Exec=cosmic-files %U
Keywords=files;explorer;
""",
        encoding="utf-8",
    )

    # 5. Hidden utility
    (apps_dir / "hidden-util.desktop").write_text(
        """[Desktop Entry]
Type=Application
Name=Hidden Service
Exec=hidden-service
NoDisplay=true
""",
        encoding="utf-8",
    )

    # 6. Non-application entry (should be ignored)
    (apps_dir / "folder.desktop").write_text(
        """[Desktop Entry]
Type=Directory
Name=Folder
Exec=none
""",
        encoding="utf-8",
    )

    return apps_dir


def test_parse_desktop_file(fake_desktop_dir):
    app = parse_desktop_file(fake_desktop_dir / "firefox.desktop")
    assert app is not None
    assert app.desktop_id == "firefox.desktop"
    assert app.name == "Firefox"
    assert app.generic_name == "Web Browser"
    assert app.comment == "Browse the Web"
    assert app.exec == "/usr/lib/firefox/firefox %u"
    assert "browser" in app.keywords
    assert not app.no_display

    # Non-application type returns None
    non_app = parse_desktop_file(fake_desktop_dir / "folder.desktop")
    assert non_app is None

    # Hidden app has no_display=True
    hidden = parse_desktop_file(fake_desktop_dir / "hidden-util.desktop")
    assert hidden is not None
    assert hidden.no_display is True


def test_clean_exec_cmd():
    # Strip field codes (%u, %F, %k, etc.)
    cmd1 = clean_exec_cmd("/usr/bin/firefox %u")
    assert cmd1 == ["/usr/bin/firefox"]

    # Handle multiple field codes and existing flags
    cmd2 = clean_exec_cmd("code-oss --reuse-window %F", arguments="file.txt")
    assert cmd2 == ["code-oss", "--reuse-window", "file.txt"]

    # Handle arguments with flags
    cmd3 = clean_exec_cmd("my-app %f", arguments="--verbose --output out.log")
    assert cmd3 == ["my-app", "--verbose", "--output", "out.log"]


def test_scan_desktop_apps(fake_desktop_dir, tmp_path):
    apps = scan_desktop_apps([fake_desktop_dir])
    assert "firefox.desktop" in apps
    assert "code-oss.desktop" in apps
    assert "cosmic-term.desktop" in apps
    assert "cosmic-files.desktop" in apps
    assert "hidden-util.desktop" in apps
    assert "folder.desktop" not in apps

    # User dir overrides system dir
    user_dir = tmp_path / "user_apps"
    user_dir.mkdir()
    (user_dir / "firefox.desktop").write_text(
        """[Desktop Entry]
Type=Application
Name=Firefox Developer Edition
Exec=firefox-dev %u
""",
        encoding="utf-8",
    )
    overridden_apps = scan_desktop_apps([fake_desktop_dir, user_dir])
    assert overridden_apps["firefox.desktop"].name == "Firefox Developer Edition"


def test_alias_matching(fake_desktop_dir):
    apps = scan_desktop_apps([fake_desktop_dir])

    # Alias "browser" resolves to default browser or firefox
    app_browser = find_app("browser", apps, default_browser="firefox.desktop")
    assert app_browser is not None
    assert app_browser.desktop_id == "firefox.desktop"

    # Alias "code" resolves to code-oss
    app_code = find_app("code", apps)
    assert app_code is not None
    assert app_code.desktop_id == "code-oss.desktop"

    # Alias "terminal" resolves to cosmic-term
    app_term = find_app("terminal", apps)
    assert app_term is not None
    assert app_term.desktop_id == "cosmic-term.desktop"

    # Alias "files" resolves to cosmic-files
    app_files = find_app("files", apps)
    assert app_files is not None
    assert app_files.desktop_id == "cosmic-files.desktop"


def test_fuzzy_and_keyword_matching(fake_desktop_dir):
    apps = scan_desktop_apps([fake_desktop_dir])

    # Exact name match
    assert find_app("Firefox", apps).name == "Firefox"

    # Keyword match: "vscode" -> code-oss
    assert find_app("vscode", apps).desktop_id == "code-oss.desktop"

    # Fuzzy match with slight typo: "firfox"
    matched_fuzzy = find_app("firfox", apps)
    assert matched_fuzzy is not None
    assert matched_fuzzy.name == "Firefox"

    # Non-existent app
    assert find_app("nonexistentapp12345", apps) is None


def test_launch_app_execution(fake_desktop_dir):
    apps = scan_desktop_apps([fake_desktop_dir])

    with patch("assistent.skills.app_launcher.scan_desktop_apps", return_value=apps), \
         patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/bin/gtk-launch"):

        # Launch without arguments prefers gtk-launch
        res = launch_app("firefox")
        assert "Launched Firefox" in res
        mock_popen.assert_called_once()
        cmd, kwargs = mock_popen.call_args
        assert cmd[0] == ["gtk-launch", "firefox.desktop"]
        assert kwargs.get("start_new_session") is True

    # Launch with arguments uses clean_exec_cmd
    with patch("assistent.skills.app_launcher.scan_desktop_apps", return_value=apps), \
         patch("subprocess.Popen") as mock_popen:

        res = launch_app("code", arguments="--diff file1.py file2.py")
        assert "Launched Code - OSS" in res
        assert "--diff file1.py file2.py" in res
        mock_popen.assert_called_once()
        cmd, kwargs = mock_popen.call_args
        assert cmd[0] == ["code-oss", "--diff", "file1.py", "file2.py"]
        assert kwargs.get("start_new_session") is True


def test_launch_app_not_found(fake_desktop_dir):
    apps = scan_desktop_apps([fake_desktop_dir])
    with patch("assistent.skills.app_launcher.scan_desktop_apps", return_value=apps):
        res = launch_app("random_non_existing_app")
        assert "Could not find application" in res

        empty_res = launch_app("")
        assert "must be specified" in empty_res


def test_list_apps(fake_desktop_dir):
    apps = scan_desktop_apps([fake_desktop_dir])
    with patch("assistent.skills.app_launcher.scan_desktop_apps", return_value=apps):
        listing = list_apps()
        assert "Firefox" in listing
        assert "Code - OSS" in listing
        assert "Cosmic Terminal" in listing
        assert "Cosmic Files" in listing
        # Hidden apps should not be listed
        assert "Hidden Service" not in listing
