"""Application launcher skill for scanning .desktop files and launching apps."""

import difflib
from dataclasses import dataclass, field
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Dict, List, Optional

from assistent.skills.base import tool


@dataclass
class DesktopApp:
    """Represents an application parsed from a .desktop file."""
    desktop_id: str
    name: str
    exec: str
    generic_name: str = ""
    comment: str = ""
    keywords: List[str] = field(default_factory=list)
    no_display: bool = False
    path: str = ""


# Default application directories according to XDG spec
DEFAULT_APP_DIRS: List[Path] = [
    Path("/usr/share/applications"),
    Path.home() / ".local/share/applications",
]

# Alias mappings for common application roles
ALIASES: Dict[str, List[str]] = {
    "browser": [
        "default-web-browser",
        "firefox",
        "chromium",
        "google-chrome",
        "brave-browser",
        "brave",
        "vivaldi",
        "microsoft-edge",
    ],
    "code": ["code", "code-oss", "vscodium", "vscode"],
    "terminal": [
        "cosmic-term",
        "gnome-terminal",
        "alacritty",
        "kitty",
        "foot",
        "wezterm",
        "konsole",
        "xterm",
    ],
    "files": ["cosmic-files", "nautilus", "thunar", "dolphin", "pcmanfm", "nemo"],
    "editor": ["code", "code-oss", "gedit", "kate", "gnome-text-editor", "nano"],
    "music": ["spotify", "rhythmbox", "vlc", "amberol"],
    "calc": ["gnome-calculator", "kcalc", "cosmic-calculator", "calculator"],
    "calculator": ["gnome-calculator", "kcalc", "cosmic-calculator", "calculator"],
}


def parse_desktop_file(file_path: Path) -> Optional[DesktopApp]:
    """Parse a single .desktop file extracting application metadata."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    in_desktop_entry = False
    name = ""
    exec_cmd = ""
    generic_name = ""
    comment = ""
    keywords: List[str] = []
    no_display = False
    is_application = True

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_desktop_entry = (line == "[Desktop Entry]")
            continue
        if not in_desktop_entry:
            continue

        if "=" not in line:
            continue

        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()

        # Prioritize base unlocalized keys
        if key == "Name" and not name:
            name = val
        elif key == "Exec" and not exec_cmd:
            exec_cmd = val
        elif key == "GenericName" and not generic_name:
            generic_name = val
        elif key == "Comment" and not comment:
            comment = val
        elif key == "Keywords":
            keywords.extend([k.strip().lower() for k in val.split(";") if k.strip()])
        elif key in ("NoDisplay", "Hidden"):
            if val.lower() == "true":
                no_display = True
        elif key == "Type":
            if val.lower() != "application":
                is_application = False

    if not is_application or not name or not exec_cmd:
        return None

    return DesktopApp(
        desktop_id=file_path.name,
        name=name,
        exec=exec_cmd,
        generic_name=generic_name,
        comment=comment,
        keywords=keywords,
        no_display=no_display,
        path=str(file_path),
    )


def scan_desktop_apps(directories: Optional[List[Path]] = None) -> Dict[str, DesktopApp]:
    """Scan given directories for .desktop files, user dirs overriding system dirs."""
    dirs = directories if directories is not None else DEFAULT_APP_DIRS
    apps: Dict[str, DesktopApp] = {}

    for directory in dirs:
        dir_path = Path(directory).expanduser()
        if not dir_path.is_dir():
            continue
        for p in sorted(dir_path.glob("*.desktop")):
            app = parse_desktop_file(p)
            if app:
                apps[app.desktop_id] = app

    return apps


def get_default_browser() -> Optional[str]:
    """Attempt to detect the system default web browser desktop ID."""
    # Check via xdg-settings
    try:
        res = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # Fallback to xdg-mime
    try:
        res = subprocess.run(
            ["xdg-mime", "query", "default", "x-scheme-handler/http"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return None


def find_app(
    query: str,
    apps: Dict[str, DesktopApp],
    default_browser: Optional[str] = None,
) -> Optional[DesktopApp]:
    """Find the best matching DesktopApp using alias, exact, keyword, and fuzzy matching."""
    q = query.strip().lower()
    if not q:
        return None

    # 1. Alias lookup
    if q in ALIASES:
        candidates = ALIASES[q]
        if q == "browser":
            browser_id = default_browser or get_default_browser()
            if browser_id and browser_id in apps:
                return apps[browser_id]
        # Check candidate list
        for candidate in candidates:
            cand_id = candidate if candidate.endswith(".desktop") else f"{candidate}.desktop"
            if cand_id in apps:
                return apps[cand_id]
            for app in apps.values():
                app_base = app.desktop_id.removesuffix(".desktop").lower()
                exec_base = Path(shlex.split(app.exec)[0]).name.lower() if app.exec else ""
                if candidate.lower() in (app_base, app.name.lower(), exec_base):
                    return app

    # 2. Exact match on desktop ID, app name, or binary executable
    for app in apps.values():
        app_base = app.desktop_id.removesuffix(".desktop").lower()
        exec_base = Path(shlex.split(app.exec)[0]).name.lower() if app.exec else ""
        if q in (app.desktop_id.lower(), app_base, app.name.lower(), exec_base):
            return app

    # 3. Match keyword or generic name
    for app in apps.values():
        if q in app.keywords or q == app.generic_name.lower():
            return app

    # 4. Substring match on name, desktop_id, or keywords
    for app in apps.values():
        app_base = app.desktop_id.removesuffix(".desktop").lower()
        if q in app.name.lower() or q in app_base:
            return app
        if any(q in kw for kw in app.keywords):
            return app

    # 5. Fuzzy matching using SequenceMatcher
    best_app: Optional[DesktopApp] = None
    best_score = 0.0

    for app in apps.values():
        app_base = app.desktop_id.removesuffix(".desktop").lower()
        scores = [
            difflib.SequenceMatcher(None, q, app.name.lower()).ratio(),
            difflib.SequenceMatcher(None, q, app_base).ratio(),
        ]
        if app.generic_name:
            scores.append(difflib.SequenceMatcher(None, q, app.generic_name.lower()).ratio())
        for kw in app.keywords:
            scores.append(difflib.SequenceMatcher(None, q, kw).ratio())

        max_app_score = max(scores)
        if max_app_score > best_score:
            best_score = max_app_score
            best_app = app

    # Require minimum similarity threshold of 0.5
    if best_score >= 0.5:
        return best_app

    return None


def clean_exec_cmd(exec_str: str, arguments: str = "") -> List[str]:
    """Parse Exec string, stripping field codes like %u, %F and appending arguments."""
    tokens = shlex.split(exec_str)
    cmd = [t for t in tokens if not (t.startswith("%") and len(t) == 2)]
    if arguments:
        cmd.extend(shlex.split(arguments))
    return cmd


@tool
def launch_app(app_name: str, arguments: str = "") -> str:
    """Launch a desktop application asynchronously by name or alias with optional arguments."""
    if not app_name or not app_name.strip():
        return "Application name must be specified."

    apps = scan_desktop_apps()
    app = find_app(app_name, apps)
    if not app:
        return f"Could not find application matching '{app_name}'."

    # Use gtk-launch when available and arguments are not flags, otherwise run Exec binary directly
    if shutil.which("gtk-launch") and not arguments:
        spawn_cmd = ["gtk-launch", app.desktop_id]
    else:
        spawn_cmd = clean_exec_cmd(app.exec, arguments)

    try:
        subprocess.Popen(
            spawn_cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if arguments:
            return f"Launched {app.name} with arguments: {arguments}"
        return f"Launched {app.name}."
    except Exception as e:
        return f"Failed to launch {app.name}: {e}"


@tool
def list_apps() -> str:
    """List common installed desktop applications."""
    apps = scan_desktop_apps()
    visible_apps = [app for app in apps.values() if not app.no_display]
    if not visible_apps:
        return "No installed applications found."

    # Sort alphabetically by name
    visible_apps.sort(key=lambda a: a.name.lower())

    # Format list
    lines = []
    seen_names = set()
    for app in visible_apps:
        if app.name.lower() in seen_names:
            continue
        seen_names.add(app.name.lower())
        desc = f" ({app.generic_name})" if app.generic_name else ""
        lines.append(f"- {app.name}{desc}")

    return f"Installed applications ({len(lines)}):\n" + "\n".join(lines)
