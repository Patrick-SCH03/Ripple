"""코드 크기 예산과 import 순환: 모듈화가 다시 무너지지 않게 ripple/의 크기를 잰다(비지 않은 줄).

모듈 ≤ 350줄, 클래스 ≤ 250줄, 함수 ≤ 60줄. 넘는 곳은 이유와 함께 EXCEPTIONS에 적고, 줄면 표에서 뺀다.
순환은 함수 안·TYPE_CHECKING 안의 import까지 센다(지금 0개라 엄격하게 둔다).
화면(web/src)은 oxlint max-lines(300)·max-lines-per-function(200)이 같은 일을 한다(web/.oxlintrc.json).
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from harness import Checker

from ripple.config.settings import PROJECT_ROOT

MODULE_MAX, CLASS_MAX, FUNCTION_MAX = 350, 250, 60

EXCEPTIONS: dict[str, str] = {
    "ripple/api/workspace.py": "검사가 모듈 전역 build를 바꿔 끼워 가져오기 읽기가 이 파일에 있어야 한다",
    "ripple/api/workspace.py::Workspaces": "검사가 가져오기를 직접 부르고 _parsing·_switch·_install을 바꿔 끼운다",
    "ripple/contracts/domain.py": "지도 어휘·노드 계약 선언(139개 파일이 import)",
    "ripple/ingest/template.py": "엑셀 양식 시트·열 정의 표(SHEETS)",
    "ripple/ingest/variants.py": "생성기 격리 검사(tests/checks/ingest.py)가 이 파일 하나를 읽는다",
}


def _size(lines: list[str], start: int, end: int) -> int:
    return sum(1 for line in lines[start - 1 : end] if line.strip())


def over_budget(root: Path) -> list[str]:
    """기준을 넘는 모듈(경로)·클래스·함수(경로::이름)."""
    found: list[str] = []
    for path in sorted((root / "ripple").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if _size(lines, 1, len(lines)) > MODULE_MAX:
            found.append(rel)
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ClassDef):
                limit = CLASS_MAX
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                limit = FUNCTION_MAX
            else:
                continue
            if _size(lines, node.lineno, node.end_lineno or node.lineno) > limit:
                found.append(f"{rel}::{node.name}")
    return found


def _targets(name: str, path: Path, modules: set[str]) -> set[str]:
    """이 모듈이 import하는 ripple 모듈(패키지 __init__ 포함)."""
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join([*parts[: len(parts) - node.level + 1], *([node.module] if node.module else [])])
            candidates = [base, *(f"{base}.{alias.name}" for alias in node.names)]
        elif isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        else:
            continue
        for candidate in candidates:
            while candidate and candidate not in modules:
                candidate = candidate.rpartition(".")[0]
            if candidate and candidate != name:
                found.add(candidate)
    return found


def _package_only(group: list[str]) -> bool:
    """패키지와 그 하위 모듈만으로 된 묶음 — __init__이 하위 모듈을 다시 내보내는 정상 구조라 순환으로 세지 않는다."""
    return any(all(name == top or name.startswith(f"{top}.") for name in group) for top in group)


def import_cycles(root: Path) -> list[list[str]]:
    """ripple 모듈 import 그래프의 순환(크기 2 이상인 강한 연결 요소, Tarjan). 하위 모듈 → 부모 패키지 간선을 더한다."""
    files = {
        path.relative_to(root).with_suffix("").as_posix().replace("/", ".").removesuffix(".__init__"): path
        for path in (root / "ripple").rglob("*.py")
    }
    graph = {name: _targets(name, path, set(files)) for name, path in files.items()}
    for name, targets in graph.items():  # A.sub를 import하면 A/__init__이 먼저 실행된다
        parent = name.rpartition(".")[0]
        if parent in graph:
            targets.add(parent)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        for nxt in graph[node]:
            if nxt not in index:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            group: list[str] = []
            while not group or group[-1] != node:
                group.append(stack.pop())
            if len(group) > 1 and not _package_only(group):
                cycles.append(sorted(group))

    for name in sorted(graph):
        if name not in index:
            visit(name)
    return cycles


def _fixture(folder: Path) -> None:
    """측정이 맞는지 볼 가짜 패키지: 긴 함수 하나, 두 모듈 순환, 하위 모듈을 다시 내보내는 정상 패키지."""
    package = folder / "ripple"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    body = "\n".join(f"    x{i} = {i}" for i in range(FUNCTION_MAX))
    (package / "a.py").write_text(f"from ripple import b\n\n\ndef long():\n{body}\n", encoding="utf-8")
    (package / "b.py").write_text("from ripple.a import long\n", encoding="utf-8")
    (package / "pkg").mkdir()
    (package / "pkg" / "__init__.py").write_text("from ripple.pkg.sub import X\n", encoding="utf-8")
    (package / "pkg" / "sub.py").write_text("X = 1\n", encoding="utf-8")


def run(c: Checker) -> None:
    c.section("코드 크기 예산·import 순환")
    found = set(over_budget(PROJECT_ROOT))
    over = sorted(found - set(EXCEPTIONS))
    budget = f"모듈 ≤ {MODULE_MAX}줄 · 클래스 ≤ {CLASS_MAX}줄 · 함수 ≤ {FUNCTION_MAX}줄"
    c.check(f"{budget}(넘으면 나누거나 이유를 표에)", not over, over)
    stale = sorted(set(EXCEPTIONS) - found)
    c.check("예외 표의 항목은 지금도 기준을 넘음(줄었으면 표에서 뺀다)", not stale, stale)
    cycles = import_cycles(PROJECT_ROOT)
    c.check("ripple 모듈 사이에 import 순환이 없음", not cycles, cycles[:3])
    with tempfile.TemporaryDirectory() as tmp:
        _fixture(Path(tmp))
        c.check(
            "측정 자체 점검: 기준보다 긴 함수와 두 모듈 순환은 찾고, 하위 모듈을 다시 내보내는 패키지는 넘김",
            over_budget(Path(tmp)) == ["ripple/a.py::long"] and import_cycles(Path(tmp)) == [["ripple.a", "ripple.b"]],
            (over_budget(Path(tmp)), import_cycles(Path(tmp))),
        )
