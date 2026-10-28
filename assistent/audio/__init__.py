"""Audio module for Assistent.

Provides chimes, audio recording with silence VAD, Groq STT, and Edge/espeak TTS.
"""

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
    EdgeTTS,
    EspeakFallbackTTS,
    convert_audio_to_wav,
    play_audio,
)

__all__ = [
    "AudioRecorder",
    "calculate_rms",
    "wav_bytes_from_pcm",
    "GroqSTT",
    "STTResult",
    "STTError",
    "EdgeTTS",
    "EspeakFallbackTTS",
    "play_audio",
    "convert_audio_to_wav",
    "generate_tone",
    "generate_tones_sequence",
    "generate_start_chime",
    "generate_stop_chime",
    "generate_action_chime",
    "generate_alert_chime",
    "play_wav_bytes",
    "play_start_chime",
    "play_stop_chime",
    "play_action_chime",
    "play_alert_chime",
]
