"""덧붙이기만 하는 기록 파일(수정 기록·실적·상태 갱신)의 연결: 폴더가 없으면 만들고, 표가 없으면 만든다."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(schema)
    except BaseException:
        connection.close()  # 열린 채 남으면 Windows에서 기록 바꿔 끼우기(os.replace)를 막는다
        raise
    return connection
