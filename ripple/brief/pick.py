"""서명 전 확인할 것 고르기: 규칙 순서(기본) 또는 AI(합성 데이터일 때만, ripple.llm.Guarded 경계 뒤).

AI는 서버가 만든 후보의 키만 골라 순서를 정한다(최대 3개, 자유 글·숫자 없음 — 글과 숫자는 후보 그대로).
후보 밖 키·중복·빈 답·3개 넘음·형식 오류·호출 실패는 모두 버리고 규칙 순서로 간다. 세 줄 요약은 AI가 고르지 않는다
(권고가 상세 대안 탭과 어긋나지 않게 규칙 우선순위로 고정, lines.py).
"""

from __future__ import annotations

from collections.abc import Sequence

from ripple.contracts.brief import BriefCheck, BriefLine
from ripple.contracts.result import AnalysisResult
from ripple.llm.base import Guarded

CHECKS_MAX = 3
BUDGET_S = 6.0  # 경로가 없는 모델에 주는 제한 시간(경로는 params/llm_v1.yaml brief.budget_s, 6초 이하)
OPTIONS_MAX = 10  # AI에 보이는 후보 수

BRIEF_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"checks": {"type": "array", "items": {"type": "string"}}},
    "required": ["checks"],
}


def rule_checks(options: Sequence[BriefCheck]) -> tuple[BriefCheck, ...]:
    """규칙 순서의 앞 3개(같은 결과면 늘 같은 답)."""
    return tuple(options[:CHECKS_MAX])


def accepted(data: object, keys: Sequence[str]) -> tuple[str, ...] | None:
    """받아들일 수 있는 답이면 고른 키(순서대로), 아니면 None. 후보 밖·중복·빈 답·3개 넘음은 받지 않는다."""
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        return None
    chosen = data["checks"]
    if not chosen or len(chosen) > CHECKS_MAX or not all(isinstance(k, str) for k in chosen):
        return None
    if len(set(chosen)) != len(chosen) or any(k not in keys for k in chosen):
        return None
    return tuple(chosen)


def ai_checks(
    llm: Guarded, result: AnalysisResult, lines: Sequence[BriefLine], options: Sequence[BriefCheck]
) -> tuple[BriefCheck, ...] | None:
    """AI가 고른 확인할 것(후보 객체 그대로, 고른 순서). 못 쓰면 None(규칙 순서)."""
    shown = list(options[:OPTIONS_MAX])
    if not llm.usable or not shown:
        return None
    keys = [option.key for option in shown]
    try:
        data = llm.generate_json(
            _prompt(result, lines, shown),
            BRIEF_SCHEMA,
            timeout_s=BUDGET_S,
            task="brief",
            accept=lambda answer: accepted(answer, keys) is not None,
        )
    except Exception:  # 경계 차단·키 없음·시간 초과·응답 형식 오류·모델 예외 모두 규칙 순서로(결재를 막지 않음)
        return None
    chosen = accepted(data, keys)
    if chosen is None:
        return None
    by_key = {option.key: option for option in shown}
    return tuple(by_key[key] for key in chosen)


def _prompt(result: AnalysisResult, lines: Sequence[BriefLine], options: Sequence[BriefCheck]) -> str:
    """세 줄 요약(서버가 이미 정함)과 후보를 보여 주고 키만 고르게 한다."""
    candidates = [f"- {o.key}: {o.text} / 틀리면: {o.why}" for o in options]
    return "\n".join(
        [
            "조선소 팀장이 설계변경 결재에 서명하기 전에 확인할 것을 고르세요. 글을 직접 쓰지 말고 아래 후보의 키만 "
            "고릅니다.",
            "이 판단이 가장 크게 기대고 있고, 틀리면 결정(승인·반려·보류)이 바뀔 수 있는 것부터 1~3개를 중요한 순서로 "
            "고르세요. 같은 내용을 두 번 고르지 마세요.",
            "",
            f"[판정] {result.verdict.level.value} — " + " / ".join(result.verdict.reasons),
            "[세 줄 요약]",
            *(f"- {line.text}" for line in lines),
            "",
            "[후보]",
            *candidates,
            "",
            '응답 형식: {"checks": ["후보 키", "후보 키"]}',
        ]
    )
