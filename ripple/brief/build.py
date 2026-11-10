"""결정 도우미 만들기: 기록 본문(분석 결과) → 세 줄(규칙) · 확인할 것 후보 → 고르기(규칙 또는 AI) → 검사.

- AI는 합성 데이터 기록에서만 부른다: 넘겨받은 경계(Guarded)와 별도로 기록 본문의 데이터 모드를 한 번 더 본다
  (활성 지도가 합성이어도 실데이터 기록을 열 수 있어서).
- AI가 고른 결과가 검사에 걸리면 규칙 결과로 바꾸고, 규칙 결과가 검사에 걸리면 프로그램 오류(BriefError)다 —
  틀린 숫자를 보이느니 도우미를 못 보이게 한다(결재는 그대로 됨).
- 비슷한 과거 사례는 받은 CaseFinder가 채운다(기본은 빈 묶음). 찾다 실패해도 도우미는 그대로 낸다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from ripple.contracts.brief import BriefCheck, BriefLine, DecisionBrief, PastCases
from ripple.contracts.domain import DataMode
from ripple.contracts.records import RecordBody
from ripple.contracts.result import AnalysisResult
from ripple.llm.base import Guarded

from .audit import audit
from .checks import check_options
from .facts import Facts
from .lines import advice_line, change_line, loss_line
from .pick import ai_checks, rule_checks

CaseFinder = Callable[[AnalysisResult], PastCases]
log = logging.getLogger(__name__)


class BriefError(RuntimeError):
    """규칙으로 만든 도우미가 검사를 통과하지 못했다(문장 템플릿·검사의 결함)."""


def no_cases(_: AnalysisResult) -> PastCases:
    return PastCases()


def build_brief(
    body: RecordBody,
    *,
    record_id: str,
    revision: int,
    today: date,
    llm: Guarded | None = None,
    cases: CaseFinder = no_cases,
    alternatives: AnalysisResult | None = None,
) -> DecisionBrief:
    """alternatives = 그 기록 요청을 같은 지도·같은 계산 판으로 대안 포함 계산한 결과(더 저렴한 대안 권고에만 쓰고,
    검사는 그 값도 허용한다). 없으면 기록 본문만."""
    facts = Facts(body=body, today=today)
    result = body.result
    options = check_options(facts)
    advice = advice_line(result, has_checks=bool(options), alternatives=alternatives)
    lines = (change_line(result), loss_line(facts), advice)
    found = _cases(cases, body, record_id)

    def make(checks: tuple[BriefCheck, ...], by: str) -> DecisionBrief:
        return DecisionBrief.model_validate(
            {
                "ecn_id": body.ecn_id,
                "revision": revision,
                "record_id": record_id,
                "data_mode": body.data_mode,
                "lines": lines,
                "checks": checks,
                "cases": found,
                "picked_by": by,
            }
        )

    rule = make(rule_checks(options), "rule")
    problems = audit(rule, body, today, alternatives)
    if problems:
        raise BriefError("; ".join(problems))
    picked = _ai(llm, body, lines, options)
    if picked is None:
        return rule
    chosen = make(picked, "ai")
    wrong = audit(chosen, body, today, alternatives)
    if wrong:
        log.warning("AI가 고른 확인할 것이 검사에 걸림 — 규칙 순서로 냄(%s %s): %s", body.ecn_id, record_id, wrong[:3])
        return rule
    return chosen


def _ai(
    llm: Guarded | None, body: RecordBody, lines: tuple[BriefLine, ...], options: list[BriefCheck]
) -> tuple[BriefCheck, ...] | None:
    if llm is None or body.data_mode is not DataMode.SYNTHETIC or body.result.data_mode is not DataMode.SYNTHETIC:
        return None
    return ai_checks(llm, body.result, lines, options)


def _cases(cases: CaseFinder, body: RecordBody, record_id: str) -> PastCases:
    try:
        return cases(body.result)
    except Exception:  # 과거 사례는 보조 정보 — 찾지 못해도 세 줄·확인할 것은 낸다(무엇이 실패했는지는 남긴다)
        log.warning("과거 사례 찾기 실패 — 빈 묶음으로 냄(%s %s)", body.ecn_id, record_id, exc_info=True)
        return PastCases()
