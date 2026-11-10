// 판단이 걸린 상태(docs/domain.md 12절): 분석 결과의 state_basis를 '확인이 필요한 것부터' 보여 주고, '맞음'·'고치기'를
// 상태 갱신(StatusUpdate)으로 바꾼다. 확인은 항상 오늘 날짜 — 기준일이 오늘이 아니면 단추 대신 안내.
// 발주 행의 단계는 입고까지만 고른다: '가공'은 품목마다 소비 공정 착수로 정해져 발주 전체로 남기면 다른 품목까지 가공이 된다.
import type { StateBasis, StatusUpdate } from '@/api/client'
import { daysBetween, formatDay } from './format'
import { PO_STATUS_NAMES, codeOf } from './labels'

const STALE_DAYS = 7
/** 발주 행에서 고를 수 있는 단계(가공 제외). */
export const PO_STEPS = ['not_ordered', 'ordered', 'material_secured', 'in_fabrication', 'received'] as const
export type PoStep = (typeof PO_STEPS)[number]

export type Need = 'unknown' | 'plan' | 'stale' | 'ok'
const NEED_RANK: Record<Need, number> = { unknown: 0, plan: 1, stale: 2, ok: 3 }

/** 확인이 필요한 정도: 근거 없음 → 계획 추정(계획 이탈 포함) → 오늘 기준 7일 넘게 확인 안 함 → 괜찮음. */
export function needOf(row: StateBasis, today: string): Need {
  if (row.basis === 'unknown') return 'unknown'
  const since = row.last_confirmed ? daysBetween(row.last_confirmed, today) : null
  const fresh = since !== null && since <= STALE_DAYS
  // 공정의 '미착수' 현장 확인은 계산 근거(계획)를 바꾸지 않지만 사람이 확인한 것이라 7일 동안은 괜찮음으로 본다
  if (row.basis === 'plan' || row.basis === 'off_plan') return row.entity_type === 'activity' && fresh ? 'ok' : 'plan'
  return fresh ? 'ok' : 'stale'
}

/**
 * 그 상태를 아는 부서(발주 단계·공정 실적은 설계 담당자가 알기 어렵다): 발주 = 구매, 공정 = 생산관리.
 * 화면은 줄마다 이 부서를 적고, 할 일 숫자에서 빼고, 검토 요청 창에 '확인 필요 n(구매 · 생산관리)'로 결재선에 알린다.
 */
export const OWNER: Record<StateBasis['entity_type'], string> = { po: '구매', activity: '생산관리' }

/** 확인이 필요한 줄의 부서별 수: '구매 1 · 생산관리 3'(없으면 null). */
export function ownerSummary(rows: readonly StateBasis[], today: string): { count: number; text: string } | null {
  const needing = rows.filter((row) => needOf(row, today) !== 'ok')
  if (needing.length === 0) return null
  const counts = (['po', 'activity'] as const)
    .map((type) => [OWNER[type], needing.filter((row) => row.entity_type === type).length] as const)
    .filter(([, n]) => n > 0)
  return { count: needing.length, text: counts.map(([owner, n]) => `${owner} ${n}`).join(' · ') }
}

export function sortRows(rows: readonly StateBasis[], today: string): StateBasis[] {
  return [...rows].sort(
    (a, b) =>
      NEED_RANK[needOf(a, today)] - NEED_RANK[needOf(b, today)] ||
      (a.entity_type === b.entity_type ? 0 : a.entity_type === 'po' ? -1 : 1) ||
      a.entity_id.localeCompare(b.entity_id),
  )
}

/**
 * 접힌 줄 단추 글(상세의 판단이 걸린 상태는 확인이 필요한 줄만 먼저 보인다): '확인 필요 2개 · 확인된 3개 더 보기'.
 * hidden = 접힌 줄 수, hiddenNeeding = 그 가운데 확인이 필요한 줄 수. 접힌 줄이 없으면 null.
 */
export function foldedText(hidden: number, hiddenNeeding: number): string | null {
  if (hidden <= 0) return null
  const ok = hidden - hiddenNeeding
  const parts = [hiddenNeeding > 0 && `확인 필요 ${hiddenNeeding}개`, ok > 0 && `확인된 ${ok}개`].filter(Boolean)
  return `${parts.join(' · ')} 더 보기`
}

/** 지금 상태 한 줄: 발주는 단계, 공정은 실적·예상. */
export function stateText(row: StateBasis): string {
  if (row.entity_type === 'po') return row.po_status ? PO_STATUS_NAMES[row.po_status] : '단계 판단 불가'
  if (row.actual_finish) return `완료(실적 ${formatDay(row.actual_finish)})`
  if (row.actual_start) return `진행 중(실적 착수 ${formatDay(row.actual_start)})`
  return row.expected_start ? `미착수 · 예상 착수 ${formatDay(row.expected_start)}` : '미착수'
}

export const BASIS_TEXT: Record<StateBasis['basis'], string> = {
  evidence: '확인된 날짜로',
  plan: '계획으로 추정',
  off_plan: '계획과 어긋나 추정',
  unknown: '근거 없음',
}

export function lastText(row: StateBasis, today: string): string {
  if (!row.last_confirmed) return '확인 기록 없음'
  const since = daysBetween(row.last_confirmed, today)
  if (since === null || since <= 0) return '오늘 확인'
  return `마지막 확인 ${formatDay(row.last_confirmed)} · ${since}일 전`
}

/** 이 행을 데려온 것: 공정 행은 '품목 …을 쓰는 공정'·'블록 … 공정'. */
export function viaText(row: StateBasis): string | null {
  if (row.via.length === 0) return null
  const items = row.via.filter((id) => id.includes('#'))
  const blocks = row.via.filter((id) => !id.includes('#'))
  if (row.entity_type === 'activity') {
    if (items.length > 0) return `품목 ${items.join(', ')}을 쓰는 공정`
    return `블록 ${blocks.map(codeOf).join(', ')}의 공정`
  }
  return blocks.length > 0 && items.length === 0 ? `블록 ${blocks.map(codeOf).join(', ')} 강재` : null
}

export type Quick = { kind: 'ok'; label: string; update: StatusUpdate } | { kind: 'blocked'; reason: string }

/** '맞음'으로 바로 남길 수 있는가(지금 보이는 상태를 오늘의 사실로). 안 되면 이유. */
export function quickConfirm(row: StateBasis, today: string): Quick {
  if (row.as_of !== today) return { kind: 'blocked', reason: '기준일을 오늘로 바꾸면 확인 가능' }
  if (row.entity_type === 'po') {
    const status = row.po_status
    if (!status) return { kind: 'blocked', reason: '단계 판단 불가 — ‘고치기’에서 선택' }
    if (status === 'processed') return { kind: 'blocked', reason: '가공은 쓰는 공정의 착수로 확인' }
    return {
      kind: 'ok',
      label: `${PO_STATUS_NAMES[status]} 맞음`,
      update: confirmUpdate([{ kind: 'po_status', po_id: row.entity_id, status, observed_on: today }]),
    }
  }
  const check = row.actual_finish
    ? 'finished'
    : row.actual_start
      ? 'in_progress'
      : row.expected_start && row.expected_start > today
        ? 'not_started'
        : null
  if (!check) return { kind: 'blocked', reason: '계획상 착수일 지남 — ‘고치기’에서 실제 착수일 입력' }
  const label = check === 'finished' ? '완료 맞음' : check === 'in_progress' ? '진행 중 맞음' : '미착수 맞음'
  return {
    kind: 'ok',
    label,
    update: confirmUpdate([{ kind: 'activity_check', activity_id: row.entity_id, state: check, confirmed_on: today }]),
  }
}

export interface PoFix {
  status: PoStep
  /** 입고까지 일수(발주 뒤). 비우면 바꾸지 않음. */
  leadTimeDays: string
}

export interface ActivityFix {
  started: string
  finished: string
  /** 아직 착수 전(실적 날짜를 넣지 않음). */
  notStarted: boolean
}

/** 고치기(발주): 오늘 단계 관측 + 납기(리드타임) 변경. 문제면 이유 문장. */
export function poFixUpdate(row: StateBasis, fix: PoFix, today: string): StatusUpdate | string {
  const items: StatusUpdate['items'] = [{ kind: 'po_status', po_id: row.entity_id, status: fix.status, observed_on: today }]
  const lead = fix.leadTimeDays.trim()
  if (lead) {
    const days = Number(lead)
    if (!Number.isInteger(days) || days <= 0) return '입고까지 일수: 1 이상의 정수 필요'
    items.push({ kind: 'po_plan', po_id: row.entity_id, field: 'lead_time_days', value: days })
  }
  return confirmUpdate(items)
}

/** 고치기(공정): 실제 착수·완료일(오늘까지) 또는 아직 미착수 확인. */
export function activityFixUpdate(row: StateBasis, fix: ActivityFix, today: string): StatusUpdate | string {
  if (fix.notStarted) {
    if (row.actual_start) return '실제 착수일 있음 · 미착수로 확인 불가'
    return confirmUpdate([{ kind: 'activity_check', activity_id: row.entity_id, state: 'not_started', confirmed_on: today }])
  }
  const started = fix.started || row.actual_start || ''
  if (!started) return '실제 착수일 입력 필요'
  if (started > today || (fix.finished && fix.finished > today)) return '오늘 뒤 날짜 입력 불가'
  if (fix.finished && fix.finished < started) return '완료일은 착수일 이후만 가능'
  return confirmUpdate([
    {
      kind: 'activity_actual',
      activity_id: row.entity_id,
      actual_start: fix.started || null,
      actual_finish: fix.finished || null,
    },
    {
      kind: 'activity_check',
      activity_id: row.entity_id,
      state: fix.finished ? 'finished' : 'in_progress',
      confirmed_on: today,
    },
  ])
}

function confirmUpdate(items: StatusUpdate['items']): StatusUpdate {
  return { origin: 'confirm', items }
}
