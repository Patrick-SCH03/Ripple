"""파일 바꿔 끼우기(ripple/config/files.py replace_file)의 성질 — Windows의 짧은 잠금(백신·색인이 새 파일을
잠깐 여는 것) 때문에 os.replace가 PermissionError(WinError 5)로 실패하던 버그(세션 파일, 검사에서 3번 재현).

- PermissionError가 처음 n번 나면 기다렸다 다시 해서 됨(기다림은 10ms부터 두 배씩, 한 번 160ms까지, 합 1초 안).
- 한도(10번)를 넘으면 마지막 PermissionError 그대로 · 다른 OSError는 다시 하지 않음.
- 원자적 쓰기(write_atomic): 다시 시도로 되면 새 내용, 끝내 안 되면 원래 파일 그대로 + 임시 파일 정리.
- 외부 AI 사용량 장부(ripple/llm/quota.py)도 write_atomic: 바꿔 끼우기가 끝내 안 되면 그 호출을 부르지 않고(세지도
  않음) 임시 파일이 남지 않으며 장부는 그대로.
- 저장소·사용량 장부의 바꿔 끼우기는 모두 이 함수를 거친다(코드에 os.replace를 직접 부르는 곳이 없음).
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from harness import Checker

from ripple.config.files import ATTEMPTS, MAX_WAIT_S, replace_file, write_atomic
from ripple.config.settings import PROJECT_ROOT
from ripple.llm.base import LlmUnavailable
from ripple.llm.quota import QuotaLimits, UsageLedger
from ripple.store import snapshots

REAL_REPLACE = os.replace


def _flaky(failures: int, error: OSError | None = None) -> tuple[Callable[..., None], list[int]]:
    """처음 failures번은 실패하고(기본 PermissionError WinError 5) 그 뒤는 진짜 os.replace인 가짜와 부른 횟수."""
    calls: list[int] = []

    def replace(source: Any, target: Any) -> None:
        calls.append(1)
        if len(calls) <= failures:
            raise error or PermissionError(13, "액세스가 거부되었습니다", str(target), 5)
        REAL_REPLACE(source, target)

    return replace, calls


def run(c: Checker) -> None:
    c.section("파일 바꿔 끼우기: Windows 짧은 잠금에 다시 시도(replace_file)")
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        _retry(c, root)
        (root / "atomic").mkdir()
        _atomic(c, root / "atomic")
        (root / "quota").mkdir()
        _usage_ledger(c, root / "quota")
    _callers(c)


def _retry(c: Checker, root: Path) -> None:
    waits: list[float] = []
    source, target = root / "a.tmp", root / "a.json"
    source.write_text("새", encoding="utf-8")
    target.write_text("옛", encoding="utf-8")
    fake, calls = _flaky(3)
    with mock.patch("os.replace", fake):
        replace_file(source, target, sleep=waits.append)
    c.check(
        "PermissionError 3번 뒤 4번째에 바꿔 끼움 · 기다림 10·20·40ms · 원본 자리는 비고 대상은 새 내용",
        len(calls) == 4
        and waits == [0.01, 0.02, 0.04]
        and not source.exists()
        and target.read_text(encoding="utf-8") == "새",
        (len(calls), waits),
    )
    waits.clear()
    source.write_text("새2", encoding="utf-8")
    fake, calls = _flaky(ATTEMPTS + 5)
    refused: BaseException | None = None
    with mock.patch("os.replace", fake):
        try:
            replace_file(source, target, sleep=waits.append)
        except PermissionError as error:
            refused = error
    c.check(
        f"한도({ATTEMPTS}번)를 넘으면 PermissionError 그대로 · 한 번 기다림 ≤ {MAX_WAIT_S}s · 합 1초 안 · "
        "대상은 그대로",
        isinstance(refused, PermissionError)
        and len(calls) == ATTEMPTS
        and len(waits) == ATTEMPTS - 1
        and max(waits) <= MAX_WAIT_S
        and sum(waits) <= 1.0
        and target.read_text(encoding="utf-8") == "새",
        (len(calls), waits),
    )
    fake, calls = _flaky(1, FileNotFoundError(2, "없음"))
    missing: BaseException | None = None
    with mock.patch("os.replace", fake):
        try:
            replace_file(root / "none.tmp", target, sleep=waits.append)
        except FileNotFoundError as error:
            missing = error
    c.check(
        "다른 OSError(없는 파일)는 다시 하지 않고 바로 그대로",
        isinstance(missing, FileNotFoundError) and len(calls) == 1,
    )


def _leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name.endswith(".tmp"))


def _atomic(c: Checker, root: Path) -> None:
    path = root / "sessions.json"
    write_atomic(path, '{"version": 1}')
    fake, calls = _flaky(2)
    with mock.patch("os.replace", fake), mock.patch("time.sleep", lambda _s: None):
        write_atomic(path, '{"version": 2}')
    c.check(
        "원자적 쓰기: 잠금 2번 뒤 바꿔 끼움 → 새 내용, 임시 파일 없음",
        len(calls) == 3 and path.read_text(encoding="utf-8") == '{"version": 2}' and _leftovers(root) == [],
        _leftovers(root),
    )
    fake, calls = _flaky(ATTEMPTS * 2)
    failed = False
    with mock.patch("os.replace", fake), mock.patch("time.sleep", lambda _s: None):
        try:
            write_atomic(path, '{"version": 3}')
        except PermissionError:
            failed = True
    c.check(
        "원자적 쓰기: 끝내 잠겨 있으면 PermissionError · 원래 파일 그대로 · 임시 파일은 지움",
        failed and path.read_text(encoding="utf-8") == '{"version": 2}' and _leftovers(root) == [],
        (failed, _leftovers(root)),
    )


def _usage_ledger(c: Checker, root: Path) -> None:
    ledger = UsageLedger(root / "llm_usage.json", QuotaLimits(daily_total=10, daily_per_account=5))
    first = ledger.reserve("kim")
    kept = (root / "llm_usage.json").read_text(encoding="utf-8")
    fake, calls = _flaky(ATTEMPTS * 2)
    refused = False
    with mock.patch("os.replace", fake), mock.patch("time.sleep", lambda _s: None):
        try:
            ledger.reserve("kim")
        except LlmUnavailable:
            refused = True
    c.check(
        "사용량 장부: 바꿔 끼우기가 끝내 안 되면 그 호출은 부르지 않음(LlmUnavailable) · 장부·메모리 수 그대로 · "
        "임시 파일 없음 · 저장소 쪽 write_atomic과 같은 함수",
        first
        and refused
        and len(calls) == ATTEMPTS
        and (root / "llm_usage.json").read_text(encoding="utf-8") == kept
        and ledger.snapshot()[1] == 1
        and _leftovers(root) == []
        and snapshots.write_atomic is write_atomic,
        (refused, _leftovers(root)),
    )


def _callers(c: Checker) -> None:
    raw = [
        f"{path.relative_to(PROJECT_ROOT)}:{n}"
        for path in sorted((PROJECT_ROOT / "ripple").rglob("*.py"))
        if path.name != "files.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"\bos\.(replace|rename)\(", line)
    ]
    c.check("저장소·사용량 장부의 바꿔 끼우기는 모두 replace_file(os.replace·os.rename 직접 부름 없음)", not raw, raw)
