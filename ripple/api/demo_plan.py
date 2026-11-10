"""합성 시연 기록 시드의 각본(docs/operations.md(서비스) 7절): 누가 · 언제 · 어느 설계변경에 무엇을 했나.

숫자는 없다 — 금액·마감·처리 시간·실적은 시드(demo_seed.py)가 엔진과 숨긴 모델로 계산한다. 여기에는 사람, 날짜(오늘부터
며칠 전 · 그날 업무 시작 뒤 몇 분), 행동, 사람이 적는 사유·메모와 요청 값(대안 포함 · 설계 승인 상태 · 변경 원인)만
둔다.

- 설계변경: 화면 샘플(개발 분할 18건)에서 시연용 네 건(RESERVED)을 뺀 14건 + 샘플 밖 세 건(EXTRA). 샘플 가운데 더 싼
  충족 대안이 있는 건은 ECN-D-0119(시연용)뿐이라, 결재함 '더 저렴한 대안'이 보이게 같은 개발 분할의 ECN-D-0067을 더했다.
  무비용(비용 줄이 도면 개정뿐) 건은 샘플에 없어 ECN-D-0015(담당자 처리 뒤 실행)·ECN-D-0007(기록만 — 현장 시연에서
  '담당자 처리')을 더했다(업무 화면에서는 목록 아래 '기록된 다른 설계변경'으로 보인다).
- 결재선(docs/records.md(기록·결재) 14절): 추가 비용 건은 파트장 → 팀장 → 본부장. 지금 걸린 건은 단계가 섞이게
  둔다 — 파트장 대기 · 파트장 승인 뒤 팀장 대기(보류 하나 포함) · 팀장 승인 뒤 본부장 대기. 지난 건에는 팀장 전결도.
- 실시간 시연 세계는 날마다 지도가 새로 만들어져 검토 요청·승인은 기록한 그날(같은 지도)에만 받는다.
  그래서 기록 → 검토 요청 → 결재선 → 실행 시작은 같은 날에 두고, 날을 넘기는 것은 종료·실적과 반려 뒤 다시 기록뿐이다.
- 사람: 담당자 김설계·팀장 박팀장과 결재선의 이파트장·최본부장은 빠른 로그인 고정 계정(ripple/auth/quick.py)과 같은
  사람(화면 단추는 김설계·이파트장 둘), 이서준·정다은은 가상 담당자(계정 파일에 비밀번호를 쓸 수 없는 계정으로
  둔다).
  결재선 두 계정은 시작할 때마다 맞춘다(demo_seed.sync_approvers).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ripple.auth.quick import QUICK_ACCOUNTS
from ripple.contracts.auth import Role, StaffRole
from ripple.contracts.change import ChangeCause, ChangeIntent, DesignStatus
from ripple.contracts.records import EcnAction

# 기록을 남기지 않고 비워 두는 설계변경: 위 막대 시연 시나리오·현장 시연(ECN-D-0043·ECN-D-0119)과 팀 데모 사례·외자재
# 운송 시연 건(samples.DEMO_ECNS의 ECN-D-0045·ECN-D-0130)
RESERVED = ("ECN-D-0043", "ECN-D-0119", "ECN-D-0045", "ECN-D-0130")
EXTRA = ("ECN-D-0067", "ECN-D-0015", "ECN-D-0007")  # 샘플 밖에서 더한 설계변경(위 설명)
WORK_START_MINUTES = 8 * 60 + 30  # 그날 업무 시작 08:30(KST)
WORK_MINUTES = 570  # 08:30~18:00

# 담당자가 기록할 때 적는 변경 원인(요청 값, 비워 두면 결정 대화상자가 '미입력' 경고): 설계변경의 의도에서 고른다 —
# 강도·간섭·중량은 사내 설계, 규칙은 선급·규정. 선주 요청은 계산에도 쓰인다(허용 지연, docs/domain.md 14절)
CAUSE_OF_INTENT: Mapping[ChangeIntent, ChangeCause] = {
    ChangeIntent.STRENGTH: ChangeCause.DESIGN_ERROR,
    ChangeIntent.INTERFERENCE: ChangeCause.DESIGN_ERROR,
    ChangeIntent.WEIGHT: ChangeCause.DESIGN_ERROR,
    ChangeIntent.OWNER_REQUEST: ChangeCause.OWNER_REQUEST,
    ChangeIntent.RULE_CHANGE: ChangeCause.CLASS_RULE,
    ChangeIntent.EQUIPMENT: ChangeCause.EQUIPMENT,
}


@dataclass(frozen=True, slots=True)
class Person:
    login_id: str
    name: str
    role: StaffRole


MEMBER = Person(*QUICK_ACCOUNTS[Role.MEMBER], Role.MEMBER)  # 김설계 quick-member
LEAD = Person(*QUICK_ACCOUNTS[Role.ADMIN], Role.ADMIN)  # 박팀장 quick-lead
SEOJUN = Person("seed-seojun", "이서준", Role.MEMBER)
DAEUN = Person("seed-daeun", "정다은", Role.MEMBER)
SEED_PEOPLE = (SEOJUN, DAEUN)  # 계정 파일에 넣는 가상 담당자(비밀번호를 쓸 수 없음)
PART = Person(*QUICK_ACCOUNTS[Role.PART_LEAD], Role.PART_LEAD)  # 이파트장 part-lead
EXEC = Person(*QUICK_ACCOUNTS[Role.EXECUTIVE], Role.EXECUTIVE)  # 최본부장 executive
APPROVERS = (PART, EXEC)  # 결재선 가상 계정(빠른 로그인 '파트장으로'·'본부장으로' 단추와 같은 계정)


@dataclass(frozen=True, slots=True)
class Step:
    """한 행동. action이 None이면 실적 입력. day = 오늘부터 며칠(0 = 오늘, 음수 = 지난날), minute = 업무 시작 뒤 분."""

    day: int
    minute: int
    action: EcnAction | None
    who: Person
    reason: str | None = None
    design: DesignStatus | None = None  # 기록할 때 요청에 적는 설계 승인 상태
    note: str = ""  # 실적 메모
    delay: bool = True  # 실적에 구역 출구 지연을 넣나(모르면 비움)


@dataclass(frozen=True, slots=True)
class Case:
    ecn_id: str
    steps: tuple[Step, ...]
    alternatives: bool = False  # 대안 포함으로 기록(강도형 요청)


def rec(day: int, minute: int, who: Person, design: DesignStatus | None = None) -> Step:
    return Step(day, minute, EcnAction.RECORD, who, design=design)


def ask(day: int, minute: int, who: Person) -> Step:
    return Step(day, minute, EcnAction.REQUEST_REVIEW, who)


def sign(day: int, minute: int, who: Person, reason: str | None = None) -> Step:
    """결재선 한 단계 승인(지금 단계의 결재자 또는 팀장 전결)."""
    return Step(day, minute, EcnAction.APPROVE, who, reason)


def line(day: int, minute: int, reason: str | None = None, *, last: Person = EXEC) -> tuple[Step, ...]:
    """결재선 끝까지 승인: 파트장 → 팀장(사유) → 본부장(last = LEAD면 팀장 전결). 단계마다 40분 뒤."""
    return sign(day, minute, PART), sign(day, minute + 40, LEAD, reason), sign(day, minute + 80, last)


def no(day: int, minute: int, reason: str, who: Person = LEAD) -> Step:
    return Step(day, minute, EcnAction.REJECT, who, reason)


def wait(day: int, minute: int, reason: str, who: Person = LEAD) -> Step:
    return Step(day, minute, EcnAction.HOLD, who, reason)


def settle(day: int, minute: int, who: Person, reason: str) -> Step:
    """무비용 담당자 처리(비용 줄이 도면 개정뿐 — 결재선 없이 승인)."""
    return Step(day, minute, EcnAction.SETTLE, who, reason)


def go(day: int, minute: int, who: Person) -> Step:
    return Step(day, minute, EcnAction.START, who)


def done(day: int, minute: int, who: Person) -> Step:
    return Step(day, minute, EcnAction.CLOSE, who)


def actual(day: int, minute: int, who: Person, note: str, *, delay: bool = True) -> Step:
    return Step(day, minute, None, who, note=note, delay=delay)


SETTLED = "작업 완료 · 정산 확정"
SETTLED_OPEN = "작업 완료 · 정산 확정(종료 처리 전)"
TRIP = "본부장 출장 중 — 팀장 전결"

PLAN: tuple[Case, ...] = (
    # 종료(실적 있음)
    Case(
        "ECN-D-0065",
        (
            rec(-24, 40, SEOJUN),
            ask(-24, 95, SEOJUN),
            *line(-24, 200),
            go(-24, 400, SEOJUN),
            done(-15, 450, SEOJUN),
            actual(-15, 480, SEOJUN, SETTLED),
        ),
    ),
    Case(
        "ECN-D-0009",
        (
            rec(-21, 25, MEMBER),
            ask(-21, 70, MEMBER),
            *line(-21, 130, last=LEAD),  # 본부장 단계 팀장 전결
            go(-21, 300, MEMBER),
            done(-12, 410, MEMBER),
            actual(-12, 440, MEMBER, SETTLED),
        ),
        alternatives=True,
    ),
    Case(
        "ECN-D-0157",
        (
            rec(-19, 60, DAEUN, DesignStatus.IN_REVIEW),
            ask(-19, 110, DAEUN),
            sign(-19, 180, PART),
            no(-19, 290, "설계 검토 미완료 변경 — 승인 도면 수령 후 재상신"),
            rec(-17, 50, DAEUN, DesignStatus.APPROVED),
            ask(-17, 80, DAEUN),
            *line(-17, 120),
            go(-17, 280, DAEUN),
            done(-9, 380, DAEUN),
            actual(-9, 400, DAEUN, SETTLED),
        ),
    ),
    Case(
        "ECN-D-0038",
        (
            rec(-14, 15, MEMBER),
            ask(-14, 35, MEMBER),
            sign(-14, 60, PART),
            sign(-14, 90, LEAD, "오늘 확정 시 추가손실 없음 — 바로 승인"),
            sign(-14, 110, LEAD, TRIP),  # 본부장 단계 팀장 전결
            go(-14, 160, MEMBER),
            done(-6, 420, MEMBER),
            actual(-6, 450, MEMBER, SETTLED),
        ),
    ),
    # 실행 중
    Case(
        "ECN-D-0099",
        (
            rec(-10, 90, SEOJUN),
            ask(-10, 140, SEOJUN),
            *line(-10, 220),
            go(-10, 420, SEOJUN),
            actual(-3, 300, SEOJUN, SETTLED_OPEN),
        ),
    ),
    Case(
        "ECN-D-0001",
        (
            rec(-8, 30, MEMBER),
            ask(-8, 60, MEMBER),
            sign(-8, 100, PART),
            wait(-8, 150, "같은 강재 재고 전용 가능 여부 — 자재팀 회신 대기"),
            sign(-8, 380, LEAD, "재고 전용 가능 회신 받음"),
            sign(-8, 420, EXEC),
            go(-8, 470, MEMBER),
            actual(-2, 330, MEMBER, SETTLED_OPEN),
        ),
        alternatives=True,
    ),
    Case("ECN-D-0020", (rec(-6, 45, DAEUN), ask(-6, 100, DAEUN), *line(-6, 200), go(-6, 450, DAEUN))),
    # 무비용 담당자 처리(결재선 없음) 뒤 실행
    Case(
        "ECN-D-0015",
        (
            rec(-5, 60, SEOJUN),
            settle(-5, 90, SEOJUN, "도면 개정만 있는 변경 — 담당자 처리"),
            go(-5, 120, SEOJUN),
        ),
    ),
    # 승인(실행 전)
    Case("ECN-D-0068", (rec(-2, 70, SEOJUN), ask(-2, 120, SEOJUN), *line(-2, 250))),
    # 반려(지금) — 같은 블록을 더 얇게 다시 올린 것이 오늘 검토 중인 ECN-D-0067
    Case(
        "ECN-D-0173",
        (
            rec(-4, 55, MEMBER),
            ask(-4, 85, MEMBER),
            no(-4, 200, "두께 증가 폭 과다 — 강도 검토로 최소 두께 재산정 후 재상신", PART),
        ),
    ),
    # 팀장 단계 보류(지금): 파트장 승인 뒤 팀장이 보류
    Case(
        "ECN-D-0021",
        (
            rec(0, 20, DAEUN),
            ask(0, 60, DAEUN),
            sign(0, 120, PART),
            wait(0, 200, "대체 밸브 납기 협력사 문의 중 — 회신 후 결정"),
        ),
    ),
    # 팀장 대기(지금): 파트장 승인 뒤
    Case("ECN-D-0067", (rec(0, 100, MEMBER), ask(0, 130, MEMBER), sign(0, 170, PART)), alternatives=True),
    Case("ECN-D-0131", (rec(0, 150, SEOJUN), ask(0, 210, SEOJUN), sign(0, 250, PART))),
    # 파트장 대기(지금)
    Case("ECN-D-0016", (rec(0, 240, DAEUN), ask(0, 300, DAEUN))),
    # 본부장 대기(지금): 팀장 승인 뒤
    Case(
        "ECN-D-0106",
        (rec(0, 260, DAEUN), ask(0, 280, DAEUN), sign(0, 320, PART), sign(0, 360, LEAD, "공정 영향 작음 — 승인")),
    ),
    # 기록만(분석)
    Case("ECN-D-0037", (rec(-1, 400, SEOJUN),), alternatives=True),
    Case("ECN-D-0007", (rec(0, 380, MEMBER),)),  # 무비용 — 담당자 처리 전(현장 시연)
)
