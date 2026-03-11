"""Tests for utils/encryption.py – covers error branches."""

import pytest
from unittest.mock import patch


class TestEncryptionServiceInit:
    """Test EncryptionService initialization edge cases."""

    def test_init_without_encryption_key_raises(self):
        """When ENCRYPTION_KEY is missing, RuntimeError is raised."""
        with patch.dict("os.environ", {}, clear=True):
            from utils.encryption import EncryptionService

            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
                EncryptionService()

    def test_init_with_invalid_key_raises(self):
        """An invalid key should raise during Fernet init."""
        with patch.dict("os.environ", {"ENCRYPTION_KEY": "not-valid-base64!"}):
            from utils.encryption import EncryptionService

            with pytest.raises(Exception):
                EncryptionService()

    def test_encrypt_and_decrypt_roundtrip(self):
        """Encrypt then decrypt should return original text."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": key}):
            from utils.encryption import EncryptionService

            svc = EncryptionService()
            ct = svc.encrypt("hello")
            assert svc.decrypt(ct) == "hello"

    def test_encrypt_error_path(self):
        """When cipher is broken, encrypt should raise."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": key}):
            from utils.encryption import EncryptionService

            svc = EncryptionService()
            svc.cipher = None  # break it
            with pytest.raises(Exception):
                svc.encrypt("boom")

    def test_decrypt_error_path(self):
        """Decrypting invalid ciphertext should raise."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": key}):
            from utils.encryption import EncryptionService

            svc = EncryptionService()
            with pytest.raises(Exception):
                svc.decrypt("not-valid-ciphertext")

    def test_generate_key_returns_string(self):
        """generate_key should return a valid Fernet key string."""
        from utils.encryption import EncryptionService

        key = EncryptionService.generate_key()
        assert isinstance(key, str)
        assert len(key) > 0
