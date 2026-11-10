"""엑셀 내려받기 응답(분석 결과·결재 대장): 파일 이름 머리글과 내보낸 시각.

파일 이름은 한글 이름(RFC 5987 filename*)과 영문 대체 이름(filename)을 함께 단다 — 화면은 한글 이름을 쓰고, 한글을
모르는 도구는 대체 이름을 쓴다. 이름에 넣는 설계변경 번호는 글자·숫자·'.-_'만 남긴다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import Response

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KST = timezone(timedelta(hours=9))  # 서머타임 없음
_UNSAFE = re.compile(r"[^0-9A-Za-z._-]+")


def safe_part(text: str) -> str:
    """파일 이름 조각: 허용 글자 밖은 '_'로, 비면 'ECN'."""
    return _UNSAFE.sub("_", text).strip("_") or "ECN"


def exported_at(now: datetime) -> str:
    """내보낸 시각(한국 시간, 분까지)."""
    return now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def xlsx_response(body: bytes, *, name: str, fallback: str) -> Response:
    disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"
    return Response(content=body, media_type=XLSX, headers={"Content-Disposition": disposition})
