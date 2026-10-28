"""Unix domain socket IPC server and client for triggering the assistant."""

import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from assistent.config import get_config


class IPCServer:
    """Async Unix domain socket server running in the background daemon."""

    def __init__(
        self,
        socket_path: Optional[str] = None,
        on_trigger: Optional[Callable[[], Any]] = None,
        on_ask: Optional[Callable[[str], Any]] = None,
        get_status: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        config = get_config()
        self.socket_path = socket_path or config.ipc.socket_path
        self.on_trigger = on_trigger
        self.on_ask = on_ask
        self.get_status = get_status
        self._server: Optional[asyncio.Server] = None

    async def start(self):
        """Starts the Unix domain socket server."""
        # Clean up stale socket file if it exists
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self.socket_path
        )

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        try:
            line = await reader.readline()
            if not line:
                return

            cmd_str = line.decode("utf-8").strip()
            parts = cmd_str.split(" ", 1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "PING":
                writer.write(b"PONG\n")
            elif cmd == "TRIGGER":
                if self.on_trigger:
                    # Execute trigger callback in background task
                    asyncio.create_task(self._safe_call(self.on_trigger))
                writer.write(b"OK: TRIGGERED\n")
            elif cmd == "ASK":
                if self.on_ask:
                    res = await self._safe_call(self.on_ask, arg)
                    out = str(res) if res is not None else "OK"
                    writer.write(f"{out}\n".encode("utf-8"))
                else:
                    writer.write(b"ERROR: No ask handler\n")
            elif cmd == "STATUS":
                status = self.get_status() if self.get_status else {"status": "running"}
                writer.write(f"{json.dumps(status)}\n".encode("utf-8"))
            else:
                writer.write(b"ERROR: Unknown command\n")

            await writer.drain()
        except Exception as e:
            writer.write(f"ERROR: {str(e)}\n".encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _safe_call(self, func: Callable, *args):
        if inspect.iscoroutinefunction(func):
            return await func(*args)
        return func(*args)

    async def stop(self):
        """Stops the socket server and removes the socket file."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass


class IPCClient:
    """Client for communicating with the background daemon over Unix socket."""

    def __init__(self, socket_path: Optional[str] = None):
        config = get_config()
        self.socket_path = socket_path or config.ipc.socket_path

    async def send_command(self, cmd: str) -> str:
        """Sends a single line command to the daemon socket and reads reply."""
        if not os.path.exists(self.socket_path):
            raise ConnectionError(f"Daemon socket not found at '{self.socket_path}'. Is the daemon running?")

        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        try:
            writer.write(f"{cmd.strip()}\n".encode("utf-8"))
            await writer.drain()
            reply = await reader.readline()
            return reply.decode("utf-8").strip()
        finally:
            writer.close()
            await writer.wait_closed()

    async def is_running_async(self) -> bool:
        """Checks asynchronously if the daemon is currently running and responsive."""
        try:
            res = await self.send_command("PING")
            return res == "PONG"
        except Exception:
            return False

    def is_running(self) -> bool:
        """Checks synchronously if the daemon is currently running and responsive."""
        try:
            return asyncio.run(self.send_command("PING")) == "PONG"
        except Exception:
            return False

    def trigger(self) -> str:
        """Sends TRIGGER command synchronously."""
        return asyncio.run(self.send_command("TRIGGER"))

    def ask(self, query: str) -> str:
        """Sends ASK command synchronously."""
        return asyncio.run(self.send_command(f"ASK {query}"))
