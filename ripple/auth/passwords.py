"""비밀번호 해시·검증·규칙·임시 비밀번호(표준 라이브러리만).

해시 형식: `scrypt$<N>$<r>$<p>$<솔트 b64>$<해시 b64>` — 매개변수를 함께 적어 나중에 올려도 옛 해시를 검증할 수 있다.
N=2^15·r=8이면 작업 메모리만 32MiB라 OpenSSL 기본 상한(32MiB)을 넘는다 → maxmem을 생성·검증·가짜 해시 모두에 명시한다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import cache

from ripple.contracts.auth import PASSWORD_MAX, PASSWORD_MIN

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16
KEY_BYTES = 32
# 헷갈리는 글자(0·O·o, 1·l·I)를 뺀 임시 비밀번호 글자
TEMPORARY_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TEMPORARY_LENGTH = 12
# 길이 기준을 넘어도 받지 않는 흔한 비밀번호(소문자로 비교)
COMMON = frozenset(
    {
        "1234567890",
        "12345678910",
        "0123456789",
        "1111111111",
        "qwertyuiop",
        "1q2w3e4r5t",
        "password12",
        "password123",
        "password1234",
        "passw0rd12",
        "abcdefghij",
        "abcd123456",
        "ripple1234",
        "ripple12345",
        "admin12345",
        "admin123456",
    }
)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    """형식이 틀린 해시는 False(예외를 내지 않음). 비교는 상수 시간."""
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
    except ValueError:
        return False
    if n != SCRYPT_N or r != SCRYPT_R or p != SCRYPT_P or len(expected) != KEY_BYTES:
        return False  # 지금 쓰지 않는 매개변수(올리면 여기서 옛 값을 함께 받는다)
    return hmac.compare_digest(_scrypt(password, salt, n, r, p), expected)


def burn_time(password: str) -> None:
    """없는 계정도 같은 계산을 해서 응답 시간으로 계정이 있는지 알 수 없게 한다."""
    verify_password(password, _dummy_hash())


def password_problem(password: str, login_id: str) -> str | None:
    """새 비밀번호 규칙. 문제가 없으면 None, 있으면 합니다체 이유."""
    if len(password) < PASSWORD_MIN:
        return f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다"
    if len(password) > PASSWORD_MAX:
        return f"비밀번호는 {PASSWORD_MAX}자 이하여야 합니다"
    if password.strip() != password:
        return "비밀번호 앞뒤에는 공백을 넣을 수 없습니다"
    lowered = password.lower()
    own = login_id.lower()
    if own and own in lowered and len(lowered) - len(own) < 4:  # 아이디 그대로이거나 아이디 + 짧은 덧붙임
        return "아이디가 포함된 비밀번호는 사용할 수 없습니다"
    if len(set(password)) < 4:
        return "같은 글자를 반복한 비밀번호는 사용할 수 없습니다"
    if lowered in COMMON:
        return "흔히 쓰는 비밀번호는 사용할 수 없습니다. 다른 비밀번호를 정해 주십시오"
    return None


def temporary_password() -> str:
    """관리자가 구성원에게 전할 임시 비밀번호(12자, 약 69비트). 첫 로그인 때 바꾸게 한다."""
    while True:
        candidate = "".join(secrets.choice(TEMPORARY_ALPHABET) for _ in range(TEMPORARY_LENGTH))
        if any(ch.isdigit() for ch in candidate) and any(ch.isalpha() for ch in candidate):
            return candidate


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=KEY_BYTES)


@cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")
