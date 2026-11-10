"""사전 점검 문장: 무엇이 걸렸나(finding) · 위험 이유 한 줄(reason, 현업 사례 유형) · 점검 불가 이유.

모두 명사형·개조식이다. 위험 이유에는 숫자를 쓰지 않는다(숫자는 분석 결과 필드에서만 — 결정 도우미 검사가
'틀리면'의 숫자를 막는다). 형상·치수는 보지 않는다 — 연결 지도에 거는 규칙 검사다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

FINDINGS = {
    "late_install": "후행 설치 불가피",
    "penetration_missing": "관통부 누락 의심",
    "hole_close": "구멍 막음 필요",
    "boundary": "상대 블록 확인",
    "secondary": "다른 분야 도면 미반영",
    "support": "새 스풀 서포트 없음",
    "notify": "현장 통보 필수",
}

REASONS = {
    "late_install": (
        "선행의장이 지난 블록의 의장품 신설·변경 — 블록 설치 불가로 폐기·재제작 뒤 선상 후행 설치, "
        "일정 크게 지연 가능(현업 사례 유형)"
    ),
    "penetration_missing": (
        "배관이 지나는 판의 관통부·칼라가 도면에 없으면 선행의장 때 설치 불가 — 현장에서 판 절단 후 재가공 필요"
        "(현업 사례 유형)"
    ),
    "hole_close": "빼는 배관이 지나던 관통부가 그대로 남으면 구멍 막음 판·칼라 작업과 검사 별도 필요",
    "boundary": (
        "블록 경계 배관 연결부는 상대 블록 배관과 맞춤 필요 — 한쪽 블록만 바꾸면 연결부 간섭으로 공수 크게 증가 "
        "가능(현업 의견)"
    ),
    "secondary": (
        "분야별로 해당 분야 도면만 보면 블록 안 간섭 누락 — 이 부재가 함께 그려진 다른 분야 도면도 개정해야 현장이 "
        "같은 도면으로 작업(현업 의견)"
    ),
    "support": "새 스풀을 받칠 서포트가 없으면 서포트 설계·단품 발주 누락으로 설치 지연 가능",
    "notify": (
        "도면에만 반영하고 현장 통보가 없으면 이미 한 공정 뒤 추가 시공(도장 뒤 화기작업 등) 발생(현업 사례 유형)"
    ),
}

UNCHECKED_REASON = "연결 지도에 이 규칙을 볼 정보 없음 — 점검 생략 · 도면·현장으로 확인 필요"

UNCHECKED_TEXT = {
    "P-01": "지도에 {blocks} 블록의 선행의장 공정 없음 — 설치 시점 점검 불가",
    "P-02": "지도에 칼라 부재 없음 — 경로가 바뀌는 배관의 관통부 점검 불가",
    "P-03": "지도에 배관 연결(pipe_joint) 없음 — 블록 경계 연결 점검 불가",
    "P-04": "지도에 다른 분야 도면 정보 없음 — 분야 간 도면 반영 점검 불가",
    "P-05": "지도에 서포트 부재 없음 — 새 스풀의 서포트 점검 불가",
}

DIRECT_NAME = "직영"
UNKNOWN_PERFORMER = "수행 주체 미상(지도에 없음)"


def code_of(entity_id: str) -> str:
    """'S-001:B31P' → 'B31P'."""
    return entity_id[entity_id.rfind(":") + 1 :]


def joined(names: Iterable[str], limit: int = 3) -> str:
    """'가·나·다 외 2개'(앞 limit개까지, 겹치는 이름은 한 번)."""
    unique = list(dict.fromkeys(names))
    shown = "·".join(unique[:limit])
    rest = len(unique) - limit
    return shown + (f" 외 {rest}개" if rest > 0 else "")


def listed(groups: Sequence[tuple[str, Sequence[str]]]) -> str:
    """'소조립·대조립 완료, 선행의장 진행 중'(빈 무리는 뺀다)."""
    return ", ".join(f"{joined(names, 7)} {state}" for state, names in groups if names)
