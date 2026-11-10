"""관문 사례 도구(scripts/gate_cases.py): 준비는 계산자에게 힌트 없는 사본만 주고, 조립은 고른 사례만 쓰며 다른 계산
기록을 지우지 않는다. 지도 ID 다시 찍기는 그 한 줄만 바꾸고 입력이 달라진 사례가 있으면 쓰지 않는다. 임시 폴더에서
돈다(저장소의 eval/gate_cases는 읽기만)."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import yaml
from harness import Checker

from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.evaluation import CaseExpectation


def _tool() -> Any:
    """scripts/gate_cases.py를 새 모듈로 읽는다(검사마다 GATE_DIR을 임시 폴더로 바꿔 쓰므로 다른 곳과 공유하지 않음)."""
    spec = importlib.util.spec_from_file_location("gate_cases_tool", PROJECT_ROOT / "scripts" / "gate_cases.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass가 정의 중에 자기 모듈을 찾는다
    spec.loader.exec_module(module)
    return module


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _expected(body: bytes | str | None) -> CaseExpectation | None:
    """사례 파일(expected 키) 또는 기대값 파일을 계약으로 읽는다 — 기본값 키가 있고 없음의 차이는 같은 정답으로 본다."""
    if body is None:
        return None
    data = yaml.safe_load(body) or {}
    return CaseExpectation.model_validate(data.get("expected", data) if "case_id" in data else data)


def run(c: Checker) -> None:
    c.section("관문 사례 도구(준비·조립, 임시 폴더)")
    tool = _tool()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tool.GATE_DIR = root / "gate_cases"
        stage = tool.STAGES[1]
        ws = root / "ws"
        with redirect_stdout(io.StringIO()) as out:
            code = tool._prepare(stage, ws)
        shown = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((ws / "cases").glob("*.yaml"))]
        stored = [
            yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((stage.folder / "inputs").glob("*.yaml"))
        ]
        c.check(
            "준비: 전달본 점검 통과, 작업 폴더 사례 입력은 제목 = 번호·focus 빈 값, 저장되는 사례 입력은 focus 그대로",
            code == 0
            and len(shown) == len(stored) == 30
            and all(
                s["focus"] == ""
                and s["title"] == s["request"]["change"]["title"] == f"설계변경 {s['request']['change']['ecn_id']}"
                for s in shown
            )
            and any(s["focus"] for s in stored),
            out.getvalue()[-300:],
        )

        # 조립: 작업 폴더에 30건의 기대값(저장소 정답)·작업지·요약, 목적지에는 다른 요약 기록이 이미 있음
        (ws / "expected").mkdir(exist_ok=True)
        for case in stored:
            answer = yaml.safe_load(
                (PROJECT_ROOT / "eval" / "gate_cases" / "1" / f"{case['case_id']}.yaml").read_text("utf-8")
            )
            (ws / "expected" / f"{case['case_id']}.yaml").write_text(
                yaml.safe_dump(answer["expected"], allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            (ws / "worksheets" / f"{case['case_id']}.md").write_text(f"# {case['case_id']} 작업지\n", encoding="utf-8")
        (ws / "worksheets" / "SUMMARY.md").write_text("# 새 요약\n", encoding="utf-8")
        target = stage.folder / "worksheets"
        target.mkdir(parents=True, exist_ok=True)
        (target / "SUMMARY-old.md").write_text("# 다른 계산 기록\n", encoding="utf-8")
        # 고르지 않을 사례(G1-002)의 이전 조립 결과: 계산 주체·날짜·검토 기록이 구분되게
        earlier = yaml.safe_load((PROJECT_ROOT / "eval" / "gate_cases" / "1" / "G1-002.yaml").read_text("utf-8"))
        earlier |= {"computed_by": "이전 계산", "computed_on": "2026-10-01", "checked_by": "이전 검토"}
        (stage.folder / "G1-002.yaml").write_text(yaml.safe_dump(earlier, allow_unicode=True), encoding="utf-8")
        (target / "G1-002.md").write_text("# 이전 작업지\n", encoding="utf-8")
        base = ["assemble", str(ws), "--by", "검사", "--stage", "1"]

        def assemble(*extra: str) -> int:
            """종료 코드, 예외로 멈추면 -1(쓰다가 실패한 것도 이 검사의 실패로 남게)."""
            try:
                with redirect_stdout(io.StringIO()):
                    return int(tool.main([*base, *extra]))
            except Exception:
                return -1

        before = _files(tool.GATE_DIR)
        refused = {
            "빈 사례 목록": assemble("--cases", "", "--summary", "SUMMARY-t.md"),
            "쉼표만": assemble("--cases", ",", "--summary", "SUMMARY-t.md"),
            "일부인데 요약 이름 없음": assemble("--cases", "G1-001"),
            "요약 이름이 다른 사례 작업지": assemble("--cases", "G1-001", "--summary", "G1-002.md"),
            "요약 이름 소문자": assemble("--cases", "G1-001", "--summary", "summary.md"),
            "요약 이름 금지 문자": assemble("--cases", "G1-001", "--summary", "SUMMARY-?.md"),
            "요약 이름 경로": assemble("--cases", "G1-001", "--summary", "../SUMMARY-x.md"),
            "없는 사례": assemble("--cases", "G1-001,G1-999", "--summary", "SUMMARY-t.md"),
        }
        c.check(
            "조립 거부: 빈 목록·요약 이름 충돌·금지 문자·경로·없는 사례는 아무것도 쓰지 않고 종료 코드 1",
            all(code == 1 for code in refused.values()) and _files(tool.GATE_DIR) == before,
            {k: v for k, v in refused.items() if v != 1},
        )
        (ws / "worksheets" / "SUMMARY.md").unlink()
        missing = assemble("--cases", "G1-001", "--summary", "SUMMARY-t.md")
        c.check("조립 거부: 작업 폴더에 요약이 없으면 쓰지 않음", missing == 1 and _files(tool.GATE_DIR) == before)
        (ws / "worksheets" / "SUMMARY.md").write_text("# 새 요약\n", encoding="utf-8")

        part = assemble("--cases", "G1-001", "--summary", "SUMMARY-t.md")
        after = _files(tool.GATE_DIR)
        changed = {k for k in after if before.get(k) != after[k]}
        written = yaml.safe_load(after.get("1/G1-001.yaml", b"{}").decode("utf-8")) or {}
        c.check(
            "일부 조립: 고른 사례 파일·작업지·요약만 쓰고(내용 = 작업 폴더), 고르지 않은 사례의 이전 결과·작업지와 "
            "다른 요약 기록은 바이트까지 그대로",
            part == 0
            and changed == {"1/G1-001.yaml", "1/worksheets/G1-001.md", "1/worksheets/SUMMARY-t.md"}
            and set(before) <= set(after)
            and written.get("computed_by") == "검사"
            and _expected(after.get("1/G1-001.yaml")) == _expected((ws / "expected" / "G1-001.yaml").read_bytes())
            and after["1/worksheets/G1-001.md"] == (ws / "worksheets" / "G1-001.md").read_bytes()
            and after["1/worksheets/SUMMARY-t.md"] == (ws / "worksheets" / "SUMMARY.md").read_bytes(),
            sorted(changed),
        )
        full = assemble()
        final = _files(tool.GATE_DIR)
        sheets = {
            f"1/worksheets/{p.name}": p.read_bytes() for p in (ws / "worksheets").glob("*.md") if p.name != "SUMMARY.md"
        }
        c.check(
            "전체 조립: 30건(기대값 = 작업 폴더)과 작업지·요약을 내용까지 쓰고, 이미 있던 다른 요약 기록"
            "(SUMMARY-old·SUMMARY-t)은 바이트까지 그대로",
            full == 0
            and all(
                _expected(final.get(f"1/G1-{n:03d}.yaml"))
                == _expected((ws / "expected" / f"G1-{n:03d}.yaml").read_bytes())
                for n in range(1, 31)
            )
            and all(final.get(name) == body for name, body in sheets.items())
            and final.get("1/worksheets/SUMMARY.md") == (ws / "worksheets" / "SUMMARY.md").read_bytes()
            and final.get("1/worksheets/SUMMARY-old.md") == before["1/worksheets/SUMMARY-old.md"]
            and final.get("1/worksheets/SUMMARY-t.md") == after["1/worksheets/SUMMARY-t.md"],
        )
    _restamp(c, tool)


OLD_ID = "G-0000000000000000"


def _restamp(c: Checker, tool: Any) -> None:
    """지도 ID 다시 찍기: 옛 지도 ID의 사례·입력을 지금 지도 ID로(그 한 줄만).
    입력이 달라진 사례가 있으면 아무것도 안 쓴다."""
    c.section("관문 사례 도구(지도 ID 다시 찍기, 임시 폴더)")
    repo = PROJECT_ROOT / "eval" / "gate_cases" / "1"
    names = ("G1-001.yaml", "G1-002.yaml", "inputs/G1-001.yaml", "inputs/G1-002.yaml")
    with tempfile.TemporaryDirectory() as tmp:
        tool.GATE_DIR = Path(tmp) / "gate_cases"
        stage = tool.STAGES[1]
        (stage.folder / "inputs").mkdir(parents=True)
        for name in names:
            text = tool.SNAPSHOT_LINE.sub(rf"\g<1>{OLD_ID}", (repo / name).read_text(encoding="utf-8"))
            (stage.folder / name).write_text(text, encoding="utf-8", newline="\n")
        drifted = stage.folder / "inputs" / "G1-002.yaml"
        old_text = drifted.read_text(encoding="utf-8")
        drifted.write_text(old_text.replace("horizon_days: 60", "horizon_days: 61"), encoding="utf-8", newline="\n")
        before = _files(tool.GATE_DIR)
        with redirect_stdout(io.StringIO()):
            refused = tool.main(["restamp", "--stage", "1"])
        c.check(
            "입력이 사례 입력 생성기와 달라진 사례가 하나라도 있으면 아무것도 쓰지 않고 종료 코드 1",
            refused == 1 and _files(tool.GATE_DIR) == before and "horizon_days: 61" in drifted.read_text("utf-8"),
        )
        drifted.write_text(old_text, encoding="utf-8", newline="\n")
        with redirect_stdout(io.StringIO()) as out:
            code = tool.main(["restamp", "--stage", "1"])
        after = {name: (stage.folder / name).read_bytes() for name in names}
        c.check(
            "옛 지도 ID의 사례·입력: 지도 ID 한 줄만 지금 지도로 바뀌어 저장소 사례와 바이트까지 같음(기대값 그대로), "
            "바꾼 파일과 옛 → 새 ID를 출력",
            code == 0
            and all(after[name] == (repo / name).read_bytes() for name in names)
            and out.getvalue().count(f"{OLD_ID} → ") == len(names),
            out.getvalue()[-300:],
        )
