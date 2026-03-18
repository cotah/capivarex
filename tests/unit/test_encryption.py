"""Unit tests for encryption utilities."""

import os
import pytest
from unittest.mock import patch

from cryptography.fernet import Fernet


class TestEncryptionService:
    @pytest.fixture(autouse=True)
    def _set_encryption_key(self):
        """Provide a valid Fernet key for testing."""
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}):
            # Re-import to pick up the new key
            import importlib
            import utils.encryption as enc_mod

            importlib.reload(enc_mod)
            self.enc = enc_mod
            yield

    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "my-secret-token-12345"
        encrypted = self.enc.encrypt_token(plaintext)
        assert encrypted != plaintext
        decrypted = self.enc.decrypt_token(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertexts(self):
        """Fernet uses random IV, so two encryptions differ."""
        a = self.enc.encrypt_token("same")
        b = self.enc.encrypt_token("same")
        assert a != b

    def test_decrypt_invalid_ciphertext_raises(self):
        with pytest.raises(Exception):
            self.enc.decrypt_token("not-valid-base64-ciphertext")

    def test_generate_key(self):
        key = self.enc.EncryptionService.generate_key()
        assert isinstance(key, str)
        assert len(key) > 20
        # Should be a valid Fernet key
        Fernet(key.encode())
