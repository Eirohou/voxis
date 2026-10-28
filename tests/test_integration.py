"""End-to-end integration tests for Assistent CLI and Daemon."""

import asyncio
import os
import tempfile
import pytest
import pytest_asyncio

from assistent.cli import AssistantDaemon
from assistent.config import AppConfig
from assistent.core.agent import Agent
from assistent.core.llm import LLMResponse, ToolCall
from assistent.ipc import IPCClient
from assistent.skills.base import default_registry


class MockLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def chat(self, messages, tools=None):
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Success.")


@pytest.mark.asyncio
async def test_daemon_handle_ask_with_skill_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "assistent_test.sock")
        notes_dir = os.path.join(tmpdir, "notes")
        os.makedirs(notes_dir, exist_ok=True)

        # Configure daemon
        daemon = AssistantDaemon()
        daemon.config.ipc.socket_path = sock_path
        daemon.ipc_server.socket_path = sock_path
        daemon.config.assistant.notes_dir = notes_dir

        # Mock LLM to invoke note tool
        mock_llm = MockLLM(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="tc_1",
                            name="save_note",
                            arguments={
                                "type_or_topic": "todo",
                                "content": "buy milk and eggs",
                            },
                        )
                    ],
                ),
                LLMResponse(content="Added to your todo note.", tool_calls=[]),
            ]
        )
        daemon.agent.llm = mock_llm

        # Test ask directly
        reply = await daemon.handle_ask("Take a todo note: buy milk and eggs")
        assert "Added to your todo note." in reply

        # Verify note was created on disk in notes_dir
        todo_file = os.path.join(notes_dir, "todo.md")
        assert os.path.exists(todo_file)
        with open(todo_file, "r") as f:
            content = f.read()
            assert "buy milk and eggs" in content


@pytest.mark.asyncio
async def test_daemon_ipc_ask_and_trigger():
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = os.path.join(tmpdir, "test_ipc_e2e.sock")

        daemon = AssistantDaemon()
        daemon.config.ipc.socket_path = sock_path
        daemon.ipc_server.socket_path = sock_path

        mock_llm = MockLLM([LLMResponse(content="Pong response.", tool_calls=[])])
        daemon.agent.llm = mock_llm

        # Mock hardware audio components so test does not block on microphone
        if daemon.audio_available:
            daemon.play_start = lambda: None
            daemon.play_stop = lambda: None
            daemon.play_action = lambda: None
            daemon.recorder.record = lambda *args, **kwargs: b""

        # Start daemon IPC server in background
        server_task = asyncio.create_task(daemon.ipc_server.start())
        await asyncio.sleep(0.05)

        client = IPCClient(socket_path=sock_path)
        assert await client.is_running_async()

        # Send ASK command through IPC
        res = await client.send_command("ASK ping")
        assert "Pong response." in res

        # Send TRIGGER command
        trig_res = await client.send_command("TRIGGER")
        assert "OK: TRIGGERED" in trig_res
        await asyncio.sleep(0.05)

        await daemon.ipc_server.stop()
        server_task.cancel()
