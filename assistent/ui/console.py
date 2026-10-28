"""Rich terminal UI and formatted status console for Assistent."""

import datetime
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


class AssistantConsole:
    """Manages styled terminal output and status badges."""

    def __init__(self):
        self.console = console

    def print_banner(self):
        banner_text = Text()
        banner_text.append("Assistent ", style="bold cyan")
        banner_text.append("v0.1.0 ", style="dim")
        banner_text.append("• Voice AI for Linux (Arch / COSMIC / PipeWire)\n", style="italic")
        banner_text.append("Languages: ", style="bold")
        banner_text.append("English (EN), Polish (PL), German (DE)\n", style="green")
        banner_text.append("Trigger: ", style="bold")
        banner_text.append("Run 'assistent trigger' or bind to a global hotkey", style="yellow")

        self.console.print(Panel(banner_text, border_style="cyan", expand=False))

    def status_badge(self, state: str, detail: Optional[str] = None):
        states = {
            "IDLE": ("● IDLE", "dim white"),
            "LISTENING": ("● LISTENING...", "bold red"),
            "TRANSCRIBING": ("⚡ TRANSCRIBING...", "bold yellow"),
            "THINKING": ("🧠 THINKING...", "bold magenta"),
            "EXECUTING": ("⚙ EXECUTING...", "bold blue"),
            "SPEAKING": ("🔊 SPEAKING...", "bold green"),
        }
        badge, style = states.get(state.upper(), (f"● {state.upper()}", "white"))
        text = Text()
        text.append(f"[{badge}]", style=style)
        if detail:
            text.append(f" {detail}", style="dim")
        self.console.print(text)

    def print_user_speech(self, text: str, language: Optional[str] = None):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        lang_badge = f"[{language.upper()}] " if language else ""
        self.console.print(
            f"[dim]{timestamp}[/] [bold cyan]You ({lang_badge}):[/] [bold white]{text}[/]"
        )

    def print_assistant_reply(self, text: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.console.print(
            f"[dim]{timestamp}[/] [bold green]Assistent:[/] {text}"
        )

    def print_tool_execution(self, tool_name: str, args: dict):
        args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        self.console.print(
            f"  [bold blue]↳ Action:[/] [yellow]{tool_name}[/]([dim]{args_str}[/])"
        )

    def print_error(self, message: str):
        self.console.print(f"[bold red]Error:[/] {message}")
