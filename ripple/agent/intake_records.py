"""문서 접수 확정의 수정 기록 줄(docs/input.md(문서 접수)): 항목마다 뺌·넘김·받아들임, 칸마다 제안 → 확정.

판단 계층 재보정 자료(DecisionTrace)는 연산·대상 칸에만 붙인다. 원문 조각은 합성 모드에서만 남긴다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ripple.contracts.assistant import ChangeDraft
from ripple.contracts.corrections import CorrectionAction, CorrectionEvent, CorrectionOrigin, DecisionTrace
from ripple.contracts.domain import DataMode
from ripple.contracts.intake import IntakeConfirmation, IntakeProposal, ItemAction

from .intake_types import Actor

SLOT_TOPICS = {"op": "change_op", "part_ids": "target_part"}
"""판단 계층 재보정 자료를 붙이는 칸(연산 → 변경 종류 주제, 대상 → 대상 부재 주제)."""


def correction_events(
    proposal: IntakeProposal,
    traces: Mapping[str, tuple[DecisionTrace, ...]],
    model: str | None,
    confirmation: IntakeConfirmation,
    finals: dict[str, ChangeDraft],
    actor: Actor,
) -> list[CorrectionEvent]:
    """확정 하나의 수정 기록 줄들. model은 AI 추출 항목의 모델 이름(규칙 항목에는 붙이지 않는다)."""
    now = datetime.now(UTC)
    synthetic = proposal.data_mode is DataMode.SYNTHETIC
    decisions = {d.item_id: d for d in confirmation.decisions}
    events: list[CorrectionEvent] = []
    for item in proposal.items:
        decision = decisions.get(item.item_id)
        if decision is None:
            continue
        base = {
            "at": now,
            "actor": actor.login_id,
            "demo": actor.demo,
            "dev": actor.dev,
            "data_mode": proposal.data_mode,
            "origin": CorrectionOrigin.INTAKE,
            "ref": proposal.proposal_id,
            "item": item.item_id,
            "extractor": item.extractor.value,
            "model": model if item.extractor.value == "llm" else None,
            "text": item.source.text[:1000] if synthetic else None,
        }
        if decision.action is ItemAction.DROP:
            events.append(CorrectionEvent(**base, slot="item", action=CorrectionAction.DROP))
            continue
        handoff = decision.draft is not None
        events.append(
            CorrectionEvent(
                **base, slot="item", action=CorrectionAction.HANDOFF if handoff else CorrectionAction.ACCEPT
            )
        )
        final = finals.get(item.item_id)
        if final is None or item.draft is None:
            continue
        by_topic = {t.topic: t for t in traces.get(item.item_id, ())}
        events.extend(_slot_events(base, item.draft, final, by_topic))
    return events


def _slot_events(
    base: dict[str, Any], proposed: ChangeDraft, final: ChangeDraft, traces: dict[str, DecisionTrace]
) -> list[CorrectionEvent]:
    """칸마다 제안 → 확정: 없던 칸을 채움(ADD) · 그대로 맞음(ACCEPT) · 고침(EDIT). 둘 다 없는 칸은 건너뛴다."""
    proposed_fills = {"op": proposed.op, **proposed.slots}
    final_fills = {"op": final.op, **final.slots}
    events = []
    for name in sorted(set(proposed_fills) | set(final_fills)):
        before, after = proposed_fills.get(name), final_fills.get(name)
        if before is None and after is None:
            continue
        if before is None:
            action = CorrectionAction.ADD
        elif after is not None and before.value == after.value:
            action = CorrectionAction.ACCEPT
        else:
            action = CorrectionAction.EDIT
        topic = SLOT_TOPICS.get(name)
        events.append(
            CorrectionEvent(
                **base,
                slot=name,
                action=action,
                proposed=None if before is None else _json(before.value),
                final=None if after is None else _json(after.value),
                method=None if before is None else before.method.value,
                trace=traces.get(topic) if topic else None,
            )
        )
    return events


def _json(value: object) -> str:
    return json.dumps(list(value) if isinstance(value, tuple) else value, ensure_ascii=False)[:400]
