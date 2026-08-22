import pytest
from cryptography.fernet import Fernet

from mail_bot.security import TokenCipher


def test_token_cipher_round_trip() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("refresh-token")
    assert encrypted != "refresh-token"
    assert cipher.decrypt(encrypted) == "refresh-token"


def test_token_cipher_requires_key() -> None:
    with pytest.raises(ValueError):
        TokenCipher("")
