// 결재·현황 화면 계산(팀장, docs/records.md(기록·결재) 11절): 결재함 줄 문구 · 마감 표시 · 처리 시간 · 비율.
// 숫자는 모두 API(ManageOverview)에서 온다. 여기서는 표시·거르기만 한다.
import type { EcnState, InboxItem, StateCount, StepHours } from '@/api/client'
import { formatKstTime } from './account'
import { STEP_LABEL } from './approval'
import { todayKst } from './basis'
import { addDays, formatDay } from './format'
import { formatMoney } from './money'
import { STATE_LABEL } from './records'

export const URGENT_DAYS = 3 // 서버의 manage.URGENT_DAYS와 같음

/**
 * 결재·현황 머리의 기준 시각 '10월 28일 18:52 KST 기준'. 결재함 D-n을 센 업무상 오늘(줄마다 결정 기한 − D-n — 서버가
 * 정한 값: 실시간 세계 = KST 오늘, 날짜에 멈춘 합성(fixed 시계) = 분석 기준일)이 그 시각의 KST 날짜와 다르면
 * '· 업무 기준일 10월 20일(화)'을 붙인다 — 머리의 날짜만 보고 D-n·'결재해도 결정은 빨라야'를 며칠 어긋나 읽지 않게.
 * 응답의 today는 늘 KST 오늘(실데이터 기준)이라 쓰지 않는다. 줄마다 센 날이 다르면 날짜 하나로 적지 않는다.
 */
export function stampText(generatedAt: string, rows: readonly Pick<InboxItem, 'deadline' | 'days_left'>[]): string {
  const stamp = `${formatKstTime(generatedAt)} 기준`
  const at = new Date(generatedAt)
  if (Number.isNaN(at.getTime())) return stamp
  const days = [...new Set(rows.map((row) => addDays(row.deadline, -row.days_left)))]
  if (days.length === 0 || (days.length === 1 && days[0] === todayKst(at))) return stamp
  return days.length === 1 ? `${stamp} · 업무 기준일 ${formatDay(days[0])}` : `${stamp} · D-n은 건마다 분석 기준일부터 셈`
}

export const PERIODS: readonly { days: number | null; label: string }[] = [
  { days: 7, label: '최근 7일' },
  { days: 30, label: '최근 30일' },
  { days: 90, label: '최근 90일' },
  { days: null, label: '전체' },
]

export type Tone = 'danger' | 'warning' | 'neutral' | 'relaxed'

export interface DueMark {
  /** 큰 글자: 'D-3' · '오늘' · '2일 지남' · '손실 없음'. */
  text: string
  tone: Tone
  /** 한 줄 설명(화면 낭독기·툴팁). */
  detail: string
}

/** 결재함 마감 표시. 날짜 기준은 서버가 기록마다 정한 days_left(합성 = 분석 기준일, 실데이터 = 오늘). */
export function dueMark(item: InboxItem): DueMark {
  if (item.deadline_kind === 'none_in_horizon') {
    return { text: '손실 없음', tone: 'relaxed', detail: `${formatDay(item.horizon_end)}까지 확정해도 추가손실 없음` }
  }
  const days = item.days_left
  const day = formatDay(item.deadline)
  if (days < 0) return { text: `${-days}일 지남`, tone: 'danger', detail: `결정 기한(${day}) 지남` }
  if (days === 0) return { text: '오늘', tone: 'danger', detail: `오늘(${day})까지 결정해야 추가손실 없음` }
  return {
    text: `D-${days}`,
    tone: days <= URGENT_DAYS ? 'danger' : 'neutral',
    detail: `${day}까지 결정 시 추가손실 없음`,
  }
}

/** '미루면' 한 줄: '10월 28일(수)부터 +1,210만원'. 금액이 그대로면(일정만 늦어짐) 그렇게, 계산 안 했으면 null. */
export function delayText(item: InboxItem): string | null {
  if (item.delay_cost == null || !item.delay_from) return null
  const from = formatDay(item.delay_from)
  return item.delay_cost > 0 ? `${from}부터 +${formatMoney(item.delay_cost)}` : `${from}부터도 금액 그대로(일정 지연 가능)`
}

/** 기다린 시간('○○ 요청 · ' 뒤에 붙음): '방금' · '5시간째 대기' · '2일 3시간째 대기'. */
export function waitingText(hours: number): string {
  if (hours < 1) return '방금'
  if (hours < 24) return `${Math.floor(hours)}시간째 대기`
  const days = Math.floor(hours / 24)
  const rest = Math.floor(hours - days * 24)
  return rest > 0 ? `${days}일 ${rest}시간째 대기` : `${days}일째 대기`
}

/** 그 결재 단계에서 기다린 시간(단계가 시작된 때 → 서버 계산 시각): '방금' · '5시간째 대기' · '2일째 대기'. */
export function stepWaitText(since: string, now: string): string {
  const hours = Math.max(0, (Date.parse(now) - Date.parse(since)) / 3_600_000)
  return Number.isFinite(hours) ? waitingText(hours) : '—'
}

/** 처리 시간 중앙값: 없으면 '—', 1시간 안이면 '25분', 하루 안이면 '3.5시간', 넘으면 '1.2일'. */
export function hoursText(hours: number | null | undefined): string {
  if (hours == null) return '—'
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}분`
  if (hours < 24) return `${Math.round(hours * 10) / 10}시간`
  return `${Math.round((hours / 24) * 10) / 10}일`
}

/** 결재선 단계별 처리 시간(중앙값): '파트장 2.5시간 · 팀장 1.2일 · 본부장 25분'. 결정이 없던 단계는 서버가 뺀다. */
export function stepHoursText(steps: readonly StepHours[]): string | null {
  if (steps.length === 0) return null
  return steps.map((s) => `${STEP_LABEL[s.step]} ${hoursText(s.median_hours)}`).join(' · ')
}

/** 예측 대비 오차율: +0.1 → '+10%', −0.052 → '−5%', 없으면 '—'. */
export function errorText(rate: number | null | undefined): string {
  if (rate == null) return '—'
  const pct = Math.round(rate * 100)
  return pct > 0 ? `+${pct}%` : pct < 0 ? `−${-pct}%` : '0%'
}

/** 실적 입력의 '만원' 글 → 원(쉼표·공백 허용, 소수 둘째 자리까지). 비었거나 숫자가 아니거나 음수면 null. */
export function manwonToWon(text: string): number | null {
  const cleaned = text.replace(/[,\s]/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null
  return Math.round(Number(cleaned) * 10_000)
}

/** 블록 표시: 지도 ID 'S-001:B31S' → 'B31S'(호선 접두어는 줄의 다른 곳에 있음). */
export function blockLabel(id: string): string {
  const cut = id.lastIndexOf(':')
  return cut >= 0 ? id.slice(cut + 1) : id
}

/** 비율 → '75%'(없으면 '—'). */
export function percent(rate: number | null | undefined): string {
  return rate == null ? '—' : `${Math.round(rate * 100)}%`
}

export type InboxFilter = 'all' | 'urgent'

export const INBOX_FILTERS: readonly { id: InboxFilter; label: string }[] = [
  { id: 'all', label: '전체' },
  { id: 'urgent', label: `결정 기한 ${URGENT_DAYS}일 이내` },
]

/** 결재함 거르기(순서는 서버의 마감 급한 순 그대로). */
export function filterInbox(items: readonly InboxItem[], filter: InboxFilter): InboxItem[] {
  if (filter === 'urgent') {
    return items.filter((item) => item.deadline_kind !== 'none_in_horizon' && item.days_left <= URGENT_DAYS)
  }
  return [...items]
}

export interface StateBar {
  state: EcnState
  label: string
  count: number
  /** 가장 많은 상태 대비 비율(0~1, 막대 길이). */
  ratio: number
}

/** 상태별 건수 막대(요청 상태는 서버가 빼고 보낸다). */
export function stateBars(states: readonly StateCount[]): StateBar[] {
  const max = Math.max(1, ...states.map((s) => s.count))
  return states.map((s) => ({ state: s.state, label: STATE_LABEL[s.state], count: s.count, ratio: s.count / max }))
}
