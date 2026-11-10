import { describe, expect, it } from 'vitest'
import type { AnalysisResult, CurvePoint } from '@/api/client'
import { deadlineDetail, deadlineGuide, deadlineWorkday, guideText, lossText, showUndo, undoOf } from './deadline'
import { addDays } from './format'
import { keyNumbers } from './summary'

const amount = (value: number, low = value, high = value) => ({ value, low, high })

/** 기준일부터 하루씩: 마감일까지 추가손실 0, 다음 날부터 loss. */
function curve(asOf: string, days: number, lastIndex: number, loss = amount(1_200_000)): CurvePoint[] {
  return Array.from({ length: days }, (_, i) => ({
    confirm_on: addDays(asOf, i),
    total: amount(1_000_000),
    additional_loss: i <= lastIndex ? amount(0) : loss,
    max_exit_delay_days: 0,
    events: [],
  }))
}

function result(kind: string, lastDay: string, points: CurvePoint[], confirmOn?: string, workday?: string): AnalysisResult {
  return {
    request: { as_of: '2026-10-20', holds: [], ...(confirmOn ? { confirm_on: confirmOn } : {}) },
    timing: { deadline: { kind, last_day: lastDay }, curve: points, holds: [], reallocations: [] },
    ...(workday ? { approval_plan: { decide_by_workday: workday } } : {}),
  } as unknown as AnalysisResult
}

describe('마감일 카드 보조 설명', () => {
  const points = curve('2026-10-20', 30, 7) // 10월 27일까지 0, 28일부터 120만원

  it('그날까지 확정하면 추가손실 0 · 다음 날부터 늘어나는 금액(곡선의 다음 날 값)', () => {
    expect(deadlineDetail({ kind: 'by_date', last_day: '2026-10-27' }, points)).toBe(
      '10월 27일(화)까지 추가손실 0 · 다음 날부터 +120만원',
    )
  })

  it('다음 날 대표값이 0이고 최대만 있으면 최대 금액, 곡선에 없으면 금액 없이', () => {
    const maxOnly = curve('2026-10-20', 30, 7, amount(0, 0, 350_000))
    expect(deadlineDetail({ kind: 'by_date', last_day: '2026-10-27' }, maxOnly)).toBe(
      '10월 27일(화)까지 추가손실 0 · 다음 날부터 최대 +35만원',
    )
    expect(deadlineDetail({ kind: 'by_date', last_day: '2026-10-27' }, points.slice(0, 8))).toBe(
      '10월 27일(화)까지 추가손실 0 · 다음 날부터 늘어남',
    )
  })

  it('마감일 전에 비용이 줄어드는 날이 있으면 "같다"고 쓰지 않음', () => {
    const dip = points.map((point, i) => (i === 3 ? { ...point, additional_loss: amount(-50_000, -80_000, 0) } : point))
    expect(deadlineDetail({ kind: 'by_date', last_day: '2026-10-27' }, dip)).toContain('추가손실 없음')
  })

  it('오늘(기준일에 확정해야 함)은 내일부터 늘어나는 금액, 기간 안 없음은 언제 확정해도 같음', () => {
    expect(deadlineDetail({ kind: 'confirm_now', last_day: '2026-10-20' }, curve('2026-10-20', 30, 0))).toBe(
      '내일부터 +120만원',
    )
    expect(deadlineDetail({ kind: 'none_in_horizon', last_day: '2026-11-18' }, curve('2026-10-20', 30, 29))).toBe(
      '11월 18일(수)까지 언제 확정해도 추가손실 0',
    )
  })
})

describe('확정일 되돌리기', () => {
  const points = curve('2026-10-20', 30, 7)
  const withEcn = (ecn: string, confirmOn?: string) => {
    const r = result('by_date', '2026-10-27', points, confirmOn)
    return { ...r, request: { ...r.request, change: { ecn_id: ecn } } } as unknown as AnalysisResult
  }

  it('단추를 누르기 전 확정일(비워 둔 기준일이면 null)로 돌아가고, 같은 설계변경에서 확정일이 달라졌을 때만 보임', () => {
    const before = withEcn('ECN-D-0119')
    const undo = undoOf(before, '2026-10-27')
    expect(undo).toEqual({ ecn: 'ECN-D-0119', confirm: null, day: '2026-10-20', to: '2026-10-27' })
    expect(showUndo(undo, before)).toBe(false) // 아직 그대로
    expect(showUndo(undo, withEcn('ECN-D-0119', '2026-10-27'))).toBe(true) // 결정 기한으로 옮긴 뒤
    expect(showUndo(undo, withEcn('ECN-D-0173', '2026-10-27'))).toBe(false) // 다른 설계변경
    expect(showUndo(null, withEcn('ECN-D-0119', '2026-10-27'))).toBe(false)
    expect(undoOf(withEcn('ECN-D-0119', '2026-10-22'), '2026-10-27')).toEqual({
      ecn: 'ECN-D-0119',
      confirm: '2026-10-22',
      day: '2026-10-22',
      to: '2026-10-27',
    })
  })

  it('단추 뒤 다시 분석이 실패해 확정일이 그대로였다가 손으로 다른 날로 바꾸면 되돌리기를 내지 않음', () => {
    const undo = undoOf(withEcn('ECN-D-0119'), '2026-10-27')
    // 단추가 옮긴 날이 아닌 확정일(손으로 고름) — 그때 확정일과 달라도 되돌리기 없음
    expect(showUndo(undo, withEcn('ECN-D-0119', '2026-10-24'))).toBe(false)
    expect(showUndo(undo, withEcn('ECN-D-0119', '2026-11-02'))).toBe(false)
    // 그 뒤 손으로 다시 단추가 옮긴 날을 고르면 되돌리기가 맞는 확정일(단추 전)로 돌아간다
    expect(showUndo(undo, withEcn('ECN-D-0119', '2026-10-27'))).toBe(true)
    // 성질: 지금 확정일이 단추가 옮긴 날일 때만 보임(같은 설계변경)
    for (let i = 0; i < 20; i += 1) {
      const day = addDays('2026-10-20', i)
      expect(showUndo(undo, withEcn('ECN-D-0119', day))).toBe(day === '2026-10-27')
    }
  })
})

describe('확정일을 마감일로', () => {
  const points = curve('2026-10-20', 30, 7)

  it('확정일이 마감일 앞이면(비우면 기준일) 마감일로 미루는 단추, 같으면 상태만, 뒤면 그날 추가손실과 당기기', () => {
    const later = deadlineGuide(result('by_date', '2026-10-27', points))
    expect(later).toEqual({ kind: 'later', to: '2026-10-27' })
    expect(guideText(later!, 'by_date')).toEqual({ status: null, button: '확정일을 10월 27일(화)로' })

    const on = deadlineGuide(result('by_date', '2026-10-27', points, '2026-10-27'))
    expect(guideText(on!, 'by_date')).toEqual({ status: '확정일 = 결정 기한', button: null })

    const past = deadlineGuide(result('by_date', '2026-10-27', points, '2026-11-02'))
    expect(past).toEqual({ kind: 'past', to: '2026-10-27', confirmOn: '2026-11-02', loss: '120만원' })
    expect(guideText(past!, 'by_date')).toEqual({
      status: '확정일 11월 2일(월) · 그날 추가손실 120만원',
      button: '결정 기한으로 당기기',
    })
  })

  it('확정일이 곡선 밖이면 금액 없이 마감일 지남, 기간 안 없음은 안내 없음', () => {
    const outside = deadlineGuide(result('by_date', '2026-10-27', points, '2027-01-30'))
    expect(guideText(outside!, 'by_date').status).toBe('확정일 1월 30일(토) · 결정 기한 지남')
    expect(deadlineGuide(result('none_in_horizon', '2026-11-18', curve('2026-10-20', 30, 29)))).toBeNull()
  })

  it('오늘 확정해야 하면 기본(기준일)은 따로 적지 않고, 확정일을 늦췄으면 오늘로 당기기', () => {
    const now = curve('2026-10-20', 30, 0)
    expect(deadlineGuide(result('confirm_now', '2026-10-20', now))).toBeNull()
    const late = deadlineGuide(result('confirm_now', '2026-10-20', now, '2026-10-23'))
    expect(guideText(late!, 'confirm_now')).toEqual({
      status: '확정일 10월 23일(금) · 그날 추가손실 120만원',
      button: '오늘로 당기기',
    })
  })

  it('성질: 어느 확정일이든 단추가 가리키는 날은 결과의 마감일뿐이고, 앞뒤 판단은 날짜 순서와 같음', () => {
    for (let i = 0; i < points.length; i += 1) {
      const confirmOn = points[i].confirm_on
      const guide = deadlineGuide(result('by_date', '2026-10-27', points, confirmOn))!
      if (guide.kind !== 'on') expect(guide.to).toBe('2026-10-27')
      expect(guide.kind).toBe(i < 7 ? 'later' : i === 7 ? 'on' : 'past')
      if (guide.kind === 'past') expect(guide.loss).toBe(lossText(points[i].additional_loss))
    }
  })
})

describe('주말 결정 기한: 단추는 근무일(서버 decide_by_workday), 표시는 그대로', () => {
  // 결정 기한 11월 8일(일) — 그 앞 마지막 근무일 11월 6일(금)
  const points = curve('2026-10-20', 30, 19)
  const weekend = (confirmOn?: string) => result('by_date', '2026-11-08', points, confirmOn, '2026-11-06')

  it('보조 설명 끝에 근무일 기준 날짜(D-n·결정 기한 날짜는 그대로), 핵심 수치 카드도 같은 글', () => {
    expect(deadlineWorkday(weekend())).toBe('2026-11-06')
    expect(deadlineDetail({ kind: 'by_date', last_day: '2026-11-08' }, points, '2026-11-06')).toBe(
      '11월 8일(일)까지 추가손실 0 · 다음 날부터 +120만원 · 근무일 기준 11월 6일(금)',
    )
    const card = keyNumbers({
      ...weekend(),
      total: amount(1_000_000),
      cost_lines: [],
      schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: null },
    } as unknown as AnalysisResult).find((c) => c.id === 'deadline')!
    expect([card.value, card.detail]).toEqual(['D-19', '11월 8일(일)까지 추가손실 0 · 다음 날부터 +120만원 · 근무일 기준 11월 6일(금)'])
  })

  it('평일 기한(근무일 = 그날)·오늘·기간 안 없음·기준일 뒤 근무일 없음·옛 응답이면 근무일을 따로 쓰지 않음', () => {
    expect(deadlineWorkday(result('by_date', '2026-10-27', curve('2026-10-20', 30, 7), undefined, '2026-10-27'))).toBeNull()
    expect(deadlineWorkday(result('confirm_now', '2026-10-24', curve('2026-10-20', 30, 0), undefined, '2026-10-23'))).toBeNull()
    expect(deadlineWorkday(result('none_in_horizon', '2026-11-18', curve('2026-10-20', 30, 29)))).toBeNull()
    expect(deadlineWorkday(result('by_date', '2026-10-18', points, undefined, '2026-10-16'))).toBeNull() // 기준일 10월 20일보다 앞
    expect(deadlineWorkday(result('by_date', '2026-11-08', points))).toBeNull()
    expect(deadlineDetail({ kind: 'by_date', last_day: '2026-11-08' }, points)).not.toContain('근무일')
  })

  it('확정일 단추·상태: 근무일 앞이면 근무일로, 근무일이면 근무일 기준 결정 기한, 그 사이 주말은 기한 안, 기한 뒤면 근무일로 당기기', () => {
    const later = deadlineGuide(weekend())!
    expect(later).toEqual({ kind: 'later', to: '2026-11-06' })
    expect(guideText(later, 'by_date').button).toBe('확정일을 11월 6일(금)로')
    expect(guideText(deadlineGuide(weekend('2026-11-06'))!, 'by_date')).toEqual({ status: '확정일 = 결정 기한(근무일 기준)', button: null })
    expect(guideText(deadlineGuide(weekend('2026-11-07'))!, 'by_date').status).toBe('확정일 · 결정 기한 안')
    expect(guideText(deadlineGuide(weekend('2026-11-08'))!, 'by_date').status).toBe('확정일 = 결정 기한')
    const past = deadlineGuide(weekend('2026-11-09'))!
    expect(past).toMatchObject({ kind: 'past', to: '2026-11-06' })
    expect(guideText(past, 'by_date').button).toBe('결정 기한으로 당기기')
  })

  it('기준일 토요일 · 결정 기한 일요일(기준일 뒤 근무일 없음): 일요일을 권하지 않고 상태 줄만', () => {
    // 서버는 근무일이 업무상 오늘보다 앞이면 decide_by_workday를 비우고(null), 옛 서버는 지난 금요일을 실었다
    const saturday = (workday?: string | null, confirmOn?: string) =>
      ({
        request: { as_of: '2026-10-24', holds: [], ...(confirmOn ? { confirm_on: confirmOn } : {}) },
        timing: { deadline: { kind: 'by_date', last_day: '2026-10-25' }, curve: curve('2026-10-24', 30, 1), holds: [], reallocations: [] },
        ...(workday !== undefined ? { approval_plan: { decide_by_workday: workday } } : {}),
      }) as unknown as AnalysisResult
    for (const r of [saturday(null), saturday('2026-10-23'), saturday()]) {
      expect(deadlineWorkday(r)).toBeNull()
      const guide = deadlineGuide(r)!
      expect(guide).toEqual({ kind: 'on', at: 'within' })
      expect(guideText(guide, 'by_date')).toEqual({ status: '확정일 · 결정 기한 안', button: null })
    }
    expect(guideText(deadlineGuide(saturday(null, '2026-10-25'))!, 'by_date').status).toBe('확정일 = 결정 기한')
    expect(deadlineGuide(saturday(null, '2026-10-26'))).toMatchObject({ kind: 'past', to: '2026-10-25' })
    // 평일 결정 기한은 근무일이 없어도 그대로 그날로 미루는 단추
    expect(deadlineGuide(result('by_date', '2026-10-27', curve('2026-10-20', 30, 7)))).toEqual({ kind: 'later', to: '2026-10-27' })
  })

  it('성질: 어느 확정일이든 단추는 근무일만 가리키고(주말을 권하지 않음), 근무일~결정 기한 사이는 단추 없음', () => {
    for (const point of points) {
      const guide = deadlineGuide(weekend(point.confirm_on))!
      if (guide.kind !== 'on') expect(guide.to).toBe('2026-11-06')
      const expected = point.confirm_on < '2026-11-06' ? 'later' : point.confirm_on <= '2026-11-08' ? 'on' : 'past'
      expect(guide.kind).toBe(expected)
    }
  })
})
