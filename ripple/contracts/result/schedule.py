"""일정 계약(docs/engine.md(비용·일정) 6절): 구역 출구 지연·인도 지연·일정 위험·출구 여유와 그 묶음."""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict, Field, model_validator

from ..base import Frozen, omittable
from ..domain import TransportMode
from .amount import Amount
from .impact import Unresolved
from .vocab import UnresolvedKind


class ZoneExitDelay(Frozen):
    zone_id: str
    zone_name: str = ""  # 지도의 구역 이름(화면용, 예: 화물탱크 구역). 지도에 없으면 빈 값
    exit_activity_id: str
    base_date: date
    new_date: date
    delay_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _days_match(self) -> ZoneExitDelay:
        if (self.new_date - self.base_date).days != self.delay_days:
            raise ValueError("지연 일수와 날짜 차이 불일치")
        return self


class DeliveryImpact(Frozen):
    """경계 조건이 있을 때만 계산한다. 이 변경이 더한 지연 = 후 − 전(화면·설명은 이 필드를 그대로 쓴다).

    1.29.0 허용 지연(명세 4-6): 변경 원인이 선주 요청이면 늘어난 지연은 인도일 조정 대상이라 지체상금 줄이 없다.
    exposure는 인도일 조정에 합의하지 못하면 이 호선에 붙을 수 있는 지체상금(총액에 넣지 않음, 0이면 None)."""

    forecast_delay_before_days: int = Field(ge=0)
    forecast_delay_after_days: int = Field(ge=0)
    added_delay_days: int = Field(ge=0)
    permissible: bool = False
    exposure: Amount | None = None

    @model_validator(mode="after")
    def _consistent(self) -> DeliveryImpact:
        if self.forecast_delay_after_days < self.forecast_delay_before_days:
            raise ValueError("변경 뒤 예상 지연이 변경 전보다 짧음")
        if self.added_delay_days != self.forecast_delay_after_days - self.forecast_delay_before_days:
            raise ValueError("늘어난 인도 지연이 변경 뒤 − 변경 전과 다름")
        if self.exposure is not None and not self.permissible:
            raise ValueError("노출 금액은 허용 지연(선주 요청)일 때만 가능")
        if self.exposure is not None and (self.added_delay_days == 0 or self.exposure.high <= 0):
            raise ValueError("노출 금액은 인도 지연이 늘고 금액이 있을 때만 가능")
        return self

    @classmethod
    def of(cls, before: int, after: int, permissible: bool = False, exposure: Amount | None = None) -> DeliveryImpact:
        return cls(
            forecast_delay_before_days=before,
            forecast_delay_after_days=after,
            added_delay_days=after - before,
            permissible=permissible,
            exposure=exposure,
        )


class TransportLeg(Frozen):
    """일정 위험이 외자재 새 자재 리드타임에 더한 운송 일수 하나(계약 1.33.0, 명세 6-6).

    days = 운송 방식 범위 끝(배율을 곱하지 않음). assumed = 외자재인데 운송 방식이 비어 선박으로 가정한 수요가 있음."""

    mode: TransportMode
    days: int = Field(gt=0)
    assumed: bool = False


class ScheduleRisk(Frozen):
    """일정 위험(docs/engine.md(비용·일정) 6-6): 새 자재 리드타임을 분류별 범위 끝으로 잡은 확정일 일정.

    대표 일정(ScheduleImpact 본문)은 그대로 두고 따로 보인다. 비용·곡선·보류 권고·대안은 대표 일정만 쓰고, 판정은
    검토 필요 이유 하나(대표 0일·위험에서만 늦는 출구, 명세 8-4)에만 쓴다.
    zone_exits는 0일보다 늦는 출구만(출구 ID 순) — 목록에 없는 출구의 위험 지연은 0일이다.
    """

    # 비면 직렬화에서 빠지는 transport: 응답 스키마에서 필수도 기본값도 아니게(AnalysisResult.prechecks와 같은 방식)
    model_config = ConfigDict(json_schema_extra=omittable("transport"))

    ratios: dict[str, float] = Field(default_factory=dict)  # 늦춘 새 자재 분류 → 리드타임 배율(범위 끝 ÷ 대표값)
    zone_exits: tuple[ZoneExitDelay, ...] = ()
    max_exit_delay_days: int = Field(default=0, ge=0)
    delivery: DeliveryImpact | None = None  # None = 계산 불가(대표에서 불가였거나 위험 일정에서만 생긴 이유)
    unresolved: tuple[Unresolved, ...] = ()  # 위험 일정에서만 생긴 계산 불가 사유(대표 unresolved·판정에 넣지 않음)
    # 1.33.0 외자재 운송: 위험 일정이 리드타임에 더한 운송 일수(방식 순). 비면 직렬화에서 빠져 그 필드가 없던 기록
    # 본문의 기록 ID(본문 해시)가 그대로다
    transport: tuple[TransportLeg, ...] = Field(default=(), exclude_if=lambda legs: not legs)

    @model_validator(mode="after")
    def _consistent(self) -> ScheduleRisk:
        if any(ratio < 1 for ratio in self.ratios.values()):
            raise ValueError("리드타임 위험 배율은 1 이상 필요")
        modes = [leg.mode for leg in self.transport]
        if modes != sorted(set(modes)):
            raise ValueError("위험 일정의 운송 일수는 운송 방식 순·중복 없음 필요")
        ids = [z.exit_activity_id for z in self.zone_exits]
        if ids != sorted(set(ids)):
            raise ValueError("위험 일정의 구역 출구는 출구 ID 순·중복 없음 필요")
        if any(z.delay_days <= 0 for z in self.zone_exits):
            raise ValueError("위험 일정의 구역 출구는 0일보다 늦는 것만 가능")
        if self.max_exit_delay_days != max((z.delay_days for z in self.zone_exits), default=0):
            raise ValueError("위험 일정의 구역 출구 최대 지연과 구역 출구 지연 불일치")
        if any(u.kind is not UnresolvedKind.DELIVERY for u in self.unresolved):
            raise ValueError("위험 일정에서만 생기는 계산 불가는 인도 지연만 가능")
        return self


class ExitMargin(Frozen):
    """늦어지지 않았지만 이 변경으로 선행 조건이 늦어져 여유가 줄어든 구역 출구(명세 6-7, 계약 1.26.0).

    정보이며 판정에 쓰지 않는다."""

    zone_id: str
    zone_name: str = ""  # 지도의 구역 이름(화면용). 지도에 없으면 빈 값
    exit_activity_id: str
    margin_days: int = Field(
        ge=0
    )  # 변경 뒤 출구 착수일 − 변경 뒤 선행 조건(0 = 이 변경이 출구를 구동하지만 아직 안 늦춤)


class ScheduleImpact(Frozen):
    added_days_by_activity: dict[str, int] = Field(default_factory=dict)
    zone_exits: tuple[ZoneExitDelay, ...] = ()
    max_exit_delay_days: int = Field(default=0, ge=0)  # 구역 출구 지연의 최댓값(없으면 0)
    delivery: DeliveryImpact | None = None  # None이면 계산 불가(이유는 AnalysisResult.unresolved)
    critical_path_before: tuple[str, ...] = ()
    critical_path_after: tuple[str, ...] = ()
    risk: ScheduleRisk | None = None  # 일정 위험(엔진 0.5.0부터 — None은 계산하지 않은 이전 판 결과)
    exit_margins: tuple[ExitMargin, ...] = ()  # 여유가 줄어든 출구(1.26.0, 출구 ID 순, 지연 출구와 겹치지 않음)

    @model_validator(mode="after")
    def _max_exit(self) -> ScheduleImpact:
        if self.max_exit_delay_days != max((z.delay_days for z in self.zone_exits), default=0):
            raise ValueError("구역 출구 최대 지연과 구역 출구 지연 불일치")
        margin_ids = [m.exit_activity_id for m in self.exit_margins]
        if margin_ids != sorted(set(margin_ids)):
            raise ValueError("여유가 줄어든 구역 출구는 출구 ID 순·중복 없음 필요")
        if set(margin_ids) & {z.exit_activity_id for z in self.zone_exits}:
            raise ValueError("늦어진 구역 출구는 여유 목록에 불가")
        problem = _risk_problem(self)
        if problem:
            raise ValueError(problem)
        return self


def _risk_problem(schedule: ScheduleImpact) -> str | None:
    """위험 일정은 대표보다 이르지 않다: 대표에서 늦는 출구는 모두 위험 목록에 같은 출구 ID로 있고 지연이 같거나 크다
    (빠짐·다른 출구로 대체를 거부 — 목록에 없으면 0일이라). 인도는 둘 다 계산됐을 때만 비교한다."""
    risk = schedule.risk
    if risk is None:
        return None
    by_exit = {z.exit_activity_id: z for z in risk.zone_exits}
    for z in schedule.zone_exits:
        if z.delay_days <= 0:
            continue
        found = by_exit.get(z.exit_activity_id)
        if found is None:
            return f"대표 일정에서 늦는 구역 출구 {z.exit_activity_id}가 위험 일정에 없음"
        if found.delay_days < z.delay_days:
            return f"구역 출구 {z.exit_activity_id}의 위험 지연이 대표보다 짧음"
        if found.zone_id != z.zone_id or found.base_date != z.base_date:
            return f"구역 출구 {z.exit_activity_id}의 구역·기준일이 대표와 다름"
    if (
        schedule.delivery is not None
        and risk.delivery is not None
        and risk.delivery.added_delay_days < schedule.delivery.added_delay_days
    ):
        return "위험 일정의 늘어난 인도 지연이 대표보다 짧음"
    return None
