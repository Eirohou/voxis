"""CLI dispatcher for the Assistent personal voice AI."""

import argparse
import asyncio
import os
import sys
from typing import Optional

from assistent.config import ensure_api_key_interactive, get_config, save_api_key
from assistent.core.agent import Agent
from assistent.ipc import IPCClient, IPCServer
from assistent.skills.base import default_registry
from assistent.ui.console import AssistantConsole


class AssistantDaemon:
    """Background voice daemon managing triggers, audio, and agent loop."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = get_config(config_path)
        self.console = AssistantConsole()
        self.agent = Agent(registry=default_registry)
        self.state = "IDLE"
        self._is_processing = False

        # Lazy imports for audio components
        try:
            import assistent.skills  # Register all tool skills
            from assistent.audio.chimes import (
                play_action_chime,
                play_start_chime,
                play_stop_chime,
            )
            from assistent.audio.recorder import AudioRecorder
            from assistent.audio.stt import GroqSTT
            from assistent.audio.tts import EdgeTTS

            self.play_start = play_start_chime
            self.play_stop = play_stop_chime
            self.play_action = play_action_chime
            self.recorder = AudioRecorder(
                sample_rate=self.config.audio.sample_rate,
                silence_threshold_rms=self.config.audio.silence_threshold_rms,
                silence_duration_seconds=self.config.audio.silence_duration_seconds,
            )
            self.stt = GroqSTT(api_key=self.config.stt.api_key)
            self.tts = EdgeTTS()
            self.audio_available = True
        except ImportError:
            self.audio_available = False

        self.ipc_server = IPCServer(
            socket_path=self.config.ipc.socket_path,
            on_trigger=self.handle_trigger,
            on_ask=self.handle_ask,
            get_status=lambda: {"state": self.state},
        )

    def set_state(self, state: str, detail: Optional[str] = None):
        self.state = state
        self.console.status_badge(state, detail)

    async def handle_trigger(self):
        """Called when a trigger signal (hotkey / CLI) arrives."""
        if self._is_processing:
            self.console.print_error("Assistant is already processing a request.")
            return

        self._is_processing = True
        try:
            if not self.audio_available:
                self.console.print_error("Audio components not available.")
                return

            # 1. Listen
            self.set_state("LISTENING")
            self.play_start()
            audio_bytes = await asyncio.to_thread(self.recorder.record, use_vad=True)
            self.play_stop()

            if not audio_bytes or len(audio_bytes) < 1000:
                self.set_state("IDLE")
                return

            # 2. Transcribe
            self.set_state("TRANSCRIBING")
            stt_result = await self.stt.transcribe_async(audio_bytes)
            user_text = stt_result.text.strip()
            language = stt_result.language or "en"

            if not user_text:
                self.set_state("IDLE")
                return

            self.console.print_user_speech(user_text, language=language)

            # 3. Think & Execute
            self.set_state("THINKING")

            def on_tool(name: str, args: dict):
                self.set_state("EXECUTING", f"{name}")
                self.console.print_tool_execution(name, args)

            agent_result = await self.agent.run(user_text, on_tool_call=on_tool)

            # 4. Feedback
            if agent_result.silent_feedback and (not agent_result.text or len(agent_result.text) < 15):
                # Subtle chime for mechanical actions
                self.play_action()
            elif agent_result.text:
                self.set_state("SPEAKING")
                self.console.print_assistant_reply(agent_result.text)
                await asyncio.to_thread(self.tts.speak, agent_result.text, language=language)

            self.set_state("IDLE")
        except Exception as e:
            self.console.print_error(f"Error during voice interaction: {str(e)}")
            self.set_state("IDLE")
        finally:
            self._is_processing = False

    async def handle_ask(self, query: str) -> str:
        """Called when a text command is sent to the daemon."""
        self.console.print_user_speech(query, language="text")
        self.set_state("THINKING")

        def on_tool(name: str, args: dict):
            self.set_state("EXECUTING", f"{name}")
            self.console.print_tool_execution(name, args)

        agent_result = await self.agent.run(query, on_tool_call=on_tool)
        self.console.print_assistant_reply(agent_result.text)
        self.set_state("IDLE")
        return agent_result.text

    async def start(self):
        """Starts the daemon."""
        self.console.print_banner()
        self.console.console.print(f"[green]Starting IPC server at:[/] [cyan]{self.config.ipc.socket_path}[/]")
        await self.ipc_server.start()
        self.set_state("IDLE")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.ipc_server.stop()


def main():
    parser = argparse.ArgumentParser(
        description="Assistent - Voice-first personal AI assistant for Linux"
    )
    parser.add_argument("--config", "-c", type=str, help="Path to config.yaml")

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # daemon
    subparsers.add_parser("daemon", help="Run background assistant daemon")

    # trigger
    subparsers.add_parser(
        "trigger", help="Send trigger pulse to running daemon (bind to hotkey)"
    )

    # ask
    ask_parser = subparsers.add_parser(
        "ask", help="Send a text command directly to the assistant"
    )
    ask_parser.add_argument("query", type=str, help="The query or command to execute")

    # tui / interactive
    subparsers.add_parser("tui", help="Interactive terminal mode")

    # setup / configure key
    setup_parser = subparsers.add_parser("setup", help="Configure Groq API key")
    setup_parser.add_argument("--key", type=str, help="API key to save directly without prompt")

    args = parser.parse_args()

    # Default to 'tui' if no command provided
    command = args.command or "tui"

    if command == "setup":
        console = AssistantConsole()
        if args.key:
            save_api_key(args.key)
            console.console.print("[bold green]✓ API key successfully saved to .env![/]")
        else:
            # Force interactive prompt even if a key already exists
            ensure_api_key_interactive(console.console)

    elif command == "daemon":
        daemon = AssistantDaemon(config_path=args.config)
        ensure_api_key_interactive(daemon.console.console)
        try:
            asyncio.run(daemon.start())
        except KeyboardInterrupt:
            print("\nShutting down daemon...")

    elif command == "trigger":
        client = IPCClient()
        try:
            res = client.trigger()
            print(res)
        except ConnectionError as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif command == "ask":
        client = IPCClient()
        if client.is_running():
            reply = client.ask(args.query)
            print(reply)
        else:
            ensure_api_key_interactive()
            # Run standalone in-process
            async def run_standalone():
                # Import skills to register tools
                import assistent.skills
                agent = Agent(registry=default_registry)
                res = await agent.run(args.query)
                print(res.text)

            asyncio.run(run_standalone())

    elif command == "tui":
        # Interactive mode
        import assistent.skills
        console = AssistantConsole()
        console.print_banner()

        # First-time setup check: prompt to paste API key if missing
        ensure_api_key_interactive(console.console)

        client = IPCClient()
        daemon_online = client.is_running()

        if daemon_online:
            console.console.print("[green]Daemon is online.[/] You can trigger via hotkey or type commands below.\n")
        else:
            console.console.print("[yellow]Daemon not running.[/] Operating in standalone text mode.\n")

        agent = Agent(registry=default_registry)

        while True:
            try:
                user_input = console.console.input("[bold cyan]You > [/]").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    break

                async def process_text():
                    def on_tool(name: str, args: dict):
                        console.print_tool_execution(name, args)

                    result = await agent.run(user_input, on_tool_call=on_tool)
                    console.print_assistant_reply(result.text)

                asyncio.run(process_text())
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break


if __name__ == "__main__":
    main()
