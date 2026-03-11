"""
Encryption utilities for sensitive data storage.
Uses Fernet (symmetric encryption) from cryptography library.
"""

import os

from cryptography.fernet import Fernet
from loguru import logger


class EncryptionService:
    """
    Service for encrypting/decrypting sensitive data (OAuth tokens).

    Uses Fernet symmetric encryption with a key from environment variables.
    """

    def __init__(self):
        """Initialize encryption service with key from environment."""
        encryption_key = os.getenv("ENCRYPTION_KEY")

        if not encryption_key:
            _is_safe_env = (
                os.getenv("CI")
                or os.getenv("PYTEST_CURRENT_TEST")
                or os.getenv("ENVIRONMENT") in ("testing", "test", "development")
            )
            if _is_safe_env:
                logger.warning(
                    "ENCRYPTION_KEY not set — generating temporary key "
                    "(safe: CI/test/development environment detected)"
                )
                encryption_key = Fernet.generate_key().decode()
            else:
                raise RuntimeError(
                    "CRITICAL: ENCRYPTION_KEY not set in environment variables. "
                    "All previously encrypted OAuth tokens would be irrecoverable. "
                    "Generate a key with: python -c "
                    '"from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())" '
                    "and set it as ENCRYPTION_KEY in your environment."
                )

        try:
            self.cipher = Fernet(encryption_key.encode())
            logger.info("Encryption service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize encryption: {e}")
            raise

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        try:
            encrypted = self.cipher.encrypt(plaintext.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a string.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string
        """
        try:
            decrypted = self.cipher.decrypt(ciphertext.encode())
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet encryption key.

        Returns:
            Base64-encoded encryption key
        """
        return Fernet.generate_key().decode()


# Global instance
encryption_service = EncryptionService()


def encrypt_token(token: str) -> str:
    """Encrypt a token."""
    return encryption_service.encrypt(token)


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt a token."""
    return encryption_service.decrypt(encrypted_token)
