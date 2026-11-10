import { describe, expect, it } from 'vitest'
import type { StateBasis } from '@/api/client'
import {
  OWNER,
  activityFixUpdate,
  foldedText,
  needOf,
  ownerSummary,
  poFixUpdate,
  quickConfirm,
  sortRows,
  stateText,
  viaText,
} from './stateBasis'

const TODAY = '2026-10-20'

function po(over: Partial<StateBasis> = {}): StateBasis {
  return {
    entity_type: 'po',
    entity_id: 'PO-0001',
    label: 'PO-0001',
    as_of: TODAY,
    po_status: 'ordered',
    basis: 'evidence',
    last_confirmed: '2026-10-18',
    line_ids: [],
    hold: false,
    via: [],
    actual_start: null,
    actual_finish: null,
    expected_start: null,
    ...over,
  }
}

function act(over: Partial<StateBasis> = {}): StateBasis {
  return po({ entity_type: 'activity', entity_id: 'S-001:B31P:assembly', po_status: null, ...over })
}

describe('판단이 걸린 상태: 순서', () => {
  it('근거 없음 → 계획 추정 → 7일 넘게 확인 안 함 → 괜찮음, 같으면 발주가 먼저', () => {
    const rows = [
      po({ entity_id: 'PO-ok' }),
      po({ entity_id: 'PO-stale', last_confirmed: '2026-10-01' }),
      act({ entity_id: 'A-plan', basis: 'plan', last_confirmed: null }),
      po({ entity_id: 'PO-plan', basis: 'off_plan' }),
      po({ entity_id: 'PO-unknown', basis: 'unknown', po_status: null }),
    ]
    expect(sortRows(rows, TODAY).map((r) => r.entity_id)).toEqual(['PO-unknown', 'PO-plan', 'A-plan', 'PO-stale', 'PO-ok'])
    expect(needOf(po({ last_confirmed: null }), TODAY)).toBe('stale')
    expect(needOf(po({ last_confirmed: '2026-10-13' }), TODAY)).toBe('ok')
    // 공정 미착수 현장 확인(근거는 계획 그대로)은 7일 동안 괜찮음, 발주의 계획 추정은 확인일과 무관하게 추정
    expect(needOf(act({ basis: 'plan', last_confirmed: TODAY }), TODAY)).toBe('ok')
    expect(needOf(act({ basis: 'plan', last_confirmed: null }), TODAY)).toBe('plan')
    expect(needOf(po({ basis: 'plan', last_confirmed: TODAY }), TODAY)).toBe('plan')
  })
})

describe('확인할 부서(발주 = 구매, 공정 = 생산관리)', () => {
  it('확인이 필요한 줄만 부서별로 세고, 모두 괜찮으면 null', () => {
    const rows = [
      po({ entity_id: 'PO-ok' }),
      po({ entity_id: 'PO-unknown', basis: 'unknown', po_status: null }),
      act({ entity_id: 'A-1', basis: 'plan', last_confirmed: null }),
      act({ entity_id: 'A-2', basis: 'plan', last_confirmed: null }),
    ]
    expect(ownerSummary(rows, TODAY)).toEqual({ count: 3, text: '구매 1 · 생산관리 2' })
    expect(ownerSummary([act({ basis: 'plan', last_confirmed: null })], TODAY)).toEqual({ count: 1, text: '생산관리 1' })
    expect(ownerSummary([po()], TODAY)).toBeNull()
    expect([OWNER.po, OWNER.activity]).toEqual(['구매', '생산관리'])
  })
})

describe('맞음: 오늘 상태만', () => {
  it('발주: 기준일이 오늘이면 그 단계를 오늘 관측으로', () => {
    const quick = quickConfirm(po(), TODAY)
    expect(quick).toEqual({
      kind: 'ok',
      label: '발주 맞음',
      update: { origin: 'confirm', items: [{ kind: 'po_status', po_id: 'PO-0001', status: 'ordered', observed_on: TODAY }] },
    })
  })

  it('기준일이 오늘이 아니면 막고 안내(미래·과거 예측을 오늘 사실로 남기지 않음)', () => {
    expect(quickConfirm(po({ as_of: '2026-10-19' }), TODAY).kind).toBe('blocked')
  })

  it('단계 판단 불가·가공은 바로 확인하지 않음(가공은 공정 착수로)', () => {
    expect(quickConfirm(po({ po_status: null, basis: 'unknown' }), TODAY).kind).toBe('blocked')
    expect(quickConfirm(po({ po_status: 'processed' }), TODAY).kind).toBe('blocked')
  })

  it('공정: 실적이 있으면 진행 중·완료, 예상 착수가 미래면 미착수, 계획상 착수일이 지났는데 실적이 없으면 막음', () => {
    const started = quickConfirm(act({ actual_start: '2026-10-10' }), TODAY)
    expect(started.kind === 'ok' && started.update.items[0]).toMatchObject({ kind: 'activity_check', state: 'in_progress' })
    const waiting = quickConfirm(act({ basis: 'plan', expected_start: '2026-10-25' }), TODAY)
    expect(waiting.kind === 'ok' && waiting.update.items[0]).toMatchObject({ state: 'not_started', confirmed_on: TODAY })
    expect(quickConfirm(act({ basis: 'plan', expected_start: '2026-10-15' }), TODAY).kind).toBe('blocked')
  })
})

describe('고치기', () => {
  it('발주: 단계 + 납기(리드타임) 변경, 잘못된 일수는 문장', () => {
    expect(poFixUpdate(po(), { status: 'received', leadTimeDays: '47' }, TODAY)).toEqual({
      origin: 'confirm',
      items: [
        { kind: 'po_status', po_id: 'PO-0001', status: 'received', observed_on: TODAY },
        { kind: 'po_plan', po_id: 'PO-0001', field: 'lead_time_days', value: 47 },
      ],
    })
    expect(typeof poFixUpdate(po(), { status: 'received', leadTimeDays: '0' }, TODAY)).toBe('string')
  })

  it('공정: 실제 날짜(오늘까지, 완료 ≥ 착수) + 확인, 미착수 확인은 실적이 없을 때만', () => {
    const fixed = activityFixUpdate(act(), { started: '2026-10-19', finished: '', notStarted: false }, TODAY)
    expect(typeof fixed !== 'string' && fixed.items.map((i) => i.kind)).toEqual(['activity_actual', 'activity_check'])
    expect(typeof activityFixUpdate(act(), { started: '2026-10-21', finished: '', notStarted: false }, TODAY)).toBe('string')
    expect(typeof activityFixUpdate(act(), { started: '2026-10-19', finished: '2026-10-18', notStarted: false }, TODAY)).toBe('string')
    expect(typeof activityFixUpdate(act({ actual_start: '2026-10-10' }), { started: '', finished: '', notStarted: true }, TODAY)).toBe('string')
  })
})

describe('표시', () => {
  it('상태 문장과 데려온 것', () => {
    expect(stateText(po({ po_status: null }))).toBe('단계 판단 불가')
    expect(stateText(act({ actual_start: '2026-10-10' }))).toContain('진행 중')
    expect(viaText(act({ via: ['PO-0001#1'] }))).toBe('품목 PO-0001#1을 쓰는 공정')
    expect(viaText(po({ via: ['S-001:B31P'] }))).toBe('블록 B31P 강재')
  })
})

describe('foldedText', () => {
  it('접힌 줄을 확인 필요·확인됨으로 나눠 센다, 접힌 줄이 없으면 null', () => {
    expect(foldedText(3, 0)).toBe('확인된 3개 더 보기')
    expect(foldedText(4, 1)).toBe('확인 필요 1개 · 확인된 3개 더 보기')
    expect(foldedText(2, 2)).toBe('확인 필요 2개 더 보기')
    expect(foldedText(0, 0)).toBeNull()
  })
})