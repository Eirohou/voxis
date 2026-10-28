"""Tests for Unix domain socket IPC communication."""

import asyncio
import os
import tempfile
import pytest
import pytest_asyncio

from assistent.ipc import IPCClient, IPCServer


@pytest.mark.asyncio
async def test_ipc_ping_and_trigger():
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test.sock")
        triggered = []

        def on_trigger():
            triggered.append(True)

        server = IPCServer(
            socket_path=sock_path,
            on_trigger=on_trigger,
            on_ask=lambda q: f"Echo: {q}",
            get_status=lambda: {"state": "idle"},
        )
        await server.start()

        client = IPCClient(socket_path=sock_path)

        # Test PING
        ping_res = await client.send_command("PING")
        assert ping_res == "PONG"

        # Test TRIGGER
        trig_res = await client.send_command("TRIGGER")
        assert "OK" in trig_res
        await asyncio.sleep(0.05)
        assert len(triggered) == 1

        # Test ASK
        ask_res = await client.send_command("ASK hello")
        assert ask_res == "Echo: hello"

        # Test STATUS
        status_res = await client.send_command("STATUS")
        assert '"state": "idle"' in status_res

        await server.stop()
