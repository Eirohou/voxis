# Assistent 🎙️

A lightweight, voice-first personal AI assistant for Linux (Arch Linux / COSMIC Desktop / Wayland / PipeWire).

Built with a **zero-compute, zero-cost cloud architecture** using free tiers (Groq Whisper + Llama 3.3 70B) and streaming Microsoft Edge neural voices (Edge-TTS), with offline fallbacks (`espeak-ng`).

---

## ✨ Features

- **Voice-First Interaction**:
  - Global trigger: press a global hotkey from anywhere on your desktop to speak.
  - Automatic silence detection (RMS Voice Activity Detection): stops recording when you pause talking.
  - Sub-second transcription via Groq `whisper-large-v3` with zero local CPU load.
  - Natural spoken answers via streaming Edge neural voices (`en-US-ChristopherNeural`, `pl-PL-MarekNeural`, `de-DE-ConradNeural`).
  - Subtle audio chimes for start/stop listening and silent feedback on mechanical actions (volume/media).
- **Trilingual Support**:
  - Automatically understands and speaks **English**, **Polish**, and **German** in that order of preference.
- **Type-Routed Note Taking**:
  - Explicit topic notes: *"Take a todo note: buy milk and eggs"* ➔ saved/appended to `notes/todo.md`.
  - Daily quick logs: *"Take a quick note: review PR later"* ➔ saved to `notes/YYYY-MM-DD.md` with timestamp `[HH:MM]`.
  - Search & read aloud: *"Search notes for groq"*, *"Read my todo note"*.
- **Smart App Launcher**:
  - Scans system `.desktop` files in `/usr/share/applications` and `~/.local/share/applications`.
  - Fuzzy matching & alias routing (e.g. `browser`, `code`, `terminal`, `files`, `spotify`).
  - Argument passing: *"Open notes in code"* ➔ launches VS Code with `./notes`.
  - Non-blocking detached execution via `gtk-launch`.
- **Desktop Utility Pack**:
  - **Volume Control**: PipeWire volume control (`wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+ / 5%-`).
  - **Media Control**: Media playback via `playerctl` (`play-pause`, `next`, `previous`).
  - **Clipboard Integration**: Wayland clipboard access (`wl-copy` / `wl-paste`).
  - **Timers & Reminders**: Async countdown timers with alert sound and `notify-send` desktop notification.

---

## 🚀 Quick Start

### 1. Configure Your Free API Key
Get a free API key at [Groq Console](https://console.groq.com) (no credit card needed).
Copy `.env.example` to `.env` and add your key:

```bash
cp .env.example .env
# Edit .env and set:
# GROQ_API_KEY=gsk_...
```

### 2. Run the Background Daemon
Start the assistant daemon:

```bash
./bin/assistent daemon
```

### 3. Bind Global Shortcut in COSMIC Desktop
Go to **Settings → Keyboard → Custom Shortcuts** in COSMIC Desktop and add:
- **Name**: `Trigger Assistent`
- **Command**: `/home/fabian/projects/assistent/bin/assistent trigger`
- **Shortcut**: `Super + Space` (or your preferred shortcut)

Whenever you press `Super + Space`:
1. A soft audio chime plays and the assistant starts listening.
2. Speak your command (in English, Polish, or German).
3. The assistant automatically detects silence, executes your requested action, and replies via voice or chime.

---

## 🖥️ Alternative Usage Modes

### Interactive Terminal (TUI)
You can launch an interactive terminal interface to see live status badges and type commands:

```bash
./bin/assistent tui
```

### Direct CLI Command
Send a one-off text query directly:

```bash
./bin/assistent ask "Take a todo note: write documentation"
./bin/assistent ask "Open notes in code"
./bin/assistent ask "Jaka jest dzisiejsza data?"
./bin/assistent ask "Wie spät ist es?"
```

---

## 🧪 Running Tests

The test suite contains 55 unit and integration tests covering audio capture, silence VAD, Groq STT/LLM, Edge-TTS, IPC sockets, notes, and app launcher:

```bash
./.venv/bin/pytest -v
```

---

## 📁 Project Structure

```
assistent/
├── bin/assistent             # Executable launcher script
├── config.yaml               # Assistant, audio, LLM, and TTS configuration
├── .env.example              # Environment variables template
├── assistent/
│   ├── cli.py                # Main CLI dispatcher (daemon, trigger, tui, ask)
│   ├── config.py             # Settings manager
│   ├── ipc.py                # Unix domain socket server & client (/tmp/assistent.sock)
│   ├── audio/
│   │   ├── chimes.py         # Pure Python synthesized audio chimes
│   │   ├── recorder.py       # arecord audio capture + RMS silence VAD
│   │   ├── stt.py            # Groq Whisper transcription (auto language detection)
│   │   └── tts.py            # Multilingual Edge-TTS with espeak-ng fallback
│   ├── core/
│   │   ├── agent.py          # Conversational agent & tool execution loop
│   │   ├── llm.py            # Groq client with native function calling
│   │   └── persona.py        # System prompt & hybrid verbosity rules
│   ├── skills/
│   │   ├── base.py           # Tool decorator and schema registry
│   │   ├── notes.py          # Type-routed markdown notes & daily log
│   │   ├── app_launcher.py   # Fuzzy .desktop app launcher with arguments
│   │   ├── media.py          # playerctl integration
│   │   ├── volume.py         # PipeWire wpctl integration
│   │   ├── clipboard.py      # Wayland wl-copy & wl-paste
│   │   └── timer.py          # Non-blocking async timer & notifications
│   └── ui/
│       └── console.py        # Rich terminal UI & status HUD
├── notes/                    # Directory where Markdown notes are stored
└── tests/                    # 55 automated unit & integration tests
```
