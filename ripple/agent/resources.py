"""비서가 쓰는 자원: 지도 어휘·현장 용어 사전·판단 계층 설정·엔진 입력·이름표. 앱이 시작할 때 한 번 만든다."""

from __future__ import annotations

from dataclasses import dataclass

from ripple.contracts.contacts import ContactBook
from ripple.contracts.decision import DecisionConfig, DecisionTopic
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.lexicon import Lexicon
from ripple.contracts.params import ParamSet
from ripple.contracts.rulebook import RuleBook
from ripple.contracts.translation import Glossary
from ripple.engine.describe import ACTIVITY_NAMES
from ripple.engine.index import GraphIndex
from ripple.explain.render import Directory
from ripple.nl.pipeline import Models
from ripple.nl.vocab import MapVocabulary

RULE_MODELS = Models(
    op={"cue": 1.0, "none:bias": 0.5},
    intent={"cue": 1.0, "none:bias": 0.5},
    target={"det": 1.0, "none:bias": 0.5},
)
"""보정 산출물에 점수기가 없을 때(판단 계층 v0) 쓰는 규칙 기반 점수: 결정적 일치와 사전 단서만."""


@dataclass(frozen=True, slots=True)
class AssistantResources:
    snapshot: GraphSnapshot
    index: GraphIndex
    vocab: MapVocabulary
    lexicon: Lexicon
    decision: DecisionConfig
    models: Models
    rulebook: RuleBook
    params: ParamSet
    directory: Directory
    data_mode: DataMode

    @classmethod
    def build(
        cls,
        snapshot: GraphSnapshot,
        index: GraphIndex,
        lexicon: Lexicon,
        decision: DecisionConfig,
        rulebook: RuleBook,
        params: ParamSet,
        data_mode: DataMode,
        contacts: ContactBook | None = None,
        glossary: Glossary | None = None,
    ) -> AssistantResources:
        """contacts(시연용 가상 연락처)는 합성 모드일 때만 알림 메일에 붙인다 — 실데이터 지도에는 섞지 않는다.
        glossary(1.36.0 현장 통보문 번역 초안)는 고정 문장·용어집이라 데이터 모드와 무관하게 붙인다(외부 호출 없음)."""
        return cls(
            snapshot=snapshot,
            index=index,
            vocab=MapVocabulary(snapshot),
            lexicon=lexicon,
            decision=decision,
            models=models_of(decision),
            rulebook=rulebook,
            params=params,
            directory=directory_of(snapshot, contacts if data_mode is DataMode.SYNTHETIC else None, glossary),
            data_mode=data_mode,
        )


def models_of(decision: DecisionConfig) -> Models:
    weights = {s.topic: s.weights for s in decision.scorers}
    if not {DecisionTopic.CHANGE_OP, DecisionTopic.CHANGE_INTENT, DecisionTopic.TARGET_PART} <= set(weights):
        return RULE_MODELS
    return Models(
        op=weights[DecisionTopic.CHANGE_OP],
        intent=weights[DecisionTopic.CHANGE_INTENT],
        target=weights[DecisionTopic.TARGET_PART],
    )


def directory_of(
    snapshot: GraphSnapshot, contacts: ContactBook | None = None, glossary: Glossary | None = None
) -> Directory:
    names = {p.part_id: p.name for p in snapshot.parts}
    names.update({b.block_id: f"{b.block_id.split(':')[-1]} {b.name}" for b in snapshot.blocks})
    names.update({s.supplier_id: s.name for s in snapshot.suppliers})
    names.update({p.po_id: p.po_id for p in snapshot.purchase_orders})
    names.update({d.drawing_id: f"{d.drawing_no} 개정 {d.revision}" for d in snapshot.drawings})
    names.update({c.crew_id: c.name for c in snapshot.crews})
    names.update(activity_names(snapshot))
    return Directory(
        names=names,
        po_supplier={p.po_id: p.supplier_id for p in snapshot.purchase_orders},
        block_fabricator={b.block_id: b.fabricator_id for b in snapshot.blocks},
        drawing_discipline={d.drawing_id: d.discipline for d in snapshot.drawings},
        contacts=contacts,
        crew_contacts={c.crew_id: c.contact for c in snapshot.crews if c.contact},
        glossary=glossary,
    )


def activity_names(snapshot: GraphSnapshot) -> dict[str, str]:
    """블록 공정 이름(알림 글의 공정 자리): 'B31P 선행의장'. 이정표는 넣지 않는다(지도 이름·그래프 라벨을 쓴다)."""
    return {
        a.activity_id: f"{a.block_id.split(':')[-1]} {ACTIVITY_NAMES[a.kind]}"
        for a in snapshot.activities
        if a.block_id is not None and a.kind in ACTIVITY_NAMES
    }
