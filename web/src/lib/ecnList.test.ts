import { describe, expect, it } from 'vitest'
import type { EcnListItem, EcnState, Sample, VerdictLevel, ZeroLossDeadline } from '@/api/client'
import {
  FILTERS,
  basisText,
  daysLeft,
  deadlineMark,
  filterRecorded,
  filterSamples,
  firstToOpen,
  isClosed,
  listedCount,
  manyShips,
  mineSet,
  placeText,
  sortSamples,
  verdictCounts,
} from './ecnList'

const AS_OF = '2026-10-20'

function sample(
  id: string,
  summary: { verdict: VerdictLevel; deadline: ZeroLossDeadline; total: number; blocks?: string[] } | null,
  asOf = AS_OF,
): Sample {
  return {
    ecn_id: id,
    title: id,
    op: 'thickness',
    rules: [],
    request: {
      as_of: asOf,
      change: { ecn_id: id, title: id, ship_ids: ['S-001'], ops: [] },
    } as unknown as Sample['request'],
    summary: summary && {
      analysis_id: `A-${id}`,
      verdict: summary.verdict,
      deadline: summary.deadline,
      total: { value: summary.total, low: summary.total, high: summary.total },
      blocks: summary.blocks ?? ['S-001:B31P'],
    },
  }
}

/** 샘플에 없는 기록(목록 아래 '기록된 다른 설계변경'): 상태와 최신 개정 판정만 본다. */
function recorded(id: string, verdict: VerdictLevel, state: EcnState): EcnListItem {
  return {
    status: { ecn_id: id, title: id, state },
    latest: { verdict },
  } as unknown as EcnListItem
}

const byDate = (lastDay: string): ZeroLossDeadline => ({ kind: 'by_date', last_day: lastDay })
const now: ZeroLossDeadline = { kind: 'confirm_now', last_day: AS_OF }
const never: ZeroLossDeadline = { kind: 'none_in_horizon', last_day: '2026-12-19' }

describe('마감일 표시', () => {
  it('남은 날: 오늘 = 0, 날짜 = 기준일부터, 기간 안 없음 = 무한', () => {
    expect(daysLeft(now, AS_OF)).toBe(0)
    expect(daysLeft(byDate('2026-10-27'), AS_OF)).toBe(7)
    expect(daysLeft(never, AS_OF)).toBe(Number.POSITIVE_INFINITY)
  })

  it('D-3 이하·오늘은 위험, 그 위는 보통, 기간 안 없음은 여유', () => {
    expect(deadlineMark(now, AS_OF)).toMatchObject({ text: '오늘', tone: 'danger' })
    expect(deadlineMark(byDate('2026-10-23'), AS_OF)).toMatchObject({ text: 'D-3', tone: 'danger' })
    expect(deadlineMark(byDate('2026-10-24'), AS_OF)).toMatchObject({ text: 'D-4', tone: 'neutral' })
    expect(deadlineMark(never, AS_OF)).toMatchObject({ text: '기간 안 없음', tone: 'relaxed' })
    expect(deadlineMark(byDate('2026-10-27'), AS_OF).label).toBe('10월 27일(화)까지 확정 시 추가손실 없음')
  })
})

describe('정렬·거르기', () => {
  const list = [
    sample('ECN-1', { verdict: 'review', deadline: byDate('2026-10-27'), total: 100 }),
    sample('ECN-2', { verdict: 'warn', deadline: byDate('2026-10-27'), total: 50 }),
    sample('ECN-3', { verdict: 'approve', deadline: never, total: 900 }),
    sample('ECN-4', { verdict: 'review', deadline: now, total: 10 }),
    sample('ECN-5', null),
    sample('ECN-6', { verdict: 'warn', deadline: byDate('2026-10-27'), total: 50 }),
  ]

  it('마감일 순: 마감일 임박 → 판정 심각도 → 비용 큰 순 → ECN 번호, 요약 없는 것은 끝', () => {
    expect(sortSamples(list, 'deadline').map((s) => s.ecn_id)).toEqual(['ECN-4', 'ECN-2', 'ECN-6', 'ECN-1', 'ECN-3', 'ECN-5'])
  })

  it('비용 큰 순: 총변경비용 → 마감일 → 판정', () => {
    expect(sortSamples(list, 'cost').map((s) => s.ecn_id)).toEqual(['ECN-3', 'ECN-1', 'ECN-2', 'ECN-6', 'ECN-4', 'ECN-5'])
  })

  it('원래 배열은 그대로', () => {
    const before = list.map((s) => s.ecn_id)
    sortSamples(list, 'deadline')
    expect(list.map((s) => s.ecn_id)).toEqual(before)
  })

  it('판정 거르기와 개수(요약 없는 것은 전체에만)', () => {
    expect(filterSamples(list, 'warn').map((s) => s.ecn_id)).toEqual(['ECN-2', 'ECN-6'])
    expect(filterSamples(list, 'all')).toHaveLength(6)
    expect(verdictCounts(list)).toEqual({ all: 6, pending: 0, mine: 0, warn: 2, review: 2, approve: 1, closed: 0 })
  })

  it("'기록된 다른 설계변경'도 같은 거르기·개수: 판정 칸은 최신 개정 판정으로, 종료는 종료 칸에만(개수 = 보이는 줄)", () => {
    const others = [
      recorded('ECN-7', 'approve', 'analyzed'),
      recorded('ECN-8', 'approve', 'in_review'),
      recorded('ECN-9', 'warn', 'rejected'),
      recorded('ECN-10', 'review', 'closed'),
    ]
    const ids = (filter: Parameters<typeof filterRecorded>[1]) => filterRecorded(others, filter).map((i) => i.status.ecn_id)
    expect(ids('review')).toEqual([])
    expect(ids('approve')).toEqual(['ECN-7', 'ECN-8'])
    expect(ids('warn')).toEqual(['ECN-9'])
    expect(ids('all')).toEqual(['ECN-7', 'ECN-8', 'ECN-9'])
    expect(ids('closed')).toEqual(['ECN-10'])
    const counts = verdictCounts(list, undefined, others)
    expect(counts).toEqual({ all: 9, pending: 1, mine: 0, warn: 3, review: 2, approve: 3, closed: 1 })
    for (const filter of FILTERS) {
      expect(counts[filter]).toBe(filterSamples(list, filter).length + filterRecorded(others, filter).length)
    }
  })

  it('종료된 설계변경은 종료 칸에만: 전체·판정 칸과 개수에서 빠짐', () => {
    const stateOf = (id: string) => (id === 'ECN-2' ? 'closed' : id === 'ECN-6' ? 'in_progress' : undefined)
    expect(filterSamples(list, 'closed', stateOf).map((s) => s.ecn_id)).toEqual(['ECN-2'])
    expect(filterSamples(list, 'warn', stateOf).map((s) => s.ecn_id)).toEqual(['ECN-6'])
    expect(filterSamples(list, 'all', stateOf).map((s) => s.ecn_id)).not.toContain('ECN-2')
    expect(verdictCounts(list, stateOf)).toEqual({ all: 5, pending: 0, mine: 0, warn: 1, review: 2, approve: 1, closed: 1 })
    expect(isClosed('closed') && !isClosed('in_progress') && !isClosed(undefined)).toBe(true)
  })

  it("'내 건': 최신 개정을 내가 기록한 것만(종료 제외) — 샘플·다른 기록 모두, 개수 = 보이는 줄, 한 건은 한 번만", () => {
    const others = [recorded('ECN-7', 'approve', 'analyzed'), recorded('ECN-10', 'review', 'closed')]
    const by = (login: string) => ({ recorded_by: { login_id: login, name: login, role: 'member', dev: false } })
    const records = [
      { ...recorded('ECN-1', 'review', 'rejected'), latest: { verdict: 'review', ...by('kim') } },
      { ...recorded('ECN-2', 'warn', 'in_review'), latest: { verdict: 'warn', ...by('lee') } },
      { ...others[0], latest: { verdict: 'approve', ...by('kim') } },
      { ...others[1], latest: { verdict: 'review', ...by('kim') } },
    ] as unknown as EcnListItem[]
    const mine = mineSet(records, 'kim')
    expect([...mine].sort()).toEqual(['ECN-1', 'ECN-10', 'ECN-7'])
    expect(mineSet(records, null).size).toBe(0)
    // 머리 개수 = 샘플 6 + 샘플 밖 기록(ECN-7·ECN-10), 샘플과 같은 번호(ECN-1·ECN-2)는 한 번
    expect(listedCount(list, records)).toBe(8)
    const stateOf = (id: string) => records.find((item) => item.status.ecn_id === id)?.status.state
    const mineOf = (id: string) => mine.has(id)
    expect(filterSamples(list, 'mine', stateOf, mineOf).map((s) => s.ecn_id)).toEqual(['ECN-1'])
    expect(filterRecorded(others, 'mine', mineOf).map((i) => i.status.ecn_id)).toEqual(['ECN-7'])
    const counts = verdictCounts(list, stateOf, others, mineOf)
    expect(counts.mine).toBe(2)
    for (const filter of FILTERS) {
      expect(counts[filter]).toBe(
        filterSamples(list, filter, stateOf, mineOf).length + filterRecorded(others, filter, mineOf).length,
      )
    }
  })

  it('처음 열 건: 종료된 건을 건너뛴 기본 정렬 첫 줄, 모두 종료면 첫 줄', () => {
    expect(firstToOpen(list, new Set())?.ecn_id).toBe('ECN-4')
    expect(firstToOpen(list, new Set(['ECN-4', 'ECN-2']))?.ecn_id).toBe('ECN-6')
    expect(firstToOpen(list, new Set(list.map((s) => s.ecn_id)))?.ecn_id).toBe('ECN-4')
    expect(firstToOpen([], new Set())).toBeUndefined()
  })
})

describe('계산 조건 · 호선·블록', () => {
  it('기준일이 같으면 그 날짜, 다르면 각 기준일', () => {
    expect(basisText([sample('A', null)])).toBe(
      '10월 20일(화) 확정 · 보류 없음 기준',
    )
    expect(basisText([sample('A', null), sample('B', null, '2026-10-21')])).toContain('각 기준일 확정')
    expect(basisText([])).toBeNull()
  })

  it('블록 코드(셋 이상이면 외 n), 호선은 둘 이상일 때만', () => {
    const one = sample('A', { verdict: 'warn', deadline: now, total: 1, blocks: ['S-001:B31P'] })
    const three = sample('B', { verdict: 'warn', deadline: now, total: 1, blocks: ['S-001:B31P', 'S-001:L31C', 'S-001:T31C'] })
    expect(placeText(one)).toBe('B31P')
    expect(placeText(one, true)).toBe('S-001 · B31P')
    expect(placeText(three)).toBe('B31P 외 2')
    expect(placeText(sample('C', null))).toBe('')
    const other = { ...one, request: { ...one.request, change: { ...one.request.change, ship_ids: ['S-002'] } } }
    expect(manyShips([one, three])).toBe(false)
    expect(manyShips([one, other])).toBe(true)
  })
})
