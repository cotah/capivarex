"""
Tests for _extract_speech_text() — the FIX [2026-02] that prevents
the VoiceAgent from TTS-reading the entire command instead of just
the intended speech content.
"""

import pytest
from agents.specialized.voice_agent import _extract_speech_text


class TestExtractSpeechText:
    """Core extraction: PT commands with 'dizendo', 'falando', etc."""

    def test_dizendo(self):
        assert (
            _extract_speech_text("me manda um audio dizendo Eu te amo") == "Eu te amo"
        )

    def test_dizendo_caps(self):
        assert _extract_speech_text("Manda um áudio DIZENDO Bom dia") == "Bom dia"

    def test_falando(self):
        assert (
            _extract_speech_text("faz um audio falando bom dia amor") == "bom dia amor"
        )

    def test_que_diz(self):
        assert _extract_speech_text("manda audio que diz olá mundo") == "olá mundo"

    def test_que_diga(self):
        assert (
            _extract_speech_text("cria um audio que diga feliz aniversário")
            == "feliz aniversário"
        )

    def test_com_o_texto(self):
        assert (
            _extract_speech_text("gera audio com o texto boas festas") == "boas festas"
        )

    def test_com_texto(self):
        assert _extract_speech_text("faz um áudio com texto boa noite") == "boa noite"

    def test_com_a_frase(self):
        assert (
            _extract_speech_text("manda audio com a frase estou a chegar")
            == "estou a chegar"
        )

    def test_com_a_mensagem(self):
        assert (
            _extract_speech_text("envia audio com a mensagem já estou a caminho")
            == "já estou a caminho"
        )

    def test_a_dizer(self):
        assert _extract_speech_text("manda um audio a dizer bom dia") == "bom dia"


class TestExtractEnglish:
    """EN commands with 'saying', 'that says', etc."""

    def test_saying(self):
        assert _extract_speech_text("send an audio saying hello world") == "hello world"

    def test_that_says(self):
        assert _extract_speech_text("make a voice that says I love you") == "I love you"

    def test_with_text(self):
        assert (
            _extract_speech_text("create audio with text good morning")
            == "good morning"
        )

    def test_with_the_message(self):
        assert (
            _extract_speech_text("generate audio with the message see you later")
            == "see you later"
        )


class TestExtractQuotes:
    """Quoted text in commands."""

    def test_single_quotes(self):
        assert _extract_speech_text("manda audio 'Eu te amo'") == "Eu te amo"

    def test_double_quotes(self):
        assert _extract_speech_text('manda audio "Eu te amo"') == "Eu te amo"


class TestNotVoiceCommand:
    """When the prompt is NOT a voice command — return as-is."""

    def test_raw_text(self):
        """Raw text passed directly to TTS (e.g., from context or another agent)."""
        assert _extract_speech_text("Eu te amo") == "Eu te amo"

    def test_plain_sentence(self):
        assert _extract_speech_text("Bom dia, como estás?") == "Bom dia, como estás?"

    def test_long_text(self):
        text = (
            "Este é um texto longo que foi gerado por outro agent e precisa ser lido."
        )
        assert _extract_speech_text(text) == text

    def test_empty(self):
        assert _extract_speech_text("") == ""


class TestEdgeCases:
    """Edge cases and tricky inputs."""

    def test_multiline_text_after_dizendo(self):
        result = _extract_speech_text("manda um audio dizendo olá\ncomo estás?")
        assert "olá" in result
        assert "como estás?" in result

    def test_trailing_period_stripped(self):
        result = _extract_speech_text("manda audio dizendo Eu te amo.")
        assert result == "Eu te amo"

    def test_preserves_exclamation(self):
        result = _extract_speech_text("manda audio dizendo Eu te amo!")
        assert result == "Eu te amo!"

    def test_accented_audio(self):
        assert _extract_speech_text("manda um áudio dizendo olá") == "olá"

    def test_envia_variant(self):
        assert _extract_speech_text("envia um audio dizendo tchau") == "tchau"

    def test_gera_variant(self):
        assert _extract_speech_text("gera um audio dizendo até logo") == "até logo"

    def test_cria_variant(self):
        assert _extract_speech_text("cria um audio dizendo obrigado") == "obrigado"

    def test_produz_variant(self):
        assert _extract_speech_text("produz audio dizendo parabéns") == "parabéns"

    def test_faz_variant(self):
        assert _extract_speech_text("faz um audio dizendo boa sorte") == "boa sorte"


class TestVoiceCommandDetection:
    """Ensure _IS_VOICE_COMMAND correctly identifies voice commands."""

    def test_manda_audio(self):
        result = _extract_speech_text("manda um audio dizendo oi")
        assert result == "oi"

    def test_generate_voice(self):
        result = _extract_speech_text("generate a voice saying hi there")
        assert result == "hi there"

    def test_not_a_command(self):
        """Should not try to extract from non-voice-command text."""
        text = "dizendo verdades sobre a vida"
        assert _extract_speech_text(text) == text  # not a voice command


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
