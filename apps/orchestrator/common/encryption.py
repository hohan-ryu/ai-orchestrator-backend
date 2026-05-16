"""
Fernet 기반 대칭키 암호화 유틸리티.

사용법:
    from apps.orchestrator.common.encryption import encrypt, decrypt, generate_key

    key = generate_key()          # 새 키 생성 (최초 1회, .env에 저장)
    cipher = encrypt("secret")    # 암호화 → base64 문자열
    plain  = decrypt(cipher)      # 복호화 → 원문 문자열

암호화 키는 Settings.encryption_key 에서 읽습니다.
값이 비어 있으면 암호화/복호화를 건너뛰고 원문을 그대로 반환합니다.
"""

import base64
import logging

logger = logging.getLogger(__name__)


def generate_key() -> str:
    """새 Fernet 키를 생성하여 base64 문자열로 반환합니다."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def _get_fernet():
    from apps.orchestrator.common.config import get_settings
    key = get_settings().encryption_key
    if not key:
        return None
    from cryptography.fernet import Fernet
    raw = key.encode() if isinstance(key, str) else key
    # 32-byte URL-safe base64 키가 아니면 SHA-256으로 파생
    try:
        return Fernet(raw)
    except Exception:
        import hashlib
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    """문자열을 암호화합니다. 키 미설정 시 원문 반환."""
    f = _get_fernet()
    if f is None:
        return plaintext
    try:
        return f.encrypt(plaintext.encode()).decode()
    except Exception as e:
        logger.warning("[Encryption] 암호화 실패: %s", e)
        return plaintext


def decrypt(ciphertext: str) -> str:
    """암호화된 문자열을 복호화합니다. 키 미설정 또는 실패 시 원문 반환."""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception as e:
        logger.warning("[Encryption] 복호화 실패 (원문 반환): %s", e)
        return ciphertext
