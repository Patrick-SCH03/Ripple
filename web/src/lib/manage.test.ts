import { describe, expect, it } from 'vitest'
import type { InboxItem } from '@/api/client'
import {
  blockLabel,
  delayText,
  dueMark,
  errorText,
  filterInbox,
  hoursText,
  manwonToWon,
  percent,
  stampText,
  stateBars,
  stepHoursText,
  stepWaitText,
  waitingText,
} from './manage'

describe('결재·현황 머리의 기준 시각(stampText)', () => {
  // 결재함 줄의 D-n을 센 날 = 결정 기한 − D-n(서버가 줄마다 정한 업무상 오늘)
  const row = (deadline: string, days_left: number) => ({ deadline, days_left })

  it('업무상 오늘 = 갱신 시각의 KST 날짜면 시각만(live 시계), 결재함이 비어도 시각만', () => {
    expect(stampText('2026-10-28T09:52:00+00:00', [row('2026-10-29', 1), row('2026-11-08', 11)])).toBe('10월 28일 18:52 KST 기준')
    expect(stampText('2026-10-28T09:52:00+00:00', [])).toBe('10월 28일 18:52 KST 기준')
    // KST 자정 넘김: UTC 10-28 15:10 = KST 10-29 00:10
    expect(stampText('2026-10-28T15:10:00+00:00', [row('2026-10-30', 1)])).toBe('10월 29일 00:10 KST 기준')
  })

  it('D-n을 다른 날로 셌으면(fixed 시계 = 지도 기준일) 머리에 업무 기준일을 함께', () => {
    expect(stampText('2026-10-28T09:52:00+00:00', [row('2026-10-21', 1), row('2026-10-26', 6)])).toBe(
      '10월 28일 18:52 KST 기준 · 업무 기준일 10월 20일(화)',
    )
  })

  it('줄마다 센 날이 다르면 날짜 하나로 적지 않고 그렇다고만', () => {
    expect(stampText('2026-10-28T09:52:00+00:00', [row('2026-10-21', 1), row('2026-10-29', 1)])).toBe(
      '10월 28일 18:52 KST 기준 · D-n은 건마다 분석 기준일부터 셈',
    )
  })
})

function item(extra: Partial<InboxItem> = {}): InboxItem {
  return {
    ecn_id: 'ECN-D-0119',
    title: '판 두께',
    state: 'in_review',
    revision: 1,
    record_id: 'R-00000000000000aa',
    data_mode: 'synthetic',
    verdict: 'warn',
    total: { value: 35_290_000, low: 13_680_000, high: 81_560_000 },
    deadline_kind: 'by_date',
    deadline: '2026-10-27',
    as_of: '2026-10-20',
    confirm_on: '2026-10-20',
    days_left: 7,
    delay_cost: 12_100_000,
    delay_from: '2026-10-28',
    horizon_end: '2026-12-19',
    requested_by: { login_id: 'kim', name: '김담당', role: 'member', dev: false },
    requested_at: '2026-10-12T01:00:00Z',
    waiting_hours: 5.4,
    checklist: 2,
    cheaper_by: 29_050_000,
    blocks: ['B31P'],
    step: 'team_lead',
    steps: ['part_lead', 'team_lead', 'executive'],
    signed: [],
    step_waiting_hours: 5.4,
    ...extra,
  }
}

describe('dueMark · delayText', () => {
  it('D-n, 3일 이내는 위험 색, 오늘·지남, 기간 안 손실 없음은 기간 끝 날짜로', () => {
    expect(dueMark(item())).toMatchObject({ text: 'D-7', tone: 'neutral' })
    expect(dueMark(item({ days_left: 3 })).tone).toBe('danger')
    expect(dueMark(item({ days_left: 0 })).text).toBe('오늘')
    expect(dueMark(item({ days_left: -2 }))).toMatchObject({ text: '2일 지남', tone: 'danger' })
    const none = dueMark(item({ deadline_kind: 'none_in_horizon', days_left: 60 }))
    expect(none).toMatchObject({ text: '손실 없음', tone: 'relaxed' })
    expect(none.detail).toContain('12월 19일')
  })

  it('미루면: 마감 다음 날부터 늘어나는 금액, 0원이면 금액 그대로, 계산 안 했으면 없음', () => {
    expect(delayText(item())).toBe('10월 28일(수)부터 +1,210만원')
    expect(delayText(item({ delay_cost: 0 }))).toContain('금액 그대로')
    expect(delayText(item({ delay_cost: null, delay_from: null }))).toBeNull()
  })
})

describe('결재함 거르기', () => {
  it('전체 · 마감 3일 이내(손실 없음 건은 빼고), 결재 단계 거르기는 없음(팀장 한 역할)', () => {
    const items = [
      item(),
      item({ ecn_id: 'B', days_left: 2 }),
      item({ ecn_id: 'C', deadline_kind: 'none_in_horizon', days_left: 1 }),
    ]
    expect(filterInbox(items, 'urgent').map((i) => i.ecn_id)).toEqual(['B'])
    expect(filterInbox(items, 'all')).toHaveLength(3)
  })
})

describe('시간·비율·상태 막대', () => {
  it('기다린 시간·처리 시간·비율 문구', () => {
    expect(waitingText(0.4)).toBe('방금')
    expect(waitingText(5.4)).toBe('5시간째 대기')
    expect(waitingText(51)).toBe('2일 3시간째 대기')
    expect(waitingText(48)).toBe('2일째 대기')
    expect(hoursText(null)).toBe('—')
    expect(hoursText(0)).toBe('1분')
    expect(hoursText(0.42)).toBe('25분')
    expect(blockLabel('S-001:B31S')).toBe('B31S')
    expect(blockLabel('B31S')).toBe('B31S')
    expect(hoursText(3.46)).toBe('3.5시간')
    expect(hoursText(30)).toBe('1.3일')
    expect(
      stepHoursText([
        { step: 'part_lead', decisions: 2, median_hours: 2.5 },
        { step: 'executive', decisions: 1, median_hours: 0.42 },
      ]),
    ).toBe('파트장 2.5시간 · 본부장 25분')
    expect(stepHoursText([])).toBeNull()
    expect(stepWaitText('2026-10-26T01:00:00Z', '2026-10-28T04:00:00Z')).toBe('2일 3시간째 대기')
    expect(stepWaitText('2026-10-28T03:50:00Z', '2026-10-28T04:00:00Z')).toBe('방금')
    expect(percent(0.756)).toBe('76%')
    expect(percent(null)).toBe('—')
  })

  it('상태 막대는 가장 많은 상태 대비 비율', () => {
    const bars = stateBars([
      { state: 'in_review', count: 2 },
      { state: 'approved', count: 4 },
      { state: 'closed', count: 0 },
    ])
    expect(bars.map((b) => [b.label, b.ratio])).toEqual([
      ['검토', 0.5],
      ['승인', 1],
      ['종료', 0],
    ])
  })
})

describe('실적 입력·오차', () => {
  it('오차율 문구는 부호를 붙이고 반올림', () => {
    expect(errorText(0.1)).toBe('+10%')
    expect(errorText(-0.052)).toBe('−5%')
    expect(errorText(0.004)).toBe('0%')
    expect(errorText(null)).toBe('—')
  })

  it("'만원' 글 → 원: 쉼표·공백 허용, 음수·글자·소수 셋째 자리는 거절", () => {
    expect(manwonToWon('3,100')).toBe(31_000_000)
    expect(manwonToWon(' 12.5 ')).toBe(125_000)
    expect(manwonToWon('0')).toBe(0)
    expect(manwonToWon('0.01')).toBe(100)
    for (const bad of ['', '-5', '1e3', '3천', '1.234', '.5']) expect(manwonToWon(bad)).toBeNull()
  })

  it('넣은 값을 다시 고칠 때(원 → 만원 글 → 원) 값이 그대로', () => {
    for (const won of [0, 100, 125_000, 31_000_000, 841_234_500]) {
      expect(manwonToWon(String(won / 10_000))).toBe(won)
    }
  })
})
