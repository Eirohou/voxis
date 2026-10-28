"""Unit tests for audio, speech, and chime components."""

import io
from pathlib import Path
import struct
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch
import wave

import pytest

from assistent.audio.chimes import (
    generate_action_chime,
    generate_alert_chime,
    generate_start_chime,
    generate_stop_chime,
    generate_tone,
    generate_tones_sequence,
    play_action_chime,
    play_alert_chime,
    play_start_chime,
    play_stop_chime,
    play_wav_bytes,
)
from assistent.audio.recorder import (
    AudioRecorder,
    calculate_rms,
    wav_bytes_from_pcm,
)
from assistent.audio.stt import (
    GroqSTT,
    STTError,
    STTResult,
)
from assistent.audio.tts import (
    DEFAULT_VOICE_MAPPING,
    ESPEAK_VOICE_MAPPING,
    EdgeTTS,
    EspeakFallbackTTS,
    convert_audio_to_wav,
    play_audio,
)

# -------------------------------------------------------------------------
# Chime Synthesis & Playback Tests
# -------------------------------------------------------------------------


def test_generate_tone():
    """Verify that generate_tone produces valid WAV bytes with expected format."""
    wav_data = generate_tone(440.0, 880.0, duration_ms=100, sample_rate=16000)
    assert isinstance(wav_data, bytes)
    assert len(wav_data) > 44
    assert wav_data.startswith(b"RIFF")

    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        # 100ms at 16kHz = 1600 samples
        assert wf.getnframes() == 1600


def test_generate_tones_sequence():
    """Verify tone sequence generation with silence pause between notes."""
    sequence = [
        (500.0, 500.0, 100, 0.4),
        (1000.0, 1000.0, 100, 0.4),
    ]
    wav_data = generate_tones_sequence(sequence, sample_rate=16000, pause_ms=50)
    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        # 100ms (1600) + 50ms (800) + 100ms (1600) = 4000 frames
        assert wf.getnframes() == 4000


def test_all_chimes_generation():
    """Verify all four chime generators produce non-empty valid WAV data."""
    start_chime = generate_start_chime()
    stop_chime = generate_stop_chime()
    action_chime = generate_action_chime()
    alert_chime = generate_alert_chime()

    for chime_data, expected_name in [
        (start_chime, "start_chime"),
        (stop_chime, "stop_chime"),
        (action_chime, "action_chime"),
        (alert_chime, "alert_chime"),
    ]:
        assert chime_data.startswith(b"RIFF"), f"{expected_name} missing RIFF header"
        with wave.open(io.BytesIO(chime_data), "rb") as wf:
            assert wf.getframerate() == 16000
            assert wf.getnchannels() == 1
            assert wf.getnframes() > 0


@patch("subprocess.Popen")
def test_play_chimes_mocked(mock_popen):
    """Verify play chime functions trigger the player process without blocking."""
    mock_proc = MagicMock()
    mock_popen.return_value = mock_proc

    t1 = play_start_chime(non_blocking=True)
    if t1:
        t1.join(timeout=1.0)
    assert mock_popen.called

    mock_popen.reset_mock()
    t2 = play_stop_chime(non_blocking=True)
    if t2:
        t2.join(timeout=1.0)
    assert mock_popen.called

    mock_popen.reset_mock()
    t3 = play_action_chime(non_blocking=True)
    if t3:
        t3.join(timeout=1.0)
    assert mock_popen.called

    mock_popen.reset_mock()
    t4 = play_alert_chime(non_blocking=True)
    if t4:
        t4.join(timeout=1.0)
    assert mock_popen.called


# -------------------------------------------------------------------------
# Audio Recorder & Silence VAD Tests
# -------------------------------------------------------------------------


def test_calculate_rms():
    """Verify RMS calculation on silence, DC offset, and loud signals."""
    # Complete silence (all zeros)
    silence = b"\x00\x00" * 320
    assert calculate_rms(silence) == 0.0
    assert calculate_rms(b"") == 0.0

    # Constant signal of amplitude 1000
    constant_val = 1000
    samples = [constant_val] * 320
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    rms = calculate_rms(pcm)
    assert pytest.approx(rms, rel=1e-3) == 1000.0

    # Mixed loud signal
    loud_samples = [5000, -5000] * 160
    pcm_loud = struct.pack(f"<{len(loud_samples)}h", *loud_samples)
    assert pytest.approx(calculate_rms(pcm_loud), rel=1e-3) == 5000.0


def test_wav_bytes_from_pcm():
    """Verify wrapping raw PCM bytes into WAV format."""
    raw_pcm = b"\x00\x00" * 1600
    wav = wav_bytes_from_pcm(raw_pcm, sample_rate=16000, channels=1, sample_width=2)
    assert wav.startswith(b"RIFF")
    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 1600
        assert wf.getsampwidth() == 2


def test_recorder_vad_stops_after_silence():
    """Verify that AudioRecorder terminates when speech stops and silence persists."""
    recorder = AudioRecorder(
        sample_rate=16000,
        channels=1,
        silence_threshold_rms=300,
        silence_duration_seconds=0.1,  # Short silence threshold for quick test
        max_recording_seconds=5,
        chunk_duration_ms=20,
    )

    # 20ms chunk = 320 samples = 640 bytes
    quiet_chunk = struct.pack("<320h", *([50] * 320))   # RMS = 50 (< 300)
    loud_chunk = struct.pack("<320h", *([1500] * 320))  # RMS = 1500 (> 300)

    # Simulated audio stream:
    # 3 quiet chunks -> 5 speech chunks -> 10 quiet chunks (>= 0.1s silence)
    stream_data = (quiet_chunk * 3) + (loud_chunk * 5) + (quiet_chunk * 10)
    stream = io.BytesIO(stream_data)

    wav_output = recorder._record_loop(stream, use_vad=True, max_duration=5.0)
    assert wav_output.startswith(b"RIFF")

    with wave.open(io.BytesIO(wav_output), "rb") as wf:
        frames = wf.getnframes()
        # Should have stopped before reading all 10 quiet chunks
        # Total chunks in stream is 18 (5760 frames)
        # Should stop around 3 quiet + 5 loud + ~5 quiet (around 13 chunks = ~4160 frames)
        assert frames < 5760
        assert frames >= 2560


def test_recorder_manual_stop():
    """Verify manual .stop() cleanly terminates recording."""
    recorder = AudioRecorder(sample_rate=16000, chunk_duration_ms=20)
    recorder._is_recording = True
    recorder._last_wav_bytes = b"RIFFtestwavbytes"

    # Stop should signal event and return the audio bytes
    result = recorder.stop()
    assert result == b"RIFFtestwavbytes"
    assert not recorder.is_recording


def test_recorder_file_saving():
    """Verify saving WAV bytes to files and temp files."""
    recorder = AudioRecorder()
    sample_wav = wav_bytes_from_pcm(b"\x00\x00" * 320)
    recorder._last_wav_bytes = sample_wav

    # Test temp file save
    temp_path = recorder.save_to_temp_file()
    try:
        assert temp_path.exists()
        assert temp_path.read_bytes() == sample_wav
    finally:
        temp_path.unlink(missing_ok=True)

    # Test designated path save
    with tempfile.TemporaryDirectory() as td:
        dest_file = Path(td) / "subdir" / "recording.wav"
        saved_path = recorder.save_to_file(dest_file)
        assert saved_path == dest_file
        assert dest_file.exists()
        assert dest_file.read_bytes() == sample_wav


# -------------------------------------------------------------------------
# STT (GroqSTT) Tests
# -------------------------------------------------------------------------


def test_groq_stt_missing_api_key():
    """Verify that GroqSTT raises ValueError when no API key is configured."""
    with patch.dict("os.environ", {}, clear=True):
        stt = GroqSTT(api_key="")
        stt.api_key = None
        with pytest.raises(ValueError, match="Groq API key not found"):
            stt.transcribe(b"fake_audio_bytes")


def test_groq_stt_language_normalization():
    """Verify language code normalization for Whisper responses."""
    stt = GroqSTT(api_key="gsk_test")
    assert stt._normalize_language("English") == "en"
    assert stt._normalize_language("polish") == "pl"
    assert stt._normalize_language("German") == "de"
    assert stt._normalize_language("en") == "en"
    assert stt._normalize_language("pl") == "pl"
    assert stt._normalize_language(None) is None


@patch("httpx.Client.post")
def test_groq_stt_sync_transcribe(mock_post):
    """Verify synchronous transcription using mocked Groq Whisper response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "text": "Hello, how are you?",
        "language": "english",
        "duration": 1.85,
    }
    mock_post.return_value = mock_resp

    stt = GroqSTT(api_key="gsk_test_key_123")
    audio_sample = b"RIFF" + (b"\x00" * 100)
    result = stt.transcribe(audio_sample)

    assert isinstance(result, STTResult)
    assert result.text == "Hello, how are you?"
    assert result.language == "en"
    assert result.duration == 1.85

    # Check request headers and payload
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer gsk_test_key_123"
    assert kwargs["data"]["model"] == "whisper-large-v3"
    assert kwargs["data"]["response_format"] == "verbose_json"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_groq_stt_async_transcribe(mock_async_post):
    """Verify asynchronous transcription using mocked Groq Whisper response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "text": "Dzień dobry, w czym mogę pomóc?",
        "language": "polish",
        "duration": 2.1,
    }
    mock_async_post.return_value = mock_resp

    stt = GroqSTT(api_key="gsk_test_key_123")
    result = await stt.transcribe_async(b"RIFF" + (b"\x00" * 100))

    assert result.text == "Dzień dobry, w czym mogę pomóc?"
    assert result.language == "pl"
    assert result.duration == 2.1


@patch("httpx.Client.post")
def test_groq_stt_http_error(mock_post):
    """Verify STTError is raised on HTTP failure."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Invalid API Key"
    mock_post.return_value = mock_resp

    stt = GroqSTT(api_key="bad_key")
    with pytest.raises(STTError, match="Groq STT request failed"):
        stt.transcribe(b"dummy")


# -------------------------------------------------------------------------
# TTS (EdgeTTS & EspeakFallbackTTS) Tests
# -------------------------------------------------------------------------


def test_edge_tts_voice_routing():
    """Verify language code to voice routing for English, Polish, and German."""
    tts = EdgeTTS()
    assert tts.get_voice("en") == "en-US-ChristopherNeural"
    assert tts.get_voice("EN") == "en-US-ChristopherNeural"
    assert tts.get_voice("pl") == "pl-PL-MarekNeural"
    assert tts.get_voice("de") == "de-DE-ConradNeural"
    # Fallback to default voice on unknown language
    assert tts.get_voice("unknown") == DEFAULT_VOICE_MAPPING["en"]
    assert tts.get_voice(None) == DEFAULT_VOICE_MAPPING["en"]


def test_espeak_fallback_voice_routing():
    """Verify espeak voice routing for English, Polish, and German."""
    espeak = EspeakFallbackTTS()
    assert espeak.get_voice("en") == "en-us"
    assert espeak.get_voice("pl") == "pl"
    assert espeak.get_voice("de") == "de"
    assert espeak.get_voice("unknown") == ESPEAK_VOICE_MAPPING["en"]


@pytest.mark.asyncio
async def test_edge_tts_mocked_websocket():
    """Verify EdgeTTS synthesis via simulated WebSocket stream."""
    tts = EdgeTTS(fallback_enabled=False)

    fake_mp3_payload = b"\xff\xfb\x90\x00" * 50
    header_text = b"Path:audio\r\nX-RequestId:123\r\nContent-Type:audio/mpeg\r\n\r\n"
    binary_message = struct.pack(">H", len(header_text)) + header_text + fake_mp3_payload

    # Create mock websocket context manager
    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = [
        "Path:speech.config\r\n",
        binary_message,
        "Path:turn.end\r\n",
    ]

    mock_connect = MagicMock()
    mock_connect.return_value.__aenter__.return_value = mock_ws
    mock_connect.return_value.__aexit__.return_value = None

    with patch("websockets.connect", mock_connect):
        audio_out = await tts.synthesize_async("Testing Edge TTS", language="en")
        assert audio_out == fake_mp3_payload
        assert mock_ws.send.call_count == 2  # config message + ssml message


def test_edge_tts_fallback_to_espeak():
    """Verify automatic fallback to EspeakFallbackTTS when EdgeTTS fails."""
    mock_fallback = MagicMock()
    mock_fallback.synthesize.return_value = b"RIFF_ESPEAK_FALLBACK"

    tts = EdgeTTS(fallback_tts=mock_fallback, fallback_enabled=True)

    # Force websocket connect to fail
    with patch("websockets.connect", side_effect=Exception("Connection refused")):
        result = tts.synthesize("Hello fallback", language="pl")
        assert result == b"RIFF_ESPEAK_FALLBACK"
        mock_fallback.synthesize.assert_called_once_with("Hello fallback", language="pl")


def test_espeak_fallback_real_synthesis():
    """Verify that espeak-ng produces valid RIFF WAV audio on system."""
    espeak = EspeakFallbackTTS()
    if not espeak.espeak_bin:
        pytest.skip("espeak-ng not installed")

    wav_bytes = espeak.synthesize("test", language="en")
    assert isinstance(wav_bytes, bytes)
    assert wav_bytes.startswith(b"RIFF")
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() > 0
        assert wf.getnframes() > 0


@patch("subprocess.Popen")
def test_play_audio_mocked(mock_popen):
    """Verify play_audio invokes audio player with WAV data."""
    mock_proc = MagicMock()
    mock_popen.return_value = mock_proc

    sample_wav = wav_bytes_from_pcm(b"\x00\x00" * 160)
    t = play_audio(sample_wav, non_blocking=True)
    if t:
        t.join(timeout=1.0)
    assert mock_popen.called
