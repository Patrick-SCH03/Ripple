"""과거 설계변경 백테스트('예측 대 실제', docs/backtest.md, `ripple/eval/backtest/`).

  uv run python scripts/backtest.py template <양식.xlsx>             빈 양식(사례 시트 + 설명 시트)
  uv run python scripts/backtest.py template <양식.xlsx> --example   가상 예시 3건을 채운 양식('예시(가상)')
  uv run python scripts/backtest.py run <입력.xlsx> <출력 폴더>       사례마다 예측·비교 → backtest_result.xlsx·.md

실데이터 사례는 저장소 밖에 두고, 결과도 저장소 밖 폴더에 쓴다(저장소 안 출력 폴더는 거부). 서버·키 없이 돈다.
종료 코드: 0 = 끝남(계산 불가 사례가 있어도), 2 = 입력·경로 문제.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from ripple.config.settings import PROJECT_ROOT
from ripple.eval.backtest.compare import run_cases
from ripple.eval.backtest.engine import Engine
from ripple.eval.backtest.examples import EXAMPLE_ROWS
from ripple.eval.backtest.report import write_results
from ripple.eval.backtest.summary import Summary, summarize
from ripple.eval.backtest.workbook import InputError, read_cases, write_template


def inside_repo(path: Path) -> bool:
    """저장소 안 경로인가(실데이터 결과를 저장소에 쓰지 않게)."""
    return path.resolve().is_relative_to(PROJECT_ROOT.resolve())


def template(path: Path, example: bool) -> int:
    write_template(path, EXAMPLE_ROWS if example else ())
    kind = "가상 예시 3건을 채운 양식" if example else "빈 양식"
    print(f"{kind}을 썼어요: {path}")
    return 0


def run(source: Path, out_dir: Path) -> int:
    if inside_repo(out_dir):
        print(f"결과 폴더가 저장소 안이에요({out_dir}). 실데이터 결과는 저장소 밖 폴더에 써 주세요.")
        return 2
    if inside_repo(source):
        print(f"주의: 입력 파일이 저장소 안이에요({source}). 실데이터면 저장소 밖으로 옮겨 주세요.")
    try:
        cases = read_cases(source)
    except (InputError, OSError) as error:
        print(f"입력을 읽지 못했어요: {error}")
        return 2
    engine = Engine.load()
    results = run_cases(cases, engine)
    summary = summarize(results)
    xlsx, md = write_results(results, summary, engine, out_dir)
    report(summary, engine)
    print(f"결과: {xlsx}\n      {md}")
    return 0


def _pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.1%}" if signed else f"{value:.1%}"


def report(summary: Summary, engine: Engine) -> None:
    versions = " · ".join(f"{name} {version}" for name, version in engine.versions())
    print(f"백테스트 · 사례 {summary.cases}건(계산 {summary.computed} · 계산 불가 {summary.failed}) · {versions}")
    for name, metric in (("비용", summary.cost), ("공수", summary.mh)):
        print(
            f"  {name}: 비교 {metric.compared}건 · 실제가 예측 범위 안 {metric.inside}/{metric.compared} · "
            f"절대 오차 중앙값 {_pct(metric.abs_error_median)} · 오차 중앙값 {_pct(metric.error_median, True)}"
        )
    median = "—" if summary.delay_median is None else f"{summary.delay_median:+g}일"
    print(f"  지연: 비교 {summary.delay_compared}건 · 예측 − 실제 중앙값 {median}")
    print(f"  가정으로 채운 칸 {summary.assumed_cells}개(결과의 '가정' 시트)")


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="과거 설계변경 백테스트(예측 대 실제)")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("template", help="사례 양식 엑셀 만들기")
    make.add_argument("path", type=Path)
    make.add_argument("--example", action="store_true", help="가상 예시 3건을 채움")
    execute = commands.add_parser("run", help="사례마다 예측하고 실제와 비교")
    execute.add_argument("source", type=Path)
    execute.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    if args.command == "template":
        return template(args.path, args.example)
    return run(args.source, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
