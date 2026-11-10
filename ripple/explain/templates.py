"""서버 글 템플릿: 숫자·수량 표현이 없는 고정 문장 + 엔터티 자리({0}, {1} …).

LLM은 이 ID만 고른다(자유 글 없음). 엔터티 자리마다 받을 수 있는 엔터티 종류가 정해져 있고, 렌더러가 이 분석
결과에 있는 엔터티인지 확인한 뒤 이름으로 바꾼다. 모든 템플릿은 TextBlock 검증(숫자·한글 수사 거부)을 통과한다
(tests/checks/explain.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ripple.contracts.result import VerdictLevel


class Slot(StrEnum):
    """엔터티 자리 종류(분석 결과 안의 엔터티)."""

    PART = "part"
    BLOCK = "block"
    PO = "po"  # 발주(PO-0130). 발주 품목 영향(PO-0130#3)에서 모은다
    DRAWING = "drawing"
    ACTIVITY = "activity"  # 공정(1.32.0 사전 점검 P-06이 짚은 공정 · 일정 영향 공정)


class Use(StrEnum):
    EXPLANATION = "explanation"
    SUPPLIER = "supplier"  # 발주 변경이 생긴 협력사 알림
    FABRICATOR = "fabricator"  # 재작업 블록 담당 알림
    DRAWING = "drawing"  # 도면 담당 알림
    CREW = "crew"  # 사내 협력사 작업반 알림(1.32.0 사전 점검 P-06 현장 공유)
    MAIL = "mail"  # 공식 메일 초안 본문(합니다체, docs/records.md(통보))


@dataclass(frozen=True, slots=True)
class Template:
    text: str
    slots: tuple[Slot, ...] = ()
    use: Use = Use.EXPLANATION


_E = Use.EXPLANATION


def _t(text: str, *slots: Slot, use: Use = _E) -> Template:
    return Template(text=text, slots=slots, use=use)


def _m(text: str, *slots: Slot) -> Template:
    return Template(text=text, slots=slots, use=Use.MAIL)


TEMPLATES: Mapping[str, Template] = MappingProxyType(
    {
        # 요약 판정(판정 수준·이유는 엔진의 숫자 없는 고정 문장과 같은 뜻)
        "verdict.approve": _t("바로 승인 가능 수준"),
        "verdict.review": _t("담당 검토 필요"),
        "verdict.warn": _t("일정·비용 영향이 큰 변경 · 주의 필요"),
        # 영향
        "impact.target": _t("요청 변경 대상 {0}", Slot.PART),
        "impact.rework": _t("{0} 블록 재작업 발생", Slot.BLOCK),
        "impact.po_change": _t("{0} 발주 변경·취소 필요", Slot.PO),
        "impact.drawing": _t("{0} 도면 개정 필요", Slot.DRAWING),
        # 확정 시점·보류
        "timing.urgent": _t("확정을 미루면 바로 추가 손실 발생"),
        "timing.relaxed": _t("탐색 기간 안에는 확정을 미뤄도 추가 손실 없음"),
        "hold.advice": _t("{0} 발주 보류 시 결정 기한 연장 가능", Slot.PO),
        # 인도·실행 방식(docs/engine.md(비용·일정) 4-6 허용 지연, 6-8 선상 설치)
        "delivery.permissible": _t(
            "선주 요청 변경 · 늘어난 인도 지연은 지체상금이 아닌 인도일 조정으로 선주 합의 필요"
        ),
        "onboard.option": _t("{0} 블록 납기 지연 의장품 — 탑재 후 선상 설치 방식과 비교", Slot.BLOCK),
        "onboard.applied": _t("{0} 블록 의장품은 탑재 후 선상 설치로 계산됨", Slot.BLOCK),
        # 하도급법 8조·공정위 「부당한 위탁취소, 수령거부 및 반품행위에 대한 심사지침」: 협의·보상 없는 취소·변경은 부당
        "po.consult": _t("협력사 발주 변경·취소 전 협력사와 손실 보상 협의 필요"),
        # 확인
        "unresolved.note": _t("판단 불가 항목 있음 — 근거 패널에서 확인"),
        "next.review": _t("확정 전 근거 패널의 비용 줄·근거 경로 확인"),
        # 알림: 협력사
        "notify.supplier.opening": _t("설계변경 검토 중인 건 사전 안내", use=Use.SUPPLIER),
        "notify.supplier.po": _t(
            "{0} 발주 사양 변경·취소 검토 중 · 현재 진행 상황 회신 요청", Slot.PO, use=Use.SUPPLIER
        ),
        "notify.supplier.hold": _t("{0} 발주 다음 단계 진행 일시 중지 가능 여부 확인 요청", Slot.PO, use=Use.SUPPLIER),
        "notify.supplier.closing": _t("확정 시 다시 안내", use=Use.SUPPLIER),
        # 알림: 재작업 블록 담당
        "notify.fabricator.rework": _t(
            "{0} 블록 재작업 발생 가능 · 작업 일정 조정 검토 요청", Slot.BLOCK, use=Use.FABRICATOR
        ),
        "notify.fabricator.closing": _t("확정 시 작업 지시 다시 전달", use=Use.FABRICATOR),
        # 알림: 도면 담당
        "notify.drawing.revise": _t("{0} 도면 개정 필요 · 개정 범위 검토 요청", Slot.DRAWING, use=Use.DRAWING),
        "notify.drawing.closing": _t("확정 전 개정안 공유 요청", use=Use.DRAWING),
        # 알림: 사내 협력사 작업반(사전 점검 P-06 — 이미 착수·완료한 공정의 수행 주체). 하도급법은 사내 협력사도 대상
        "notify.crew.opening": _t("이미 작업한 블록의 설계변경 검토 중 · 사전 안내", use=Use.CREW),
        "notify.crew.activity": _t(
            "{0} 공정에 이 변경 반영 필요 · 현재 작업 상태 회신 요청", Slot.ACTIVITY, use=Use.CREW
        ),
        "notify.crew.subcontract": _t(
            "변경 작업은 확정 후 서면 재지시 · 추가 대금은 사전 협의(하도급법)", use=Use.CREW
        ),
        "notify.crew.closing": _t("확정 시 작업 지시 다시 전달", use=Use.CREW),
        # 공식 메일(합니다체). 문단 머리(■)와 항목(-)도 템플릿이라 숫자 검사를 받는다
        "mail.heading.po": _m("■ 대상 발주"),
        "mail.heading.block": _m("■ 대상 블록"),
        "mail.heading.drawing": _m("■ 대상 도면"),
        "mail.heading.review": _m("■ 검토 내용"),
        "mail.heading.request": _m("■ 요청 사항"),
        "mail.heading.activity": _m("■ 대상 공정"),
        "mail.heading.part": _m("■ 바뀌는 부재"),
        "mail.heading.schedule": _m("■ 확정 일정"),
        "mail.item.po": _m("- {0}", Slot.PO),
        "mail.item.block": _m("- {0} 블록", Slot.BLOCK),
        "mail.item.drawing": _m("- {0}", Slot.DRAWING),
        "mail.item.activity": _m("- {0}", Slot.ACTIVITY),
        "mail.item.part": _m("- {0}", Slot.PART),
        "mail.thanks": _m("바쁘신 중에 협조해 주셔서 감사합니다."),
        "mail.supplier.intro": _m(
            "당사에서 검토 중인 설계변경과 관련하여 귀사에 발주한 아래 건의 진행 현황 확인을 요청드립니다."
        ),
        "mail.supplier.review": _m("- 위 발주의 사양 변경 또는 취소를 검토하고 있으며, 아직 확정되지 않았습니다."),
        "mail.supplier.status": _m("- 현재 제작·출하 진행 상황을 회신해 주시기 바랍니다."),
        "mail.supplier.hold": _m("- {0} 발주는 다음 단계 진행을 즉시 중지할 수 있는지 확인 부탁드립니다.", Slot.PO),
        "mail.supplier.hold_basis": _m(
            "- 아래 기한은 분석 기준일부터 보류할 경우 탑재 일정에 영향 없이 보류를 유지할 수 있는 마지막 날입니다."
        ),
        "mail.supplier.closing": _m("검토가 확정되는 대로 정식 변경 내용을 다시 안내드리겠습니다."),
        "mail.fabricator.intro": _m("설계변경 검토 결과 아래 블록에 재작업이 발생할 수 있어 미리 공유드립니다."),
        "mail.fabricator.request": _m("- 해당 블록의 작업 일정 조정 가능 여부를 검토해 주시기 바랍니다."),
        "mail.fabricator.closing": _m("변경이 확정되면 작업 지시를 다시 드리겠습니다."),
        "mail.drawing.intro": _m("설계변경 검토 결과 아래 도면의 개정이 필요하여 요청드립니다."),
        "mail.drawing.scope": _m("- 개정 범위를 검토해 주시기 바랍니다."),
        "mail.drawing.share": _m("- 변경 확정 전에 개정안을 공유해 주시기 바랍니다."),
        "mail.drawing.closing": _m("확정 일정이 정해지는 대로 다시 안내드리겠습니다."),
        "mail.crew.intro": _m("귀 작업반이 수행한 아래 공정에 설계변경이 검토되고 있어 미리 공유드립니다."),
        "mail.crew.status": _m("- 해당 공정의 현재 작업 상태(완료·진행 범위)를 회신해 주시기 바랍니다."),
        "mail.crew.subcontract": _m(
            "- 변경 작업은 확정 후 서면으로 다시 지시드리며, 추가 작업 대금은 사전에 협의하여 정하겠습니다(하도급법)."
        ),
        "mail.crew.closing": _m("변경이 확정되면 작업 지시서를 다시 드리겠습니다."),
    }
)

REASONS = "verdict.reasons"
"""판정 이유 블록: 분석 결과의 판정 이유(엔진의 숫자 없는 고정 문장)를 그대로 쓴다. 렌더러가 검증한다."""

VERDICT_TEMPLATES: Mapping[VerdictLevel, str] = MappingProxyType(
    {
        VerdictLevel.APPROVE: "verdict.approve",
        VerdictLevel.REVIEW: "verdict.review",
        VerdictLevel.WARN: "verdict.warn",
    }
)
