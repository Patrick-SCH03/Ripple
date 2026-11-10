// 결정 기한(추가손실 0 마지막 날) 카드의 보조 설명과 '확정일을 결정 기한으로' 안내(DESIGN.md 6절, docs/domain.md 7절).
// 숫자는 곡선(timing.curve)의 추가손실과 요청의 기준일·확정일만 쓴다 — 날짜를 화면에서 만들지 않는다.
import type { AnalysisResult, Amount, CurvePoint, ZeroLossDeadline } from '@/api/client'
import { addDays, formatDay, isWeekend } from './format'
import { formatMoney } from './money'

function pointOn(curve: readonly CurvePoint[], day: string): CurvePoint | undefined {
  return curve.find((point) => point.confirm_on === day)
}

/** 추가손실 한 마디: 대표값이 있으면 그 값, 대표값은 0이고 최대만 있으면 '최대 n'. 늘지 않으면 null. */
export function lossText(loss: Amount): string | null {
  if (loss.value > 0) return formatMoney(loss.value)
  if (loss.high > 0) return `최대 ${formatMoney(loss.high)}`
  return null
}

/** 기준일부터 그날까지 곡선이 모두 0이면 '추가손실 0', 줄어드는 날이 있으면 '추가손실 없음'(0이라고 쓰지 않게). */
function unchanged(curve: readonly CurvePoint[], lastDay: string): string {
  const flat = curve
    .filter((point) => point.confirm_on <= lastDay)
    .every((point) => point.additional_loss.low === 0 && point.additional_loss.high === 0)
  return flat ? '추가손실 0' : '추가손실 없음'
}

/**
 * 결정 기한이 토·일일 때 그 앞 마지막 근무일(서버 결재 계획 decide_by_workday — 날짜를 화면에서 만들지 않는다).
 * 날짜로 정한 결정 기한(by_date)이고 그날이 기준일 이후·결정 기한 앞일 때만 — 평일 기한이면 같은 날이라 null, 기준일
 * 뒤에 근무일이 없으면(기준일 토요일·기한 일요일) 지난 금요일을 권하지 않게 null. 옛 응답(값 없음)도 null.
 */
export function deadlineWorkday(result: Pick<AnalysisResult, 'timing' | 'request' | 'approval_plan'>): string | null {
  const { kind, last_day: lastDay } = result.timing.deadline
  const workday = result.approval_plan?.decide_by_workday
  if (kind !== 'by_date' || !workday || workday >= lastDay || workday < result.request.as_of) return null
  return workday
}

/**
 * 마감일 카드의 보조 설명 한 줄: 그날까지 확정하면 기준일 확정과 비용이 같고, 다음 날부터 얼마 늘어나는지.
 * '오늘'(기준일에 확정해야 함)은 내일부터 늘어나는 금액, '기간 안 없음'은 탐색 기간 끝까지 언제 확정해도 같다는 것.
 * 결정 기한이 주말이면(workday = deadlineWorkday) 끝에 '근무일 기준 11월 6일(금)'을 덧붙인다(D-n·날짜는 그대로).
 */
export function deadlineDetail(deadline: ZeroLossDeadline, curve: readonly CurvePoint[], workday: string | null = null): string {
  const { kind, last_day: lastDay } = deadline
  if (kind === 'none_in_horizon') return `${formatDay(lastDay)}까지 언제 확정해도 ${unchanged(curve, lastDay)}`
  const next = pointOn(curve, addDays(lastDay, 1))
  const grows = next ? lossText(next.additional_loss) : null
  // '최대 n'이면 '최대 +n'(결정 도우미 lib/brief plusLoss와 같은 표기)
  const rise = grows ? (grows.startsWith('최대 ') ? `최대 +${grows.slice('최대 '.length)}` : `+${grows}`) : '늘어남'
  if (kind === 'confirm_now') return `내일부터 ${rise}`
  const weekday = workday ? ` · 근무일 기준 ${formatDay(workday)}` : ''
  return `${formatDay(lastDay)}까지 ${unchanged(curve, lastDay)} · 다음 날부터 ${rise}${weekday}`
}

/**
 * 지금 확정일과 마감일의 관계(표시 중인 결과의 요청 기준). 단추가 가리키는 날(to)은 결정 기한 — 기한이 토·일이면
 * 그 앞 마지막 근무일(deadlineWorkday, 서버 decide_by_workday)이라 주말 확정을 권하지 않는다.
 * later: 확정일이 그날 앞 — 그날까지 미뤄도 비용이 같아 '확정일을 ○월 ○일로'를 권한다.
 * on: 확정일이 그날부터 결정 기한 사이(at = 결정 기한 그날 · 근무일 기준 그날 · 그 사이 주말).
 * past: 확정일이 결정 기한 뒤 — 그날 추가손실(곡선 밖이면 null)과 '결정 기한으로 당기기'(그날로).
 * 결정 기한이 토·일인데 근무일이 없으면(기준일 토요일 · 기한 일요일처럼 기준일 뒤에 근무일이 없어 서버가 비움, 옛 응답)
 * 주말 날짜를 권하지 않게 단추 없이 상태 줄만('확정일 · 결정 기한 안').
 * '기간 안 없음'은 마감일이 탐색 기간 끝일 뿐이라 안내하지 않는다.
 */
export type DeadlineGuide =
  | { kind: 'later'; to: string }
  | { kind: 'on'; at: 'deadline' | 'workday' | 'within' }
  | { kind: 'past'; to: string; confirmOn: string; loss: string | null }

export function deadlineGuide(result: AnalysisResult): DeadlineGuide | null {
  const { kind, last_day: lastDay } = result.timing.deadline
  if (kind === 'none_in_horizon') return null
  const confirmOn = result.request.confirm_on ?? result.request.as_of
  const workday = deadlineWorkday(result)
  const to = workday ?? lastDay
  if (confirmOn === lastDay) return kind === 'by_date' ? { kind: 'on', at: 'deadline' } : null // '오늘'은 기본값이라 따로 적지 않는다
  if (confirmOn < to) return workday === null && isWeekend(lastDay) ? { kind: 'on', at: 'within' } : { kind: 'later', to }
  if (confirmOn < lastDay) return { kind: 'on', at: confirmOn === to ? 'workday' : 'within' }
  const point = pointOn(result.timing.curve, confirmOn)
  return { kind: 'past', to, confirmOn, loss: point ? lossText(point.additional_loss) : null }
}

const ON_TEXT: Record<Extract<DeadlineGuide, { kind: 'on' }>['at'], string> = {
  deadline: '확정일 = 결정 기한',
  workday: '확정일 = 결정 기한(근무일 기준)',
  within: '확정일 · 결정 기한 안',
}

/**
 * '확정일을 ○월 ○일로'를 누르기 전의 확정일(되돌리기). confirm은 그때 요청의 confirm_on(null = 비워 둔 기준일),
 * day는 화면에 적을 날, to는 단추가 옮긴 확정일. 같은 설계변경이고 지금 확정일이 단추가 옮긴 그날일 때만 되돌리기를
 * 보인다(showUndo) — 다시 분석이 실패해 확정일이 그대로였다가 나중에 손으로 다른 날로 바꾸면, 그 확정일은 단추가
 * 옮긴 것이 아니라 되돌리기를 내지 않는다.
 */
export interface DeadlineUndo {
  ecn: string | null
  confirm: string | null
  day: string
  to: string
}

export function undoOf(result: AnalysisResult, to: string): DeadlineUndo {
  const { change, confirm_on: confirm, as_of: asOf } = result.request
  return { ecn: change.ecn_id ?? null, confirm: confirm ?? null, day: confirm ?? asOf, to }
}

export function showUndo(undo: DeadlineUndo | null, result: AnalysisResult): undo is DeadlineUndo {
  if (!undo) return false
  const { change, confirm_on: confirm, as_of: asOf } = result.request
  return undo.ecn === (change.ecn_id ?? null) && undo.confirm !== (confirm ?? null) && (confirm ?? asOf) === undo.to
}

/** 안내 글: 상태 한 줄(명사형)과 단추 이름. 단추는 확정일을 바꿀 수 있을 때만 화면이 그린다. */
export function guideText(
  guide: DeadlineGuide,
  kind: ZeroLossDeadline['kind'],
): { status: string | null; button: string | null } {
  if (guide.kind === 'later') return { status: null, button: `확정일을 ${formatDay(guide.to)}로` }
  if (guide.kind === 'on') return { status: ON_TEXT[guide.at], button: null }
  return {
    status: `확정일 ${formatDay(guide.confirmOn)} · ${guide.loss ? `그날 추가손실 ${guide.loss}` : '결정 기한 지남'}`,
    button: kind === 'confirm_now' ? '오늘로 당기기' : '결정 기한으로 당기기',
  }
}
