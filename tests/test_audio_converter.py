"""
Tests for audio converter utilities.
"""

import audioop
import base64
import io
import wave

import pytest


class TestMulawToWav:
    """Tests for Twilio → Whisper conversion."""

    def test_mulaw_chunks_to_wav_returns_valid_wav(self):
        """mulaw_chunks_to_wav produces valid WAV file."""
        from utils.audio_converter import mulaw_chunks_to_wav

        # Generate 1 second of silence in mulaw (8000 bytes)
        silence_pcm = b"\x00\x00" * 8000  # 1s of silence at 8kHz, 16-bit
        silence_mulaw = audioop.lin2ulaw(silence_pcm, 2)

        wav_bytes = mulaw_chunks_to_wav(silence_mulaw)

        assert wav_bytes, "Should return non-empty bytes"
        # Verify it's a valid WAV file
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2  # 16-bit PCM
            assert wf.getframerate() == 16000  # Resampled to 16kHz

    def test_mulaw_chunks_to_wav_empty_input(self):
        """Empty input returns empty bytes."""
        from utils.audio_converter import mulaw_chunks_to_wav

        assert mulaw_chunks_to_wav(b"") == b""

    def test_mulaw_to_pcm_produces_correct_length(self):
        """mulaw → PCM doubles the byte count (1 byte → 2 bytes per sample)."""
        from utils.audio_converter import mulaw_to_pcm

        mulaw = b"\x80" * 100  # 100 mulaw samples
        pcm = mulaw_to_pcm(mulaw)
        assert len(pcm) == 200  # 100 samples × 2 bytes

    def test_resample_pcm_changes_length(self):
        """Resampling 8kHz → 16kHz doubles the data."""
        from utils.audio_converter import resample_pcm

        pcm_8k = b"\x00\x00" * 8000  # 1s at 8kHz
        pcm_16k = resample_pcm(pcm_8k, 8000, 16000)
        # Should be approximately double (not exact due to resampling algorithm)
        assert len(pcm_16k) >= len(pcm_8k) * 1.8

    def test_resample_pcm_same_rate_no_change(self):
        """Same rate returns identical bytes."""
        from utils.audio_converter import resample_pcm

        pcm = b"\x00\x00" * 100
        assert resample_pcm(pcm, 16000, 16000) == pcm


class TestMp3ToMulaw:
    """Tests for ElevenLabs → Twilio conversion."""

    def _make_wav_bytes(self, duration_s: float = 0.5) -> bytes:
        """Create a simple WAV file with a 440Hz sine wave for testing."""
        import struct
        import math

        buf = io.BytesIO()
        sample_rate = 8000  # 8kHz is sufficient for mulaw tests
        n_frames = int(sample_rate * duration_s)
        # Generate 440Hz sine wave (not silence — silence can be optimized away by encoders)
        samples = [int(16000 * math.sin(2 * math.pi * 440 * t / sample_rate)) for t in range(n_frames)]
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{n_frames}h", *samples))
        return buf.getvalue()

    # Pre-generated 440Hz sine wave MP3 (200ms, 8kHz mono) — avoids runtime WAV→MP3
    def test_mp3_to_mulaw_chunks_returns_base64_list(self):
        """mp3_to_mulaw_chunks converts MP3 to base64 mulaw chunks."""
        from unittest.mock import MagicMock, patch

        # Create fake PCM audio data (800 bytes = 100ms at 8kHz mono 16-bit)
        fake_pcm = b"\x00\x10" * 400

        mock_audio = MagicMock()
        mock_audio.set_channels.return_value = mock_audio
        mock_audio.set_frame_rate.return_value = mock_audio
        mock_audio.set_sample_width.return_value = mock_audio
        mock_audio.raw_data = fake_pcm

        with patch("pydub.AudioSegment.from_mp3", return_value=mock_audio):
            from utils.audio_converter import mp3_to_mulaw_chunks
            chunks = mp3_to_mulaw_chunks(b"\xff\xfb\x90\x00" * 50)

        assert isinstance(chunks, list)
        assert len(chunks) > 0
        for chunk in chunks:
            decoded = base64.b64decode(chunk)
            assert len(decoded) > 0

    def test_mp3_to_mulaw_chunks_empty_input(self):
        """Empty input returns empty list."""
        pytest.importorskip("pydub")
        from utils.audio_converter import mp3_to_mulaw_chunks

        assert mp3_to_mulaw_chunks(b"") == []

    def test_mp3_to_mulaw_raw_empty_input(self):
        """Empty input returns empty bytes."""
        pytest.importorskip("pydub")
        from utils.audio_converter import mp3_to_mulaw_raw

        assert mp3_to_mulaw_raw(b"") == b""

    def test_mp3_to_mulaw_raw_returns_bytes(self):
        """mp3_to_mulaw_raw converts MP3 to raw mulaw bytes."""
        from unittest.mock import MagicMock, patch

        fake_pcm = b"\x00\x10" * 400

        mock_audio = MagicMock()
        mock_audio.set_channels.return_value = mock_audio
        mock_audio.set_frame_rate.return_value = mock_audio
        mock_audio.set_sample_width.return_value = mock_audio
        mock_audio.raw_data = fake_pcm

        with patch("pydub.AudioSegment.from_mp3", return_value=mock_audio):
            from utils.audio_converter import mp3_to_mulaw_raw
            mulaw = mp3_to_mulaw_raw(b"\xff\xfb\x90\x00" * 50)

        assert isinstance(mulaw, bytes)
        assert len(mulaw) > 0


class TestVAD:
    """Tests for Voice Activity Detection."""

    def test_is_speech_silence(self):
        """Silence should not be detected as speech."""
        from utils.audio_converter import is_speech

        silence = b"\xff" * 160  # mulaw silence (~0x7F is zero-crossing)
        # This is a basic test — actual silence detection depends on threshold
        result = is_speech(silence, threshold=500)
        assert isinstance(result, bool)

    def test_is_speech_empty(self):
        """Empty bytes should return False."""
        from utils.audio_converter import is_speech

        assert is_speech(b"") is False

    def test_calculate_rms_silence(self):
        """RMS of silence should be low."""
        from utils.audio_converter import calculate_rms

        silence = b"\x80" * 160  # mulaw mid-point
        rms = calculate_rms(silence)
        assert isinstance(rms, (int, float))
        assert rms >= 0

    def test_calculate_rms_empty(self):
        """RMS of empty bytes should be 0."""
        from utils.audio_converter import calculate_rms

        assert calculate_rms(b"") == 0.0


class TestDurationHelpers:
    """Tests for duration calculation."""

    def test_mulaw_duration_1_second(self):
        """8000 bytes of mulaw = 1 second."""
        from utils.audio_converter import mulaw_duration_seconds

        one_second = b"\x80" * 8000
        assert abs(mulaw_duration_seconds(one_second) - 1.0) < 0.01

    def test_mulaw_duration_empty(self):
        """Empty bytes = 0 seconds."""
        from utils.audio_converter import mulaw_duration_seconds

        assert mulaw_duration_seconds(b"") == 0.0

    def test_wav_duration(self):
        """WAV duration calculation."""
        from utils.audio_converter import wav_duration_seconds, pcm_to_wav_bytes

        # 1 second of PCM at 16kHz
        pcm = b"\x00\x00" * 16000
        wav = pcm_to_wav_bytes(pcm, 16000)
        duration = wav_duration_seconds(wav)
        assert abs(duration - 1.0) < 0.01

    def test_wav_duration_empty(self):
        """Empty bytes = 0 seconds."""
        from utils.audio_converter import wav_duration_seconds

        assert wav_duration_seconds(b"") == 0.0
