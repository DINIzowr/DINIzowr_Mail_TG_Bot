from cryptography.fernet import Fernet


class TokenCipher:
    def __init__(self, key: str):
        if not key:
            raise ValueError("ENCRYPTION_KEY must be set")
        self._cipher = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._cipher.decrypt(value.encode()).decode()
