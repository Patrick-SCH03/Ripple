"""레이어 규칙: 안쪽 레이어는 바깥을 모르고, 순수 계산 레이어는 I/O를 모른다(docs/architecture.md 1절)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from harness import Checker

from ripple.config.settings import PROJECT_ROOT

ALLOWED: dict[str, set[str]] = {
    "contracts": set(),
    "engine": {"contracts"},
    "decide": {"contracts"},
    "nl": {"contracts"},  # 규칙 기반 해석·값 정규화·후보(순수 계산)
    "explain": {"contracts"},  # 설명·알림 렌더러(순수 계산)
    "records": {"contracts"},  # ECN 상태 기계·감사 사슬(순수 계산, docs/records.md)
    "intake": {"contracts", "nl", "decide", "explain"},  # 문서 접수: 분할·항목·확정 검증(순수 계산, docs/input.md)
    "config": {"contracts"},
    "generator": {"contracts", "config"},  # 숨긴 실제 비용 모델이 엔진을 보면 안 된다
    "graph": {"contracts", "engine", "config"},
    "llm": {"contracts", "config"},
    "ingest": {"contracts", "engine", "decide", "config"},
    "store": {"contracts", "config", "records"},  # 기록 저장소는 상태 기계·감사 사슬을 트랜잭션 안에서 쓴다
    "auth": {"contracts", "config", "store"},  # 로그인·세션·구성원 관리
    "eval": {"contracts", "engine", "decide", "nl", "explain", "config", "generator", "graph", "store", "intake"},
    # 과거 사례: 합성 = 생성기 세계(재료·숨긴 실제 모델) + 엔진(예측), 실데이터 = 기록·실적 저장소(docs/records.md)
    "cases": {"contracts", "engine", "explain", "config", "generator", "records", "store"},
    "agent": {"contracts", "engine", "decide", "nl", "explain", "config", "graph", "llm", "ingest", "store", "intake"},
    "brief": {"contracts", "explain", "records", "llm"},  # 결정 도우미: 기록 본문 → 세 줄·확인할 것(AI는 고르기만)
    "api": {
        "contracts",
        "engine",
        "decide",
        "nl",
        "explain",
        "config",
        "generator",  # 실시간 시연 세계: 합성 기본 지도를 오늘 날짜로 만든다(ripple/api/live_world.py)
        "graph",
        "llm",
        "ingest",
        "store",
        "agent",
        "auth",
        "intake",
        "records",
        "brief",
        "cases",  # 결정 도우미의 과거 사례 선반(ripple/api/past_cases.py)
    },
}

PURE_LAYERS = {"contracts", "engine", "decide", "nl", "explain", "records", "intake"}
PURE_THIRD_PARTY = {"pydantic", "pydantic_core", "typing_extensions"}
PURE_STDLIB = {
    "__future__",
    "abc",
    "bisect",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "fractions",
    "functools",
    "hashlib",
    "heapq",
    "itertools",
    "json",
    "math",
    "operator",
    "re",
    "statistics",
    "string",
    "types",
    "typing",
    "unicodedata",
}


def run(c: Checker) -> None:
    c.section("레이어 규칙")
    package = PROJECT_ROOT / "ripple"
    layers = {p.name for p in package.iterdir() if (p / "__init__.py").exists()}
    c.check("모든 하위 패키지가 레이어 표에 있음", layers == set(ALLOWED), layers ^ set(ALLOWED))

    violations: list[str] = []
    impure: list[str] = []
    for path in sorted(package.rglob("*.py")):
        module = path.relative_to(PROJECT_ROOT).with_suffix("").parts
        layer = module[1] if len(module) > 2 else "root"
        for target, external in _imports(path, module):
            if external:
                if layer in PURE_LAYERS and target not in PURE_STDLIB | PURE_THIRD_PARTY:
                    impure.append(f"{'/'.join(module)} → {target}")
                if target in {"tests", "scripts"}:
                    violations.append(f"{'/'.join(module)} → {target}")
                continue
            if layer in ALLOWED and target not in {layer, "root"} and target not in ALLOWED[layer]:
                violations.append(f"{'/'.join(module)} → {target}")
    c.check("레이어 의존 방향을 지킴", not violations, violations[:5])
    c.check("계약·엔진·판단 계층은 파일·네트워크·DB·LLM 모듈을 쓰지 않음", not impure, impure[:5])
    c.check("검사 대상 표준 라이브러리 목록은 실제 모듈", all(name in sys.stdlib_module_names for name in PURE_STDLIB))


def _imports(path: Path, module: tuple[str, ...]) -> list[tuple[str, bool]]:
    """(대상, 외부 여부) 목록. 내부면 대상은 ripple의 하위 레이어 이름(최상위 모듈이면 'root')."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module[:-1]  # 모듈 파일이든 __init__이든 바로 위가 상대 import의 기준 패키지
    found: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        names: list[tuple[str, ...]] = []
        if isinstance(node, ast.Import):
            names = [tuple(alias.name.split(".")) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                names = [base + (tuple(node.module.split(".")) if node.module else ())]
            elif node.module:
                names = [tuple(node.module.split("."))]
        for parts in names:
            if parts[0] == "ripple":
                found.append((parts[1] if len(parts) > 1 else "root", False))
            else:
                found.append((parts[0], True))
    return found
