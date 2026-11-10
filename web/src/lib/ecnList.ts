// ECN 목록(DESIGN.md 6절): 판정 · 추가손실 0 마감일(D-n) · 총변경비용 · 블록, 기본 정렬 = 마감일 임박 → 판정.
// 값은 샘플의 기본 요청(기준일에 확정·보류 없음)을 서버가 분석한 요약(Sample.summary)이고, 여기서는 표시·정렬·거르기만 한다.
// 결재가 끝난(종료) 설계변경은 '종료' 칸에만 모은다 — 전체·판정 칸과 개수에서 빠지고, 마감일(D-n)도 보이지 않는다.
// 판정 거르기와 개수는 목록 아래 '기록된 다른 설계변경'에도 같게 적용한다(개수 = 보이는 줄).
import type { EcnListItem, EcnState, Sample, VerdictLevel, ZeroLossDeadline } from '@/api/client'
import { daysBetween, formatDay } from './format'
import { codeOf } from './labels'
import { URGENT_DAYS } from './summary'

// '내 건'(담당자): 최신 개정을 내가 기록한, 종료되지 않은 설계변경. '결재 대기'(결재자): 검토·보류 중인 설계변경.
// 따로 묶음을 두면 같은 건이 목록에 두 번 나와서 거르기 칸으로 둔다.
export type ListSort = 'deadline' | 'cost'
export type ListFilter = 'all' | 'pending' | 'mine' | VerdictLevel | 'closed'
/** 설계변경 번호 → 결재 상태(기록이 없으면 undefined). */
export type StateOf = (ecnId: string) => EcnState | undefined
/** 설계변경 번호 → 내가 최신 개정을 기록했나(담당자의 '내 건'). */
export type MineOf = (ecnId: string) => boolean

export interface ListView {
  sort: ListSort
  filter: ListFilter
}

export const DEFAULT_VIEW: ListView = { sort: 'deadline', filter: 'all' }
export const FILTERS: readonly ListFilter[] = ['all', 'pending', 'mine', 'warn', 'review', 'approve', 'closed']
export const FILTER_NAMES: Record<ListFilter, string> = {
  all: '전체',
  pending: '결재 대기',
  mine: '내 건',
  warn: '경고',
  review: '검토 필요',
  approve: '승인 가능',
  closed: '종료',
}

const NO_STATE: StateOf = () => undefined
const NOT_MINE: MineOf = () => false

/** 기록 목록에서 '내 건' 고르기: 최신 개정을 그 아이디가 기록한 설계변경 번호들(아이디가 없으면 빈 집합). */
export function mineSet(records: readonly EcnListItem[], loginId: string | null): ReadonlySet<string> {
  if (!loginId) return new Set()
  return new Set(records.filter((item) => item.latest.recorded_by.login_id === loginId).map((item) => item.status.ecn_id))
}

/** 결재가 끝난 설계변경인가(마감일·판정 칸 대상이 아님). */
export function isClosed(state: EcnState | undefined): boolean {
  return state === 'closed'
}
export const SORT_NAMES: Record<ListSort, string> = { deadline: '결정 기한 순', cost: '비용 큰 순' }

/** 판정 심각도: 경고가 먼저. */
const SEVERITY: Record<VerdictLevel, number> = { warn: 0, review: 1, approve: 2 }

const compare = (a: number, b: number): number => (a === b ? 0 : a < b ? -1 : 1)

/** 기준일부터 추가손실 0 마감일까지 남은 날: 오늘 확정 = 0, 탐색 기간 안에 없음 = 무한. */
export function daysLeft(deadline: ZeroLossDeadline, asOf: string): number {
  if (deadline.kind === 'confirm_now') return 0
  if (deadline.kind === 'none_in_horizon') return Number.POSITIVE_INFINITY
  return daysBetween(asOf, deadline.last_day) ?? Number.POSITIVE_INFINITY
}

export interface DeadlineMark {
  text: string
  /** danger = D-3 이하·오늘, relaxed = 탐색 기간 안에 마감 없음 */
  tone: 'danger' | 'neutral' | 'relaxed'
  /** 화면 낭독기·툴팁 문장 */
  label: string
}

/** 목록의 마감일 표시: '오늘' · 'D-7' · '기간 안 없음'. */
export function deadlineMark(deadline: ZeroLossDeadline, asOf: string): DeadlineMark {
  if (deadline.kind === 'confirm_now') {
    return { text: '오늘', tone: 'danger', label: '오늘 확정해야 추가손실 없음' }
  }
  const until = `${formatDay(deadline.last_day)}까지 확정`
  if (deadline.kind === 'none_in_horizon') {
    return { text: '기간 안 없음', tone: 'relaxed', label: `${until}해도 추가손실 없음` }
  }
  const days = daysLeft(deadline, asOf)
  return { text: `D-${days}`, tone: days <= URGENT_DAYS ? 'danger' : 'neutral', label: `${until} 시 추가손실 없음` }
}

/**
 * 정렬. 마감일 순 = 마감일 임박 → 판정 심각도 → 비용 큰 순, 비용 큰 순 = 총변경비용 → 마감일 임박 → 판정.
 * 요약이 없는 샘플(분석 거부)은 끝, 나머지가 같으면 ECN 번호 순.
 */
export function sortSamples(samples: readonly Sample[], sort: ListSort): Sample[] {
  return [...samples].sort((a, b) => {
    const left = a.summary
    const right = b.summary
    const byId = a.ecn_id.localeCompare(b.ecn_id)
    if (!left || !right) return compare(left ? 0 : 1, right ? 0 : 1) || byId
    const deadline = compare(daysLeft(left.deadline, a.request.as_of), daysLeft(right.deadline, b.request.as_of))
    const severity = compare(SEVERITY[left.verdict], SEVERITY[right.verdict])
    const cost = compare(right.total.value, left.total.value)
    return (sort === 'deadline' ? deadline || severity || cost : cost || deadline || severity) || byId
  })
}

/** 처음 열 설계변경: 목록 기본 정렬('전체' 칸 — 종료 제외)의 첫 줄. 모두 종료면 종료 포함 첫 줄. */
export function firstToOpen(samples: readonly Sample[], closed: ReadonlySet<string>): Sample | undefined {
  const sorted = sortSamples(samples, DEFAULT_VIEW.sort)
  return sorted.find((sample) => !closed.has(sample.ecn_id)) ?? sorted[0]
}

/**
 * 한 줄이 칸에 드는가: '종료'는 종료된 것만, 나머지 칸은 종료된 것을 빼고 '결재 대기'는 검토·보류, '내 건'은 내가 기록한 것,
 * 판정 칸은 판정으로.
 */
function inFilter(filter: ListFilter, state: EcnState | undefined, verdict: VerdictLevel | undefined, mine: boolean): boolean {
  if (filter === 'closed') return isClosed(state)
  if (isClosed(state)) return false
  if (filter === 'all') return true
  if (filter === 'pending') return state === 'in_review' || state === 'on_hold'
  if (filter === 'mine') return mine
  return verdict === filter
}

/** 거르기: '종료'는 종료된 것만, 나머지 칸은 종료된 것을 빼고 판정으로(전체면 판정 무관, '내 건'은 내가 기록한 것). */
export function filterSamples(
  samples: readonly Sample[],
  filter: ListFilter,
  stateOf: StateOf = NO_STATE,
  mineOf: MineOf = NOT_MINE,
): Sample[] {
  return samples.filter((sample) =>
    inFilter(filter, stateOf(sample.ecn_id), sample.summary?.verdict, mineOf(sample.ecn_id)),
  )
}

/**
 * 목록 아래 '기록된 다른 설계변경'(샘플에 없는 기록) 거르기: 샘플과 같은 규칙 — '종료'는 종료된 것만, 나머지 칸은 종료를 빼고
 * 최신 개정의 판정으로(전체면 판정 무관). 판정 칸을 눌렀는데 아래 묶음이 그대로 남아 개수와 보이는 줄이 어긋나지 않게.
 */
export function filterRecorded(items: readonly EcnListItem[], filter: ListFilter, mineOf: MineOf = NOT_MINE): EcnListItem[] {
  return items.filter((item) => inFilter(filter, item.status.state, item.latest.verdict, mineOf(item.status.ecn_id)))
}

/** 칸별 개수: 전체·내 건·판정은 종료되지 않은 것만, '종료'는 종료된 것. 기록된 다른 설계변경(others)도 같은 칸에 센다. */
export function verdictCounts(
  samples: readonly Sample[],
  stateOf: StateOf = NO_STATE,
  others: readonly EcnListItem[] = [],
  mineOf: MineOf = NOT_MINE,
): Record<ListFilter, number> {
  const counts: Record<ListFilter, number> = { all: 0, pending: 0, mine: 0, warn: 0, review: 0, approve: 0, closed: 0 }
  const add = (ecnId: string, state: EcnState | undefined, verdict: VerdictLevel | undefined) => {
    for (const filter of FILTERS) if (inFilter(filter, state, verdict, mineOf(ecnId))) counts[filter] += 1
  }
  for (const sample of samples) add(sample.ecn_id, stateOf(sample.ecn_id), sample.summary?.verdict)
  for (const item of others) add(item.status.ecn_id, item.status.state, item.latest.verdict)
  return counts
}

/** 목록 칸 머리의 개수: 샘플과 샘플 밖 기록을 합친 설계변경 수(같은 번호는 한 번) — 거르기 칸 '전체 + 종료'와 같다. */
export function listedCount(samples: readonly Sample[], records: readonly EcnListItem[]): number {
  return new Set([...samples.map((sample) => sample.ecn_id), ...records.map((item) => item.status.ecn_id)]).size
}

/** 목록 값의 계산 조건(거르기 칸 툴팁 — 뜻은 ⓘ 'listBasis'). 목록 값은 상세에서 확정일·보류를 바꿔도 그대로다. 기준일이 다 같으면 그 날짜. */
export function basisText(samples: readonly Sample[]): string | null {
  const days = [...new Set(samples.map((sample) => sample.request.as_of))]
  if (days.length === 0) return null
  const when = days.length === 1 ? `${formatDay(days[0])} 확정` : '각 기준일 확정'
  return `${when} · 보류 없음 기준`
}

/** 목록에 호선을 적을까: 샘플들의 호선이 둘 이상일 때만(하나뿐이면 위 막대에 이미 있다). */
export function manyShips(samples: readonly Sample[]): boolean {
  return new Set(samples.flatMap((sample) => sample.request.change.ship_ids)).size > 1
}

/** 호선·블록: "B31P"(호선을 적으면 "S-001 · B31P"), 블록이 셋 이상이면 "B31P 외 2". */
export function placeText(sample: Sample, withShip = false): string {
  const ships = withShip ? sample.request.change.ship_ids.join(', ') : ''
  const blocks = (sample.summary?.blocks ?? []).map(codeOf)
  const where = blocks.length > 2 ? `${blocks[0]} 외 ${blocks.length - 1}` : blocks.join(', ')
  return [ships, where].filter(Boolean).join(' · ')
}
