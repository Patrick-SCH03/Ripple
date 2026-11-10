"""내용 해시 식별자: 그래프 스냅샷 ID와 분석 ID.

정규 JSON(키 정렬, 공백 없음, UTF-8)의 SHA-256 앞 16자리에 접두어를 붙인다.
분석 ID는 결과에 영향을 주는 필드만 쓰고, 순서가 의미 없는 목록은 정렬한다.
그래서 원문 문장·제목·ECN 번호가 달라도 같은 변경이면 같은 분석 ID가 나온다.
"""

from __future__ import annotations

import hashlib
import json

from .analysis import AnalysisRequest, Versions
from .change import ChangeCause, ChangeOp
from .domain import GraphSnapshot

JsonDict = dict[str, object]


def canonical_json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


LATER_FIELDS: dict[str, tuple[str, ...]] = {
    "activities": ("confirmations", "performer"),  # 1.22.0 공정 현장 확인, 1.32.0 수행 주체
    "blocks": ("shape", "outfit_items", "electric_items"),  # 1.32.0 난이도 입력
    "parts": ("secondary_drawing_ids",),  # 1.32.0 다른 분야 도면
    "specs": ("origin", "transport"),  # 1.33.0 외자재 원산지 구분·운송 방식
}
"""목록 안 항목에 나중에 더한 선택 필드: 비어 있으면(None·빈 목록) 지도 ID 정규형에서 뺀다."""


def snapshot_id(snapshot: GraphSnapshot) -> str:
    """snapshot_id 필드를 뺀 내용의 해시. 필드 값과 무관하게 내용이 같으면 같다.

    계약에 나중에 더한 필드(1.8.0 pipe_systems, 1.22.0 Activity.confirmations, 1.32.0 crews·수행 주체·블록 난이도 입력·
    다른 분야 도면, 1.33.0 규격 원산지·운송 방식)는 비어 있으면 넣지 않는다: 그 필드가 없던 지도 파일(엑셀로 가져온
    지도 포함)의 ID가 그대로 맞는다.
    """
    excluded = {"snapshot_id"}
    excluded |= set() if snapshot.pipe_systems else {"pipe_systems"}
    excluded |= set() if snapshot.crews else {"crews"}
    body = snapshot.model_dump(mode="json", exclude=excluded)
    for collection, fields in LATER_FIELDS.items():
        for item in body[collection]:
            for name in fields:
                if item[name] is None or item[name] == []:
                    del item[name]
    return _digest("G", body)


PERMISSIBLE_SINCE = (1, 29, 0)
"""변경 원인(선주 요청)이 결과를 바꾸기 시작한 계약 판. 그 전 판(1.28.0)의 기록은 원인을 계산에 쓰지 않아 ID에 없다."""


def analysis_id(versions: Versions, request: AnalysisRequest) -> str:
    body = normalized_request(request)
    if not _at_least(versions.contract, PERMISSIBLE_SINCE):
        body.pop("permissible_delay", None)  # 옛 기록의 분석 ID가 그대로 맞게
    return _digest("A", {"versions": versions.model_dump(mode="json"), "request": body})


def _at_least(version: str, since: tuple[int, ...]) -> bool:
    """'1.29.0' 꼴 판 비교. 숫자 판이 아니면(시험용 이름 등) 지금 판으로 본다."""
    try:
        return tuple(int(part) for part in version.split(".")) >= since
    except ValueError:
        return True


def normalized_request(request: AnalysisRequest) -> JsonDict:
    """분석 결과를 바꾸는 필드만 남긴 정규형.

    변경 사유(의도)는 대안을 끈 분석에서는 계산에 쓰지 않아 넣지 않는다: 분석 뒤에 사유를 기록해도 분석 ID가 같다.
    대안 포함 분석은 적격 판정이 의도에 따라 달라 넣는다(docs/engine.md(대안) 6절).
    변경 원인은 선주 요청일 때만 결과가 달라(허용 지연) 그때만 표시를 넣는다.
    """
    change = request.change
    intent: JsonDict = (
        {"intent": None if change.intent is None else change.intent.value} if request.include_alternatives else {}
    )
    return {
        **intent,
        "ship_ids": sorted(change.ship_ids),
        "ops": sorted((normalized_op(op) for op in change.ops), key=canonical_json),
        "as_of": request.as_of.isoformat(),
        "confirm_on": request.effective_confirm_on.isoformat(),
        "horizon_days": request.horizon_days,
        "holds": sorted((h.model_dump(mode="json") for h in request.holds), key=canonical_json),
        "include_alternatives": request.include_alternatives,
        # 1.23.0 설계 승인 전(검토 중·선주 승인 대기)이면 판정 이유가 달라 넣는다.
        # 미입력·승인·적용 범위(정보)는 넣지 않는다
        **({"design_pending": True} if change.design_status.pending else {}),
        # 1.29.0 선주 요청이면 인도 지연이 허용 지연이라 지체상금이 빠진다.
        # 그 밖의 원인·미입력은 결과가 같아 넣지 않는다
        **({"permissible_delay": True} if permissible_delay(request) else {}),
        # 1.29.0 의장품 선상 설치(켰을 때만 — 끈 요청은 이 필드가 없던 분석 ID 그대로)
        **({"outfit_on_board": True} if request.outfit_on_board else {}),
    }


def permissible_delay(request: AnalysisRequest) -> bool:
    """이 요청이 늘리는 인도 지연이 인도일 조정 대상(허용 지연)인가: 변경 원인이 선주 요청일 때(명세 4-6)."""
    return request.change.cause is ChangeCause.OWNER_REQUEST


ORDERED_LISTS = frozenset({"added_spool_spec_ids"})
"""순서가 의미 있는 연산 목록. 경로 변경의 더하는 스풀은 규격 순서대로 배치된다(docs/engine.md(전파) 3절)."""


def normalized_op(op: ChangeOp) -> JsonDict:
    """연산 정규형. 분석 ID와 변경 후 보기의 임시 ID가 같은 정규형을 쓴다.

    대상 ID 목록처럼 순서가 의미 없는 목록은 정렬하고, ORDERED_LISTS는 받은 순서를 지킨다.
    """
    body: JsonDict = op.model_dump(mode="json")
    for key, value in body.items():
        if isinstance(value, list) and key not in ORDERED_LISTS:
            body[key] = sorted(value, key=str)
    return body


def _digest(prefix: str, data: object) -> str:
    return f"{prefix}-{hashlib.sha256(canonical_json(data)).hexdigest()[:16]}"
