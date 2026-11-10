"""파일 바꿔 끼우기(원자적 교체)의 한 입구: os.replace를 Windows의 짧은 잠금에 견디게 감싼다.

Windows에서는 바꿔 끼울 파일(대상)이나 방금 쓴 임시 파일(원본)을 다른 프로세스가 공유 삭제 없이 열어 두면
— 백신(실시간 검사)·검색 색인처럼 새로 생긴 파일을 잠깐 여는 프로그램 — os.replace가 PermissionError
(WinError 5 접근 거부·32 공유 위반)로 실패한다. 잠깐 뒤 다시 하면 대개 된다.

그래서 PermissionError일 때만 짧게 다시 해 보고(10·20·40·80·160ms…, 한 번 기다림은 160ms까지, 모두 합쳐 1초 안),
그래도 안 되면 마지막 PermissionError를 그대로 낸다(호출자가 임시 파일을 지우고 원래 파일은 그대로 둔다).
다른 OSError(없는 파일·다른 볼륨 등)는 다시 하지 않는다 — 기다려도 바뀌지 않는 실패다.

저장소(ripple/store: 지도·계정·세션·열 매핑·기록 비우기)와 외부 AI 사용량 장부(ripple/llm/quota.py)가 모두 이 함수로
바꿔 끼운다. 글 파일 한 개를 통째로 쓰는 곳은 write_atomic(같은 폴더의 고유한 임시 파일 → 디스크에 내림 → 바꿔
끼우기 → 실패해도 임시 파일은 지움)을 쓴다.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

ATTEMPTS = 10  # 처음 1번 + 다시 9번
FIRST_WAIT_S = 0.01
MAX_WAIT_S = 0.16  # 기다림 합 = 10+20+40+80+160×5 ms = 0.95초


def replace_file(
    source: str | os.PathLike[str] | Path,
    target: str | os.PathLike[str] | Path,
    *,
    attempts: int = ATTEMPTS,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """source를 target 자리로 바꿔 끼운다(os.replace). PermissionError면 짧게 기다렸다 다시, 한도를 넘으면 마지막
    예외를 그대로 낸다."""
    wait = FIRST_WAIT_S
    for attempt in range(1, attempts + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            (sleep or time.sleep)(wait)  # 부를 때 찾는다(검사가 바꿔 끼울 수 있게)
            wait = min(wait * 2, MAX_WAIT_S)


def write_atomic(path: Path, text: str) -> None:
    """같은 폴더의 임시 파일(프로세스·호출마다 고유)에 쓰고 디스크에 내린 뒤 바꿔 끼운다. 실패하면 임시 파일을 지우고
    원래 파일은 그대로 둔다."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)  # Windows의 짧은 잠금(백신·색인)에 견디게
    finally:
        temporary.unlink(missing_ok=True)
