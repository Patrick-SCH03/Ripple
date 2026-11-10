// 분석 결과 → 첫 화면 요약(DESIGN.md 2·6절): 핵심 수치 카드, 해야 할 일, 비용 줄 순서, 곡선 계단.
// 숫자는 모두 결과 필드에서 오고, 여기서는 고르고 D-n·표기만 바꾼다.
import type {
  AnalysisResult,
  ApprovalPlan,
  CostLine,
  CurvePoint,
  HoldAdvice,
  OnboardOption,
  Reallocation,
  ZeroLossDeadline,
} from '@/api/client'
import { approvalHoldText } from './approvalHold'
import { deadlineDetail, deadlineWorkday } from './deadline'
import { delayRippleLine } from './delayRipple'
import { daysBetween, formatDay } from './format'
import { codeOf, zoneName } from './labels'
import { scheduleRiskBasis } from './schedule'
import { formatMoney, formatRange } from './money'

/** D-3 이하는 위험 색(DESIGN.md 6절). */
export const URGENT_DAYS = 3

export type Tone = 'neutral' | 'danger' | 'success'

export interface KeyNumber {
  id: 'total' | 'deadline' | 'ordered' | 'exit' | 'delivery'
  label: string
  value: string
  detail?: string
  /** 주의 한 줄(경고 색): 결정 기한까지 금액은 그대로여도 일정이 늦어질 때. */
  caution?: string
  /** 총액 밖 금액 한 줄(경고 색, 1.32.0): 구역 출구 카드의 지연 파급 비용(가정) — 지체상금 노출 금액과 같은 방식. */
  outside?: string
  /** 상세 카드에 싣는 짧은 주의(범위 없이) — caution이 범위를 품을 때만. 요약 복사·리포트는 caution 그대로. */
  brief?: string
  tone: Tone
}

/** 결정 기한 한 단어: 날짜 · '오늘' · '기간 안 없음'. */
export function deadlineText(deadline: ZeroLossDeadline): string {
  if (deadline.kind === 'confirm_now') return '오늘'
  if (deadline.kind === 'none_in_horizon') return '기간 안 없음'
  return formatDay(deadline.last_day)
}

/**
 * 마감일까지 늦출 때 일정: 금액(추가손실)은 그대로여도 구역 출구 지연이 늘면 기준일·마감일의 지연 일수.
 * 늘지 않거나 곡선에 그날이 없으면 null.
 */
export function exitSlip(curve: readonly CurvePoint[], lastDay: string): { from: number; to: number } | null {
  const first = curve[0]
  const until = curve.find((point) => point.confirm_on === lastDay)
  if (!first || !until || until.max_exit_delay_days <= first.max_exit_delay_days) return null
  return { from: first.max_exit_delay_days, to: until.max_exit_delay_days }
}

/**
 * 마감일 카드의 주의 한 줄: 금액은 그대로여도 늦출수록 구역 출구 지연이 는다는 것(일수는 곡선의 기준일·마감일 값).
 * 실무자가 한눈에 읽게 짧게. '추가손실 0'(총변경비용)과 함께 읽혀 '늦춰도 괜찮다'로 오해하지 않게 비용과 일정을 맞세운다
 * (구역 출구가 밀려 드는 지연 파급 비용은 총액 밖 — 구역 출구 카드).
 */
export function slipText(slip: { from: number; to: number }, lastDay: string): string {
  const until = `${formatDay(lastDay)} 확정 시`
  if (slip.from === 0) return `비용 변동 없어도 일정 악화 · 출구 지연 생김(${until} ${slip.to}일)`
  return `비용 변동 없어도 일정 악화 · 출구 지연 기준일 ${slip.from}일 → ${until} ${slip.to}일`
}

/**
 * 구역 출구 카드의 일정 위험 한 줄: 새 자재가 리드타임 범위 끝에 오면 최대 며칠인지(늦춘 분류·배율, 외자재 운송 일수 —
 * 일정 탭·리포트의 위험 설명 줄과 같은 근거, schedule.scheduleRiskBasis). 위험이 없거나(이전 판 결과) 대표보다 크지 않으면 null.
 */
export function exitRiskText(schedule: AnalysisResult['schedule']): string | null {
  const risk = schedule.risk
  const most = risk?.max_exit_delay_days ?? 0
  if (!risk || most <= schedule.max_exit_delay_days) return null
  const basis = scheduleRiskBasis(risk)
  // 일정 탭·리포트와 같은 이름('자재가 늦게 오면')을 쓴다 — 같은 숫자에 이름이 둘이면 헷갈린다
  return basis.length > 0 ? `자재가 늦게 오면 최대 ${most}일(${basis.join(' · ')})` : `자재가 늦게 오면 최대 ${most}일`
}

/** 핵심 수치 카드(2~4개). 0이거나 해당 없음이면 카드를 내지 않는다. */
export function keyNumbers(result: AnalysisResult): KeyNumber[] {
  const { total, timing, schedule, request } = result
  const cards: KeyNumber[] = [
    {
      id: 'total',
      label: '총변경비용',
      value: formatMoney(total.value),
      detail: total.low === total.high ? undefined : formatRange(total.low, total.high),
      tone: 'neutral',
    },
  ]
  const { kind, last_day: lastDay } = timing.deadline
  const slip = kind === 'confirm_now' ? null : exitSlip(timing.curve, lastDay)
  const caution = slip ? slipText(slip, lastDay) : undefined
  // 보조 설명: 그날까지 확정하면 비용 그대로 · 다음 날부터 얼마 늘어나는지(곡선 값, lib/deadline), 기한이 주말이면 근무일 기준 날
  const detail = deadlineDetail(timing.deadline, timing.curve, deadlineWorkday(result))
  if (kind === 'by_date') {
    const days = daysBetween(request.as_of, lastDay) ?? 0
    cards.push({
      id: 'deadline',
      label: '결정 기한',
      value: `D-${days}`,
      detail,
      caution,
      tone: days <= URGENT_DAYS ? 'danger' : 'neutral',
    })
  } else if (kind === 'confirm_now') {
    cards.push({ id: 'deadline', label: '결정 기한', value: '오늘', detail, tone: 'danger' })
  } else {
    cards.push({ id: 'deadline', label: '결정 기한', value: '기간 안 없음', detail, caution, tone: 'success' })
  }
  const worst = schedule.zone_exits.find((exit) => exit.delay_days === schedule.max_exit_delay_days)
  const late = schedule.max_exit_delay_days > 0 && worst !== undefined
  // 일정 위험이 대표보다 크면 대표 0일이어도 카드를 낸다(결정에 필요한 '없음' — DESIGN.md 2절)
  const riskCaution = exitRiskText(schedule)
  if (late || riskCaution) {
    cards.push({
      id: 'exit',
      label: '구역 출구 예상 최대 지연',
      value: `${schedule.max_exit_delay_days}일`,
      detail: late
        ? `${zoneName(worst)} 출구 ${formatDay(worst.base_date)} → ${formatDay(worst.new_date)}`
        : '대표 일정으로는 지연 없음',
      caution: riskCaution ?? undefined,
      outside: delayRippleLine(result) ?? undefined,
      tone: late ? 'danger' : 'neutral',
    })
  }
  const delivery = schedule.delivery
  const added = delivery?.added_delay_days ?? 0
  if (added > 0 && delivery?.permissible) {
    // 선주 요청(허용 지연, 명세 4-6): 지체상금 줄이 없고, 합의하지 못할 때의 금액만 주의로 보인다
    const exposure = delivery.exposure
    cards.push({
      id: 'delivery',
      label: '늘어난 예상 인도 지연',
      value: `${added}일`,
      detail: '선주 요청 · 인도일 조정 대상(지체상금 제외)',
      caution: exposure
        ? `합의 불발 시 지체상금 ${formatMoney(exposure.value)}(${formatRange(exposure.low, exposure.high)})`
        : undefined,
      brief: exposure ? `합의 불발 시 지체상금 ${formatMoney(exposure.value)}` : undefined,
      tone: 'danger',
    })
  } else if (added > 0) {
    const damages = result.cost_lines
      .filter((line) => line.rule_id === 'R-L01')
      .sort((a, b) => b.amount.value - a.amount.value)[0]
    cards.push({
      id: 'delivery',
      label: '늘어난 예상 인도 지연',
      value: `${added}일`,
      detail: damages ? `지체상금 ${formatMoney(damages.amount.value)}` : '유예 기간 안 · 지체상금 없음',
      tone: 'danger',
    })
  }
  return cards
}

/**
 * 결정 기한이 아닌 카드(구역 출구 · 인도 · 옛 기록의 총변경비용 · 이미 발주된 품목)의 보조 한 줄: 행동이 바뀌는 것 하나만 —
 * 주의(경고 색)가 있으면 그것, 없으면 보조 설명. 범위(총변경비용 '1,236만~1억 250만원')는 싣지 않는다(비용 탭·검토서).
 */
export function cardLine(card: KeyNumber): { text: string; tone: 'warning' | 'neutral' } | null {
  if (card.id === 'total') return null
  const caution = card.brief ?? card.caution
  if (caution) return { text: caution, tone: 'warning' }
  return card.detail ? { text: card.detail, tone: 'neutral' } : null
}

export type Todo =
  | { kind: 'held'; poId: string; days: number }
  | { kind: 'hold'; advice: HoldAdvice }
  | { kind: 'onboard'; option: OnboardOption }
  | { kind: 'consult'; poIds: string[] }
  | { kind: 'reallocation'; item: Reallocation }

/**
 * 발주 변경·취소 손실 줄(높은 값 > 0)이 있는 발주, ID 순 — 서버 ripple/explain/render.py po_loss_pos와 같은 정의.
 * 줄 ID 끝은 발주 품목 ID('{발주 ID}#{품목 번호}')이고 발주 ID에도 #가 올 수 있어 마지막 #에서 자른다.
 */
function lossPos(result: AnalysisResult): string[] {
  const marker = ':po_change:'
  const ids = result.cost_lines
    .filter((line) => line.line_id.includes(marker) && line.amount.high > 0)
    .map((line) => {
      const poLine = line.line_id.slice(line.line_id.indexOf(marker) + marker.length)
      return poLine.slice(0, poLine.lastIndexOf('#'))
    })
  return [...new Set(ids)].sort()
}

/**
 * 해야 할 일: 적용한 보류(권고가 사라져도 빼기 단추가 남게) → 아직 적용하지 않은 보류 권고 → 후행 설치
 * 선택지(명세 6-8) → 발주 손실 보상 협의(하도급법 8조, 공정위 위탁취소 심사지침) → 자재 전용.
 */
export function todos(result: AnalysisResult): Todo[] {
  const consult = lossPos(result)
  const onboard = result.onboard
  return [
    ...result.request.holds.map((hold): Todo => ({ kind: 'held', poId: hold.po_id, days: hold.hold_days })),
    ...result.timing.holds.map((advice): Todo => ({ kind: 'hold', advice })),
    ...(onboard ? [{ kind: 'onboard', option: onboard } as const] : []),
    ...(consult.length > 0 ? [{ kind: 'consult', poIds: consult } as const] : []),
    ...result.timing.reallocations.map((item): Todo => ({ kind: 'reallocation', item })),
  ]
}

/** 할 일(조치) 한 줄의 글: 제목 · 세부(판단에 쓰는 숫자만 짧게, 바뀌지 않는 값은 빼고) · 결재 기간 한 줄. */
export interface TodoText {
  title: string
  detail: string
  /** 보류 권고의 결재 기간 한 줄(결재 계획을 줄 때만 — 서버 문구 그대로, lib/approvalHold). */
  note?: string
}

/**
 * 할 일(조치) 한 줄의 글. 결재 계획(분석 응답·기록 조회의 approval_plan)을 주면 보류 권고에 결재 기간 한 줄(note)을
 * 더한다 — 엔진 보류 기간은 그대로, 문구는 서버 값.
 */
export function todoText(todo: Todo, deadline: ZeroLossDeadline, plan?: ApprovalPlan | null): TodoText {
  if (todo.kind === 'held') {
    return { title: `발주 ${todo.poId} ${todo.days}일 보류`, detail: '보류를 넣은 가정 계산' }
  }
  if (todo.kind === 'hold') {
    const { advice } = todo
    const moved = deadlineText(deadline) !== deadlineText(advice.deadline_after)
    return {
      title: `발주 ${advice.po_id} 보류 권고`,
      detail: [
        `최대 ${advice.max_hold_days}일(${formatDay(advice.hold_until)}까지)`,
        ...(moved ? [`결정 기한 ${deadlineText(deadline)} → ${deadlineText(advice.deadline_after)}`] : []),
        `피하는 손실 ${formatMoney(advice.avoided.value)}`,
      ].join(' · '),
      ...noteOf(approvalHoldText(advice, plan)),
    }
  }
  if (todo.kind === 'onboard') return onboardText(todo.option)
  if (todo.kind === 'consult') {
    return {
      title: `발주 ${todo.poIds.join(', ')} 변경·취소 전 손실 보상 협의`,
      detail: '협의 없이 바꾸거나 취소하면 하도급법 위반 소지',
    }
  }
  const { item } = todo
  const surplus = item.lot_id.includes('#')
  const saved =
    item.saved.value >= 0 ? `절감 비용 ${formatMoney(item.saved.value)}` : `추가 비용 ${formatMoney(-item.saved.value)}`
  return {
    title: surplus
      ? `잉여 자재 ${item.lot_id} → ${codeOf(item.to_block_id)} 블록으로 전용`
      : `재고 ${item.lot_id} → ${codeOf(item.to_block_id)} 블록에 사용`,
    detail: `${item.qty.toFixed(3)}t · ${saved}`,
  }
}

/**
 * 후행 설치 선택지 한 줄(명세 6-8): 다른 방식으로 바꾸면 탑재·구역 출구·인도 지연과 비용이 어떻게 되는지.
 * 지금 → 바꾸면 순서로 적고(같으면 '그대로' — '0일 → 0일'처럼 읽히는 데 시간이 드는 글을 줄임), 인도 지연은 둘 중 하나라도
 * 늘었거나 계산하지 못할 때만 적는다.
 */
function onboardText(option: OnboardOption): { title: string; detail: string } {
  const blocks = option.block_ids.map(codeOf).join(', ')
  const toOnBoard = option.direction === 'to_on_board'
  const change = option.total_change.value
  const days = (value: number | null | undefined) => (value == null ? '계산 불가' : `${value}일`)
  const move = (name: string, now: number | null | undefined, then: number | null | undefined) =>
    now === then && now != null ? `${name} 그대로(${days(now)})` : `${name} ${days(now)} → ${days(then)}`
  const deliveryShown =
    option.delivery_added_now_days !== option.delivery_added_then_days ||
    (option.delivery_added_now_days ?? 1) > 0
  return {
    title: toOnBoard
      ? `${blocks} 블록 의장품을 탑재 뒤 선상에서 설치하면`
      : `${blocks} 블록 탑재를 기다려 블록에서 설치하면`,
    detail: [
      move('블록 탑재 지연', option.erection_delay_now_days, option.erection_delay_then_days),
      move('구역 출구 지연', option.exit_delay_now_days, option.exit_delay_then_days),
      ...(deliveryShown ? [move('인도 지연', option.delivery_added_now_days, option.delivery_added_then_days)] : []),
      ...(toOnBoard ? [`후행 설치 ${option.on_board_days}일`] : []),
      change === 0 ? '비용 그대로' : change > 0 ? `비용 ${formatMoney(change)} 늘어남` : `비용 ${formatMoney(-change)} 줄어듦`,
    ].join(' · '),
  }
}

/** 비용 탭: 대표값 큰 순(같으면 줄 ID 순). */
export function sortedLines(lines: readonly CostLine[]): CostLine[] {
  return [...lines].sort((a, b) => b.amount.value - a.amount.value || a.line_id.localeCompare(b.line_id))
}

export interface CurveStep {
  day: string
  total: number
  added: number
  events: readonly string[]
}

/** 곡선 탭의 계단: 대표 총액이 전날과 달라졌거나 사건이 있는 날(첫날 제외). */
export function curveSteps(curve: readonly CurvePoint[]): CurveStep[] {
  return curve
    .filter((point, i) => i > 0 && (point.total.value !== curve[i - 1].total.value || point.events.length > 0))
    .map((point) => ({
      day: point.confirm_on,
      total: point.total.value,
      added: point.additional_loss.value,
      events: point.events,
    }))
}

/** 결재 기간 한 줄이 있으면 note로(없으면 칸을 두지 않는다). */
function noteOf(note: string | null): { note?: string } {
  return note ? { note } : {}
}
