"""숨긴 모델 대비 평가 명령(scripts/eval_cost·eval_schedule·eval_decision)이 같이 쓰는 분할·시드 인자.

평가 분할은 --final이 있을 때만 열고, 다른 시드(합성 세계 전체를 다시 만든 반복)는 개발 분할로만 잰다.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from ripple.contracts.dataset import EcnSplit


@dataclass(frozen=True, slots=True)
class SplitRun:
    name: str  # 명령줄 이름(dev · eval)
    split: EcnSplit
    seeds: tuple[int | None, ...]  # None = 생성기 기본 시드


def add_split_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--split", choices=("dev", "eval"), default="dev")
    parser.add_argument("--final", action="store_true", help="평가 분할은 최종 인증 때만(이 표시가 있어야 돈다)")
    parser.add_argument("--seeds", default="", help="쉼표로 나눈 시드(개발 분할만): 합성 세계 전체를 다시 만든 강건성")


def split_run(
    args: argparse.Namespace, *, dev_only: bool = False, refused: str = "다른 시드는 개발 분할로만 재요."
) -> SplitRun | None:
    """인자 → 실행할 분할·시드. 막히면 이유를 출력하고 None(종료 코드 2).

    dev_only: 시드 말고도 개발 분할로만 도는 선택(예: 확인 모드)이 켜졌는지.
    """
    if args.split == "eval" and not args.final:
        print("평가 분할은 최종 인증 때 한 번만 재요. 정말이면 --final을 붙여 주세요.")
        return None
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if (seeds or dev_only) and args.split == "eval":
        print(refused)
        return None
    split = EcnSplit.DEV if args.split == "dev" else EcnSplit.EVAL
    return SplitRun(args.split, split, tuple(seeds) if seeds else (None,))
