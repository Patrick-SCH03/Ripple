"""로그인·세션·구성원 관리(docs/operations.md(서비스) 2절). 비밀번호는 표준 라이브러리 scrypt, 세션은 서버 쪽."""

from .principal import DEMO_ID, DEV_PRINCIPAL, AuthError, Principal, normalize_id
from .service import AuthService

__all__ = ["DEMO_ID", "DEV_PRINCIPAL", "AuthError", "AuthService", "Principal", "normalize_id"]
