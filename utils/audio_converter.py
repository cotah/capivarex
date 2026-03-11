"""
utils/audio_converter.py
========================
Audio format conversion utilities for Twilio Media Streams.

Twilio Media Streams sends/receives: mulaw (µ-law), 8000 Hz, mono, base64
OpenAI Whisper expects:             PCM WAV, 16000 Hz, mono
ElevenLabs returns:                 MP3, 44100 Hz, stereo

This module handles all conversions between these formats.

Usage:
    from utils.audio_converter import (
        mulaw_chunks_to_wav,
        mp3_to_mulaw_chunks,
        pcm_to_wav_bytes,
    )

    # Twilio → Whisper
    wav_bytes = mulaw_chunks_to_wav(accumulated_mulaw_bytes)

    # ElevenLabs → Twilio
    mulaw_b64_chunks = mp3_to_mulaw_chunks(mp3_bytes)
"""

import audioop
import base64
import io
import logging
import wave
from typing import List

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────
TWILIO_SAMPLE_RATE = 8000  # Twilio Media Streams: 8kHz
WHISPER_SAMPLE_RATE = 16000  # Whisper prefers 16kHz
MULAW_SAMPLE_WIDTH = 1  # µ-law = 1 byte per sample
PCM_SAMPLE_WIDTH = 2  # PCM 16-bit = 2 bytes per sample
CHANNELS = 1  # Mono

# Twilio sends ~20ms chunks = 160 samples at 8kHz = 160 bytes mulaw
TWILIO_CHUNK_SIZE = 160

# Max payload size for Twilio media message (~32KB recommended)
TWILIO_MAX_PAYLOAD_SIZE = 32_000


# ── Twilio → Whisper ──────────────────────────────────────────────────────


def mulaw_to_pcm(mulaw_bytes: bytes) -> bytes:
    """
    Convert µ-law audio to PCM 16-bit linear.

    Args:
        mulaw_bytes: Raw µ-law encoded audio bytes

    Returns:
        PCM 16-bit linear audio bytes
    """
    return audioop.ulaw2lin(mulaw_bytes, PCM_SAMPLE_WIDTH)


def resample_pcm(pcm_bytes: bytes, from_rate: int, to_rate: int) -> bytes:
    """
    Resample PCM audio from one sample rate to another.

    Args:
        pcm_bytes: PCM 16-bit audio bytes
        from_rate: Source sample rate (e.g., 8000)
        to_rate: Target sample rate (e.g., 16000)

    Returns:
        Resampled PCM bytes
    """
    if from_rate == to_rate:
        return pcm_bytes
    resampled, _ = audioop.ratecv(
        pcm_bytes, PCM_SAMPLE_WIDTH, CHANNELS, from_rate, to_rate, None
    )
    return resampled


def pcm_to_wav_bytes(
    pcm_bytes: bytes, sample_rate: int = WHISPER_SAMPLE_RATE
) -> bytes:
    """
    Wrap PCM data in a WAV container.

    Args:
        pcm_bytes: Raw PCM 16-bit audio
        sample_rate: Sample rate of the PCM data

    Returns:
        Complete WAV file as bytes (ready for Whisper)
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(PCM_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def mulaw_chunks_to_wav(mulaw_bytes: bytes) -> bytes:
    """
    Convert accumulated µ-law audio (from Twilio) to WAV (for Whisper).

    This is the main function for Twilio → Whisper conversion.

    Pipeline: mulaw 8kHz → PCM 16-bit 8kHz → PCM 16-bit 16kHz → WAV

    Args:
        mulaw_bytes: Accumulated µ-law bytes from Twilio Media Streams

    Returns:
        WAV file bytes ready for Whisper STT
    """
    if not mulaw_bytes:
        return b""

    # Step 1: µ-law → PCM 16-bit
    pcm_8k = mulaw_to_pcm(mulaw_bytes)

    # Step 2: Resample 8kHz → 16kHz (Whisper prefers 16kHz)
    pcm_16k = resample_pcm(pcm_8k, TWILIO_SAMPLE_RATE, WHISPER_SAMPLE_RATE)

    # Step 3: Wrap in WAV container
    wav_bytes = pcm_to_wav_bytes(pcm_16k, WHISPER_SAMPLE_RATE)

    logger.debug(
        "mulaw→WAV: %d bytes mulaw → %d bytes WAV (%.1fs audio)",
        len(mulaw_bytes),
        len(wav_bytes),
        len(mulaw_bytes) / TWILIO_SAMPLE_RATE,
    )

    return wav_bytes


# ── ElevenLabs → Twilio ──────────────────────────────────────────────────


def mp3_to_mulaw_chunks(
    mp3_bytes: bytes, chunk_duration_ms: int = 20
) -> List[str]:
    """
    Convert MP3 audio (from ElevenLabs) to µ-law base64 chunks (for Twilio).

    This is the main function for ElevenLabs → Twilio conversion.

    Pipeline: MP3 → PCM (via pydub) → resample to 8kHz → µ-law → base64 chunks

    Args:
        mp3_bytes: MP3 audio bytes from ElevenLabs
        chunk_duration_ms: Duration of each chunk in ms (default: 20ms)

    Returns:
        List of base64-encoded µ-law chunks ready to send via Twilio WebSocket
    """
    from pydub import AudioSegment

    if not mp3_bytes:
        return []

    # Step 1: Decode MP3 → raw PCM
    audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))

    # Step 2: Convert to mono, 8kHz, 16-bit PCM
    audio = (
        audio.set_channels(CHANNELS)
        .set_frame_rate(TWILIO_SAMPLE_RATE)
        .set_sample_width(PCM_SAMPLE_WIDTH)
    )
    pcm_data = audio.raw_data

    # Step 3: PCM → µ-law
    mulaw_data = audioop.lin2ulaw(pcm_data, PCM_SAMPLE_WIDTH)

    # Step 4: Split into chunks and base64 encode
    # Each chunk = chunk_duration_ms worth of samples
    # At 8kHz, 20ms = 160 samples = 160 bytes (mulaw)
    samples_per_chunk = int(TWILIO_SAMPLE_RATE * chunk_duration_ms / 1000)
    chunks = []

    for i in range(0, len(mulaw_data), samples_per_chunk):
        chunk = mulaw_data[i : i + samples_per_chunk]
        if chunk:  # Don't send empty chunks
            chunks.append(base64.b64encode(chunk).decode("ascii"))

    logger.debug(
        "MP3→mulaw: %d bytes MP3 → %d chunks (%.1fs audio)",
        len(mp3_bytes),
        len(chunks),
        len(mulaw_data) / TWILIO_SAMPLE_RATE,
    )

    return chunks


def mp3_to_mulaw_raw(mp3_bytes: bytes) -> bytes:
    """
    Convert MP3 to raw µ-law bytes (without chunking).

    Useful when you need the complete mulaw audio, not chunked.

    Args:
        mp3_bytes: MP3 audio bytes

    Returns:
        Raw µ-law audio bytes
    """
    from pydub import AudioSegment

    if not mp3_bytes:
        return b""

    audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
    audio = (
        audio.set_channels(CHANNELS)
        .set_frame_rate(TWILIO_SAMPLE_RATE)
        .set_sample_width(PCM_SAMPLE_WIDTH)
    )
    pcm_data = audio.raw_data
    return audioop.lin2ulaw(pcm_data, PCM_SAMPLE_WIDTH)


# ── Voice Activity Detection (simple) ────────────────────────────────────


def calculate_rms(
    audio_bytes: bytes, sample_width: int = MULAW_SAMPLE_WIDTH
) -> float:
    """
    Calculate Root Mean Square (volume level) of audio.

    Used for simple Voice Activity Detection (VAD):
    - RMS > threshold → person is speaking
    - RMS < threshold for N seconds → person stopped speaking

    Args:
        audio_bytes: Audio bytes (mulaw or PCM)
        sample_width: Bytes per sample

    Returns:
        RMS value (0.0 = silence, higher = louder)
    """
    if not audio_bytes:
        return 0.0
    try:
        return audioop.rms(audio_bytes, sample_width)
    except audioop.error:
        return 0.0


def is_speech(mulaw_bytes: bytes, threshold: int = 50) -> bool:
    """
    Simple Voice Activity Detection for µ-law audio.

    Args:
        mulaw_bytes: µ-law audio chunk
        threshold: RMS threshold (default: 50, tune as needed)

    Returns:
        True if the chunk likely contains speech
    """
    # Convert to PCM first for better RMS calculation
    if not mulaw_bytes:
        return False
    pcm = audioop.ulaw2lin(mulaw_bytes, PCM_SAMPLE_WIDTH)
    rms = audioop.rms(pcm, PCM_SAMPLE_WIDTH)
    return rms > threshold


# ── Audio duration helpers ────────────────────────────────────────────────


def mulaw_duration_seconds(mulaw_bytes: bytes) -> float:
    """Calculate duration of µ-law audio in seconds."""
    if not mulaw_bytes:
        return 0.0
    return len(mulaw_bytes) / TWILIO_SAMPLE_RATE


def wav_duration_seconds(wav_bytes: bytes) -> float:
    """Calculate duration of WAV audio in seconds."""
    if not wav_bytes:
        return 0.0
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / rate
    except Exception:
        return 0.0
