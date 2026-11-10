// 블록별 강재 중량 변화(1.34.0): 중량 포맷 · 블록 줄 정렬 · 합계는 결과 값 그대로 · 옛 기록 · 정보 없음 블록.
import { describe, expect, it } from 'vitest'
import {
  COG_NOTE,
  WEIGHT_SOURCE_NAMES,
  blockLabel,
  formatDelta,
  formatTons,
  partsText,
  weightSummary,
  weightView,
  type BlockWeight,
  type WeightChangeData,
} from './weightChange'

function block(over: Partial<BlockWeight>): BlockWeight {
  return {
    block_id: 'S-001:B31P',
    name: 'No.3 COT 이중저 좌',
    before_t: 0,
    after_t: 0,
    delta_t: 0,
    counted: 0,
    missing: 0,
    parts: [],
    ...over,
  }
}

// ECN-D-0119(B31P 판 3장 17 → 20mm)의 엔진 값 그대로
const d0119: WeightChangeData = {
  blocks: [block({ before_t: 3.886, after_t: 4.571764, delta_t: 0.685764, counted: 3 })],
  before_t: 3.886,
  after_t: 4.571764,
  delta_t: 0.685764,
  counted: 3,
  missing: 0,
}

describe('formatTons · formatDelta', () => {
  it('소수 둘째 자리 t, 음수는 −, 작은 변화는 셋째 자리', () => {
    expect(formatTons(3.886)).toBe('3.89t')
    expect(formatTons(1234.5)).toBe('1,234.50t')
    expect(formatTons(0)).toBe('0.00t')
    expect(formatTons(-0.12)).toBe('−0.12t')
    expect(formatTons(0.004)).toBe('0.004t')
    expect(formatTons(-0.0004)).toBe('0.000t')
  })

  it('차이: 늘면 +, 줄면 −, 같으면 0.00t', () => {
    expect(formatDelta(0.685764)).toBe('+0.69t')
    expect(formatDelta(-0.4)).toBe('−0.40t')
    expect(formatDelta(0)).toBe('0.00t')
  })
})

describe('weightView', () => {
  it('ECN-D-0119: 블록 한 줄 B31P · 3.89t → 4.57t · +0.69t · 부재 3, 합계 = 결과 값', () => {
    const view = weightView(d0119)
    expect(view?.rows).toEqual([
      {
        key: 'S-001:B31P',
        code: 'B31P',
        name: 'No.3 COT 이중저 좌',
        before: '3.89t',
        after: '4.57t',
        delta: '+0.69t',
        parts: 3,
        missing: 0,
        unknown: false,
      },
    ])
    expect(view?.total).toEqual({ before: '3.89t', after: '4.57t', delta: '+0.69t', parts: 3, missing: 0 })
    expect(view?.empty).toBe(false)
    expect(view?.missingNote).toBeNull()
  })

  it('정렬: 차이 크기 큰 순, 셀 수 있는 부재가 없는 블록은 끝(중량 칸 —)', () => {
    const view = weightView({
      blocks: [
        block({ block_id: 'S-001:A10', name: 'A10', delta_t: 0.1, after_t: 0.1, counted: 1 }),
        block({ block_id: 'S-001:B20', name: 'B20', delta_t: -0.5, before_t: 0.5, counted: 1 }),
        block({ block_id: 'S-001:C30', name: 'C30', missing: 2 }),
        block({ block_id: null, name: '블록 모름', delta_t: 0.2, after_t: 0.2, counted: 1 }),
      ],
      before_t: 0.5,
      after_t: 0.3,
      delta_t: -0.2,
      counted: 3,
      missing: 2,
    })
    expect(view?.rows.map((r) => r.key)).toEqual(['S-001:B20', '(블록 모름)', 'S-001:A10', 'S-001:C30'])
    expect(view?.rows.at(-1)).toMatchObject({ before: '—', after: '—', delta: '—', unknown: true, missing: 2 })
    expect(view?.rows[1]).toMatchObject({ code: null, name: '블록 모름' })
    expect(view?.total.delta).toBe('−0.20t')
    expect(view?.missingNote).toBe('중량 정보 없음 2개 · 합계 제외')
  })

  it('바뀌는 부재 없음 → 빈 줄 · empty, 옛 기록(필드 없음) → null', () => {
    const view = weightView({ blocks: [], before_t: 0, after_t: 0, delta_t: 0, counted: 0, missing: 0 })
    expect(view?.empty).toBe(true)
    expect(view?.rows).toEqual([])
    expect(weightView(undefined)).toBeNull()
    expect(weightView(null)).toBeNull()
  })
})

describe('보조 표기', () => {
  it('블록 이름: 코드 + 이름, 이름이 코드와 같으면 이름 생략', () => {
    expect(blockLabel({ block_id: 'S-001:B31P', name: 'No.3 COT 이중저 좌' })).toEqual({
      code: 'B31P',
      name: 'No.3 COT 이중저 좌',
    })
    expect(blockLabel({ block_id: 'S-001:A10', name: 'A10' })).toEqual({ code: 'A10', name: '' })
  })

  it('부재 수 칸 · 한 줄 요약 · 근거 이름 · 무게중심 안내', () => {
    expect(partsText({ parts: 3, missing: 0 })).toBe('3')
    expect(partsText({ parts: 2, missing: 1 })).toBe('2 · 정보 없음 1')
    expect(weightSummary(d0119)).toBe('강재 +0.69t(3.89t → 4.57t) · 블록 1 · 부재 3')
    expect(weightSummary({ blocks: [], before_t: 0, after_t: 0, delta_t: 0, counted: 0, missing: 0 })).toBeNull()
    expect(Object.keys(WEIGHT_SOURCE_NAMES).sort()).toEqual(['none', 'qty_t', 'weight_kg'])
    expect(COG_NOTE).toBe('무게중심: 좌표 정보 필요(다음 단계)')
  })
})
