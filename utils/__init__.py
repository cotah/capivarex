"""
Utility package for shared helpers.
"""

try:
    from utils.audio_converter import (  # noqa: F401
        calculate_rms,
        is_speech,
        mp3_to_mulaw_chunks,
        mp3_to_mulaw_raw,
        mulaw_chunks_to_wav,
        mulaw_duration_seconds,
    )
except ImportError:
    pass  # pydub/ffmpeg may not be installed in all environments
