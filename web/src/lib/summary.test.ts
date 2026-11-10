import { describe, expect, it } from 'vitest'
import type { AnalysisResult, CostLine, CurvePoint, OnboardOption } from '@/api/client'
import { cardLine, curveSteps, exitSlip, keyNumbers, slipText, sortedLines, todoText, todos } from './summary'

const amount = (value: number, low = value, high = value) => ({ value, low, high })

function line(line_id: string, value: number): CostLine {
  return {
    line_id,
    rule_id: line_id.split(':')[0],
    entity_id: line_id.split(':').slice(2).join(':'),
    label: line_id,
    formula: '',
    inputs: {},
    amount: amount(value),
    determinacy: 'known',
    sources: [],
    param_keys: [],
    factors: [],
  }
}

function point(day: string, total: number, events: string[] = []): CurvePoint {
  return { confirm_on: day, total: amount(total), additional_loss: amount(total - 100), max_exit_delay_days: 0, events }
}

function result(over: Record<string, unknown> = {}): AnalysisResult {
  const base = {
    request: { as_of: '2026-10-20', holds: [] },
    total: amount(2984205, 664313, 7893318),
    cost_lines: [],
    schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 0 } },
    timing: { deadline: { kind: 'by_date', last_day: '2026-10-31' }, holds: [], reallocations: [], curve: [] },
  }
  return { ...base, ...over } as unknown as AnalysisResult
}

describe('핵심 수치 카드', () => {
  it('총변경비용은 대표값과 범위, 범위가 없으면 세부 없음', () => {
    const [total] = keyNumbers(result())
    expect(total).toMatchObject({ id: 'total', value: '298만원', detail: '66만~789만원' })
    expect(keyNumbers(result({ total: amount(8500) }))[0].detail).toBeUndefined()
  })

  it('마감일: D-n(3일 이하는 위험 색) · 오늘 · 기간 안 없음', () => {
    const deadline = (kind: string, last_day: string) =>
      keyNumbers(result({ timing: { ...result().timing, deadline: { kind, last_day } } }))[1]
    expect(deadline('by_date', '2026-10-31')).toMatchObject({ value: 'D-11', tone: 'neutral' })
    expect(deadline('by_date', '2026-10-23')).toMatchObject({ value: 'D-3', tone: 'danger' })
    expect(deadline('confirm_now', '2026-10-20')).toMatchObject({ value: '오늘', tone: 'danger' })
    expect(deadline('none_in_horizon', '2026-12-19')).toMatchObject({ value: '기간 안 없음', tone: 'success' })
  })

  it('결정 기한 보조 설명: 그날까지 확정하면 추가손실 0 · 다음 날부터 늘어나는 금액(곡선 값)', () => {
    const curve = [point('2026-10-20', 100), point('2026-10-31', 100), point('2026-11-01', 1_200_100)]
    const timing = { ...result().timing, curve, deadline: { kind: 'by_date', last_day: '2026-10-31' } }
    expect(keyNumbers(result({ timing }))[1].detail).toBe(
      '10월 31일(토)까지 추가손실 0 · 다음 날부터 +120만원',
    )
  })

  it('출구 지연·인도 지연은 0보다 클 때만, 출구는 가장 늦는 구역', () => {
    expect(keyNumbers(result()).map((card) => card.id)).toEqual(['total', 'deadline'])
    const exits = [
      { zone_id: 'S-001:ZER', zone_name: '기관실·펌프룸', exit_activity_id: 'x', base_date: '2027-02-20', new_date: '2027-02-23', delay_days: 3 },
      { zone_id: 'S-001:ZCT', zone_name: '화물탱크 구역', exit_activity_id: 'y', base_date: '2027-01-16', new_date: '2027-03-25', delay_days: 68 },
    ]
    const late = result({
      schedule: { zone_exits: exits, max_exit_delay_days: 68, delivery: { added_delay_days: 36 } },
      cost_lines: [line('R-L01:ld:S-001', 216_000_000)],
    })
    const cards = keyNumbers(late)
    expect(cards.map((card) => card.id)).toEqual(['total', 'deadline', 'exit', 'delivery'])
    expect(cards[2]).toMatchObject({ value: '68일', detail: '화물탱크 구역 출구 1월 16일(토) → 3월 25일(목)' })
    const unnamed = keyNumbers(
      result({ schedule: { zone_exits: [{ ...exits[1], zone_name: '' }], max_exit_delay_days: 68, delivery: null } }),
    )
    expect(unnamed[2]).toMatchObject({ detail: 'ZCT 출구 1월 16일(토) → 3월 25일(목)' })
    expect(cards[3]).toMatchObject({ value: '36일', detail: '지체상금 2억 1,600만원' })
    const grace = keyNumbers(result({ schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 5 } } }))
    expect(grace[2]).toMatchObject({ id: 'delivery', detail: '유예 기간 안 · 지체상금 없음' })
    const unknown = keyNumbers(result({ schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: null } }))
    expect(unknown.map((card) => card.id)).toEqual(['total', 'deadline'])
  })

  it('선주 요청(허용 지연)이면 인도 카드가 지체상금 대신 인도일 조정, 노출 금액은 주의 한 줄', () => {
    const delivery = { added_delay_days: 36, permissible: true, exposure: amount(158_400_000, 115_200_000, 223_200_000) }
    const cards = keyNumbers(result({ schedule: { zone_exits: [], max_exit_delay_days: 0, delivery } }))
    expect(cards[2]).toMatchObject({
      id: 'delivery',
      value: '36일',
      detail: '선주 요청 · 인도일 조정 대상(지체상금 제외)',
      caution: '합의 불발 시 지체상금 1억 5,840만원(1억 1,520만~2억 2,320만원)',
    })
    // 유예 안이라 노출 금액이 없으면 주의도 없다
    const grace = { added_delay_days: 5, permissible: true, exposure: null }
    expect(keyNumbers(result({ schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: grace } }))[2].caution).toBeUndefined()
  })

  it('상세 카드 보조 한 줄: 주의가 있으면 그것(범위 없이), 없으면 보조 설명, 총변경비용 범위는 싣지 않음', () => {
    const delivery = { added_delay_days: 36, permissible: true, exposure: amount(158_400_000, 115_200_000, 223_200_000) }
    const [total, , owner] = keyNumbers(result({ schedule: { zone_exits: [], max_exit_delay_days: 0, delivery } }))
    expect(cardLine(total)).toBeNull()
    expect(cardLine(owner)).toEqual({ text: '합의 불발 시 지체상금 1억 5,840만원', tone: 'warning' })
    const grace = { added_delay_days: 5, permissible: true, exposure: null }
    const [, , noExposure] = keyNumbers(result({ schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: grace } }))
    expect(cardLine(noExposure)).toEqual({ text: '선주 요청 · 인도일 조정 대상(지체상금 제외)', tone: 'neutral' })
    // 줄은 언제나 하나: 숫자를 되풀이하거나 범위를 품은 줄은 없다
    for (const card of [total, owner, noExposure]) expect(cardLine(card)?.text ?? '').not.toMatch(/~/)
  })
})

describe('구역 출구 카드의 일정 위험', () => {
  const at = (days: number) => ({
    zone_id: 'S-001:ZCT',
    zone_name: '화물탱크 구역',
    exit_activity_id: 'S-001:ZCT:exit',
    base_date: '2027-01-16',
    new_date: days === 9 ? '2027-01-25' : days === 70 ? '2027-03-27' : '2027-03-25',
    delay_days: days,
  })
  const withRisk = (rep: number, risk: number | null, ratios: Record<string, number> = { plate: 1.2 }) =>
    keyNumbers(
      result({
        schedule: {
          zone_exits: rep > 0 ? [at(rep)] : [],
          max_exit_delay_days: rep,
          delivery: { added_delay_days: 0 },
          risk:
            risk === null
              ? null
              : { ratios, zone_exits: risk > 0 ? [at(risk)] : [], max_exit_delay_days: risk, delivery: null, unresolved: [] },
        },
      }),
    ).find((card) => card.id === 'exit')

  it('위험이 대표보다 크면 대표 0일이어도 카드(대표 기준 설명 + 경고 한 줄), 같거나 없으면 경고 없음', () => {
    expect(withRisk(0, 9)).toMatchObject({
      value: '0일',
      detail: '대표 일정으로는 지연 없음',
      caution: '자재가 늦게 오면 최대 9일(판재 × 1.2)',
      tone: 'neutral',
    })
    expect(withRisk(68, 70, { valve: 3, plate: 1.2 })).toMatchObject({
      value: '68일',
      caution: '자재가 늦게 오면 최대 70일(판재 × 1.2 · 밸브 × 3)',
      tone: 'danger',
    })
    expect(withRisk(68, 68)?.caution).toBeUndefined()
    expect(withRisk(68, null)?.caution).toBeUndefined()
  })

  it('외자재 운송(1.33.0): 위험 일정이 더한 운송 일수를 한 마디 붙이고, 방식이 비어 선박으로 가정했으면 그 말도', () => {
    const card = (transport: { mode: 'air' | 'sea'; days: number; assumed: boolean }[]) =>
      keyNumbers(
        result({
          schedule: {
            zone_exits: [],
            max_exit_delay_days: 0,
            delivery: { added_delay_days: 0 },
            risk: { ratios: { valve: 3 }, zone_exits: [at(43)], max_exit_delay_days: 43, delivery: null, unresolved: [], transport },
          },
        }),
      ).find((c) => c.id === 'exit')
    expect(card([{ mode: 'sea', days: 35, assumed: false }])?.caution).toBe(
      '자재가 늦게 오면 최대 43일(밸브 × 3 · 운송 선박 35일 포함)',
    )
    expect(card([{ mode: 'sea', days: 35, assumed: true }])?.caution).toBe(
      '자재가 늦게 오면 최대 43일(밸브 × 3 · 운송 선박 35일 포함(방식 없음 → 선박 가정))',
    )
    expect(card([])?.caution).toBe('자재가 늦게 오면 최대 43일(밸브 × 3)')
    expect(withRisk(0, 0)).toBeUndefined()
    expect(withRisk(0, null)).toBeUndefined()
  })
})

describe('마감일 카드의 일정 주의', () => {
  const exitAt = (day: string, delay: number): CurvePoint => ({ ...point(day, 100), max_exit_delay_days: delay })
  const curve = [exitAt('2026-10-20', 7), exitAt('2026-10-21', 8), exitAt('2026-10-27', 14), exitAt('2026-10-28', 18)]

  it('마감일까지 출구 지연이 늘면 기준일·마감일 일수, 늘지 않으면 없음', () => {
    expect(exitSlip(curve, '2026-10-27')).toEqual({ from: 7, to: 14 })
    expect(exitSlip([exitAt('2026-10-20', 3), exitAt('2026-10-27', 3)], '2026-10-27')).toBeNull()
    expect(exitSlip(curve, '2026-12-01')).toBeNull()
  })

  it('문장: 비용 변동 없어도 일정 악화(추가손실 0과 함께 읽혀도 오해 없게) — 지연이 있던 경우와 새로 생기는 경우', () => {
    expect(slipText({ from: 7, to: 14 }, '2026-10-27')).toBe(
      '비용 변동 없어도 일정 악화 · 출구 지연 기준일 7일 → 10월 27일(화) 확정 시 14일',
    )
    expect(slipText({ from: 0, to: 3 }, '2026-10-27')).toBe(
      '비용 변동 없어도 일정 악화 · 출구 지연 생김(10월 27일(화) 확정 시 3일)',
    )
  })

  it('마감일 카드에만 붙고, 오늘 확정해야 하면 붙지 않음', () => {
    const timing = { ...result().timing, curve, deadline: { kind: 'by_date', last_day: '2026-10-27' } }
    expect(keyNumbers(result({ timing }))[1].caution).toContain('기준일 7일 → 10월 27일(화) 확정 시 14일')
    const now = { ...timing, deadline: { kind: 'confirm_now', last_day: '2026-10-20' } }
    expect(keyNumbers(result({ timing: now }))[1].caution).toBeUndefined()
  })
})

describe('해야 할 일', () => {
  const advice = {
    po_id: 'PO-0130',
    rule_id: 'R-H01',
    max_hold_days: 22,
    hold_until: '2026-11-11',
    avoided: amount(6_909_000),
    reason: '',
    deadline_after: { kind: 'by_date', last_day: '2026-12-06' },
  }

  const onboard: OnboardOption = {
    direction: 'to_on_board',
    block_ids: ['S-001:E21C'],
    part_ids: ['NEW:4b53b84b:1', 'NEW:4b53b84b:2'],
    on_board_days: 1,
    total_change: amount(153_000, 21_600, 360_000),
    erection_delay_now_days: 21,
    erection_delay_then_days: 1,
    exit_delay_now_days: 0,
    exit_delay_then_days: 0,
    delivery_added_now_days: 0,
    delivery_added_then_days: 0,
  }

  it('적용한 보류 → 보류 권고 → 후행 설치 선택지 → 손실 보상 협의 → 자재 전용 순, 없으면 빈 목록', () => {
    expect(todos(result())).toEqual([])
    const full = result({
      request: { as_of: '2026-10-20', holds: [{ po_id: 'PO-0104', hold_days: 27 }] },
      timing: {
        ...result().timing,
        holds: [advice],
        reallocations: [{ lot_id: 'LOT-04', rule_id: 'R-M01', spec_id: 'PL', to_block_id: 'S-001:T31C', qty: 1.4578, saved: amount(1_189_320) }],
      },
      cost_lines: [line('R-T01:po_change:PO-0130#2', 1_000)],
      onboard,
    })
    expect(todos(full).map((todo) => todo.kind)).toEqual(['held', 'hold', 'onboard', 'consult', 'reallocation'])
  })

  it('후행 설치 선택지 글: 탑재·출구 지연 지금 → 바꾸면, 늘지 않은 인도 지연은 빼고, 비용 증감', () => {
    const deadline = { kind: 'by_date', last_day: '2026-10-31' } as const
    expect(todoText({ kind: 'onboard', option: onboard }, deadline)).toEqual({
      title: 'E21C 블록 의장품을 탑재 뒤 선상에서 설치하면',
      detail: '블록 탑재 지연 21일 → 1일 · 구역 출구 지연 그대로(0일) · 후행 설치 1일 · 비용 15만원 늘어남',
    })
    const back: OnboardOption = {
      ...onboard,
      direction: 'to_wait',
      total_change: amount(-76_500, -180_000, -10_800),
      erection_delay_now_days: 0,
      erection_delay_then_days: 1,
      exit_delay_now_days: 1,
      exit_delay_then_days: 1,
      delivery_added_now_days: 2,
      delivery_added_then_days: 2,
    }
    expect(todoText({ kind: 'onboard', option: back }, deadline)).toEqual({
      title: 'E21C 블록 탑재를 기다려 블록에서 설치하면',
      detail: '블록 탑재 지연 0일 → 1일 · 구역 출구 지연 그대로(1일) · 인도 지연 그대로(2일) · 비용 8만원 줄어듦',
    })
  })

  it('손실 보상 협의: 발주 변경·취소 손실(높은 값 > 0)이 있는 발주만, 품목은 발주로 모아 ID 순', () => {
    const lines = [
      line('R-T01:po_change:PO-0130#3', 5_000),
      line('R-M02:po_change:PO-0104#1', 2_000),
      line('R-T01:po_change:PO-0130#1', 1_000),
      line('R-T01:po_change:PO-0200#1', 0),
      line('R-T01:reorder:PO-0300#1', 9_000),
    ]
    const found = todos(result({ cost_lines: lines }))
    expect(found).toEqual([{ kind: 'consult', poIds: ['PO-0104', 'PO-0130'] }])
    expect(todoText(found[0], { kind: 'by_date', last_day: '2026-10-31' }).title).toBe(
      '발주 PO-0104, PO-0130 변경·취소 전 손실 보상 협의',
    )
    expect(todos(result({ cost_lines: [line('R-T01:po_change:PO-0200#1', 0)] }))).toEqual([])
  })

  it('손실 보상 협의: 발주 ID에 #가 있어도 품목 번호(마지막 #)만 떼고 서로 다른 발주를 합치지 않음', () => {
    const lines = [line('R-T01:po_change:PO#0131#1', 1_000), line('R-T01:po_change:PO#0130#2', 1_000)]
    expect(todos(result({ cost_lines: lines }))).toEqual([{ kind: 'consult', poIds: ['PO#0130', 'PO#0131'] }])
  })

  it('보류 권고 글: 최대 일수·기한, 결정 기한 변화, 피하는 손실', () => {
    const text = todoText({ kind: 'hold', advice } as never, { kind: 'by_date', last_day: '2026-11-29' })
    expect(text.title).toBe('발주 PO-0130 보류 권고')
    expect(text.detail).toBe('최대 22일(11월 11일(수)까지) · 결정 기한 11월 29일(일) → 12월 6일(일) · 피하는 손실 691만원')
  })

  it('보류 권고 글: 보류해도 결정 기한이 같으면 적지 않음(바뀌는 값만)', () => {
    const same = { ...advice, deadline_after: { kind: 'by_date', last_day: '2026-11-29' } }
    const text = todoText({ kind: 'hold', advice: same } as never, { kind: 'by_date', last_day: '2026-11-29' })
    expect(text.detail).toBe('최대 22일(11월 11일(수)까지) · 피하는 손실 691만원')
  })

  it('전용 글: 재고 로트와 잉여 자재(발주 품목)를 구분', () => {
    const deadline = { kind: 'by_date', last_day: '2026-10-31' } as const
    const stock = { lot_id: 'LOT-04', rule_id: 'R-M01', spec_id: 'PL', to_block_id: 'S-001:T31C', qty: 1.4578, saved: amount(1_189_320) }
    expect(todoText({ kind: 'reallocation', item: stock }, deadline)).toEqual({
      title: '재고 LOT-04 → T31C 블록에 사용',
      detail: '1.458t · 절감 비용 119만원',
    })
    const surplus = { ...stock, lot_id: 'PO-0104#2', to_block_id: 'S-001:F31C', qty: 0.17, saved: amount(-3_000) }
    expect(todoText({ kind: 'reallocation', item: surplus }, deadline)).toEqual({
      title: '잉여 자재 PO-0104#2 → F31C 블록으로 전용',
      detail: '0.170t · 추가 비용 3,000원',
    })
  })
})

describe('비용 줄·곡선 계단', () => {
  it('비용 줄은 대표값 큰 순, 같으면 줄 ID 순', () => {
    const sorted = sortedLines([line('R-T03:b', 21_000), line('C-01:a', -1_189_320), line('R-T03:a', 21_000), line('R-B01:x', 2_384_820)])
    expect(sorted.map((l) => l.line_id)).toEqual(['R-B01:x', 'R-T03:a', 'R-T03:b', 'C-01:a'])
  })

  it('계단은 첫날을 빼고 총액이 바뀌거나 사건이 있는 날', () => {
    const curve = [
      point('2026-10-20', 100),
      point('2026-10-21', 100),
      point('2026-10-22', 300, ['PO-0130#3 발주 변경·취소']),
      point('2026-10-23', 300),
      point('2026-10-24', 300, ['구역 출구 지연 2일']),
      point('2026-10-25', 250),
    ]
    expect(curveSteps(curve).map((step) => [step.day, step.added])).toEqual([
      ['2026-10-22', 200],
      ['2026-10-24', 200],
      ['2026-10-25', 150],
    ])
  })
})
