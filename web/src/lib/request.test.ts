import { describe, expect, it } from 'vitest'
import {
  causeName,
  conditionSummary,
  contextOf,
  parseRequest,
  reflectsRecord,
  sameRequest,
  withCause,
  withConfirmOn,
  withDesignStatus,
  withEffectiveOn,
  withHold,
  withOutfitOnBoard,
} from './request'

describe('요청 글 다루기', () => {
  const text = JSON.stringify({ as_of: '2026-10-20', change: {} })

  it('확정일을 넣고 빼도 나머지는 그대로', () => {
    const set = JSON.parse(withConfirmOn(text, '2026-11-01'))
    expect(set).toEqual({ as_of: '2026-10-20', change: {}, confirm_on: '2026-11-01' })
    expect(JSON.parse(withConfirmOn(JSON.stringify(set), null))).toEqual({ as_of: '2026-10-20', change: {} })
  })

  it('읽을 수 없는 글은 바꾸지 않고, 객체가 아니면 이유를 알려 줌', () => {
    expect(withConfirmOn('{oops', '2026-11-01')).toBe('{oops')
    expect(parseRequest('[1, 2]')).toEqual({ ok: false, reason: 'JSON 객체가 아님' })
    expect(parseRequest('null')).toEqual({ ok: false, reason: 'JSON 객체가 아님' })
    const broken = parseRequest('{oops')
    expect(broken.ok).toBe(false)
    expect(parseRequest(text)).toEqual({ ok: true, value: JSON.parse(text) })
  })
})

describe('withHold', () => {
  const base = JSON.stringify({ as_of: '2026-10-20', change: {}, holds: [] })

  it('보류를 넣었다 빼면 원래 요청과 같음', () => {
    const held = withHold(base, 'PO-0130', 22)
    expect(JSON.parse(held).holds).toEqual([{ po_id: 'PO-0130', hold_days: 22 }])
    expect(sameRequest(JSON.parse(withHold(held, 'PO-0130', null)), JSON.parse(base))).toBe(true)
  })

  it('같은 발주를 다시 넣으면 일수만 바뀌고, 다른 보류는 순서 그대로', () => {
    const two = withHold(withHold(base, 'PO-0104', 27), 'PO-0130', 22)
    expect(JSON.parse(withHold(two, 'PO-0104', 10)).holds).toEqual([
      { po_id: 'PO-0130', hold_days: 22 },
      { po_id: 'PO-0104', hold_days: 10 },
    ])
    expect(JSON.parse(withHold(two, 'PO-0104', null)).holds).toEqual([{ po_id: 'PO-0130', hold_days: 22 }])
  })

  it('holds가 없던 요청에도 넣고, 읽을 수 없는 글은 그대로', () => {
    const bare = JSON.stringify({ as_of: '2026-10-20' })
    expect(JSON.parse(withHold(bare, 'PO-1', 3)).holds).toEqual([{ po_id: 'PO-1', hold_days: 3 }])
    expect(withHold('{oops', 'PO-1', 3)).toBe('{oops')
  })
})

describe('contextOf', () => {
  it('요청에서 ECN 번호·제목·호선·기준일·확정일·탐색 기간을 읽음', () => {
    const request = {
      as_of: '2026-10-07',
      confirm_on: '2026-10-21',
      horizon_days: 90,
      change: { ecn_id: 'ECN-1', title: '판 두께 변경', ship_ids: ['S-001', 'S-002'] },
    }
    expect(contextOf(request)).toEqual({
      ecnId: 'ECN-1',
      title: '판 두께 변경',
      shipIds: ['S-001', 'S-002'],
      asOf: '2026-10-07',
      confirmOn: '2026-10-21',
      horizonDays: 90,
      designStatus: 'unknown',
      effectiveOn: null,
      cause: null,
    })
  })

  it('1.23.0 설계 승인 상태·적용 시작일을 읽고, 모르는 값은 미입력', () => {
    const change = { ecn_id: 'E', ship_ids: ['S-001'], design_status: 'owner_pending', effectivity: { effective_on: '2026-11-01' } }
    expect(contextOf({ change })).toMatchObject({ designStatus: 'owner_pending', effectiveOn: '2026-11-01' })
    expect(contextOf({ change: { ...change, design_status: 'nope', effectivity: 3 } })).toMatchObject({
      designStatus: 'unknown',
      effectiveOn: null,
      cause: null,
    })
  })

  it('없거나 형식이 다른 값은 비움(던지지 않음)', () => {
    const empty = {
      ecnId: null,
      title: null,
      shipIds: [],
      asOf: null,
      confirmOn: null,
      horizonDays: null,
      designStatus: 'unknown',
      effectiveOn: null,
      cause: null,
    }
    for (const value of [null, undefined, 3, 'x', [], {}, { change: [] }, { change: { ship_ids: 'S-001' } }]) {
      expect(contextOf(value)).toEqual(empty)
    }
    expect(contextOf({ as_of: 20261007, horizon_days: -3, change: { ecn_id: '', ship_ids: ['S-001', 7, null] } })).toEqual({
      ...empty,
      shipIds: ['S-001'],
    })
  })
})

describe('설계 승인·적용 시작일 고치기(1.23.0)', () => {
  const text = JSON.stringify({ as_of: '2026-10-20', change: { ecn_id: 'E', ship_ids: ['S-001'] } })
  it('미입력이면 필드를 빼고, 다른 값은 넣음(다른 필드는 그대로)', () => {
    const pending = JSON.parse(withDesignStatus(text, 'in_review'))
    expect(pending.change).toEqual({ ecn_id: 'E', ship_ids: ['S-001'], design_status: 'in_review' })
    expect(JSON.parse(withDesignStatus(JSON.stringify(pending), 'unknown')).change).toEqual({ ecn_id: 'E', ship_ids: ['S-001'] })
  })
  it('적용 시작일: 넣고 빼면 effectivity도 빠짐, 메모는 남김', () => {
    const set = JSON.parse(withEffectiveOn(text, '2026-11-01'))
    expect(set.change.effectivity).toEqual({ effective_on: '2026-11-01' })
    expect(JSON.parse(withEffectiveOn(JSON.stringify(set), null)).change.effectivity).toBeUndefined()
    const noted = JSON.stringify({ change: { effectivity: { effective_on: '2026-11-01', note: '2번선부터' } } })
    expect(JSON.parse(withEffectiveOn(noted, null)).change.effectivity).toEqual({ note: '2번선부터' })
  })
  it('읽을 수 없거나 change가 없으면 원문 그대로', () => {
    expect(withDesignStatus('{', 'approved')).toBe('{')
    expect(withEffectiveOn('{}', '2026-11-01')).toBe('{}')
  })
})

describe('후행 설치(1.29.0)', () => {
  it('켜면 필드가 생기고 끄면 키를 지워 필드가 없던 요청과 같아짐, 읽을 수 없으면 원문', () => {
    const text = JSON.stringify({ as_of: '2026-10-20', change: {} })
    const on = withOutfitOnBoard(text, true)
    expect(JSON.parse(on)).toEqual({ as_of: '2026-10-20', change: {}, outfit_on_board: true })
    expect(sameRequest(JSON.parse(withOutfitOnBoard(on, false)), JSON.parse(text))).toBe(true)
    expect(withOutfitOnBoard('{', true)).toBe('{')
  })
})

describe('변경 원인(1.28.0)', () => {
  const text = JSON.stringify({ as_of: '2026-10-20', change: { ecn_id: 'E', ship_ids: ['S-001'] } })
  it('넣고 빼면 필드가 생기고 사라짐(다른 필드는 그대로), 맥락에서 읽음', () => {
    const owner = withCause(text, 'owner_request')
    expect(JSON.parse(owner).change).toEqual({ ecn_id: 'E', ship_ids: ['S-001'], cause: 'owner_request' })
    expect(contextOf(JSON.parse(owner)).cause).toBe('owner_request')
    expect(JSON.parse(withCause(owner, null)).change).toEqual({ ecn_id: 'E', ship_ids: ['S-001'] })
    expect(withCause('{', 'production')).toBe('{')
  })
  it('모르는 값은 미입력', () => {
    expect(contextOf({ change: { cause: 'nope' } }).cause).toBeNull()
    expect(causeName('nope')).toBe('미입력')
    expect(causeName(undefined)).toBe('미입력')
    expect(causeName('class_rule')).toBe('선급·규정')
  })
})

describe('reflectsRecord', () => {
  const basis = { as_of: '2026-10-20', change: { ecn_id: 'ECN-AI-1', title: '횡격벽 판 두께', intent: null } }
  const shown = (body: unknown, analysis_id = 'A1') => ({ result: { analysis_id }, body })
  const draftOf = (body: unknown) => JSON.stringify(body, null, 2)

  it('상세가 사유를 기록하기 전 그 요청이고 초안을 고치지 않았으면 반영', () => {
    expect(reflectsRecord(shown(basis), draftOf(basis), basis, 'A1')).toBe(true)
  })

  it('분석 ID가 같아도 다른 요청(ECN 번호·제목·사유만 다름)을 보이면 반영하지 않음', () => {
    const otherEcn = { ...basis, change: { ...basis.change, ecn_id: 'ECN-B', title: '다른 요청' } }
    const otherReason = { ...basis, change: { ...basis.change, intent: 'owner_request' } }
    expect(reflectsRecord(shown(otherEcn), draftOf(otherEcn), basis, 'A1')).toBe(false)
    expect(reflectsRecord(shown(otherReason), draftOf(otherReason), basis, 'A1')).toBe(false)
  })

  it('초안을 고치는 중이거나 읽을 수 없거나, 다른 분석이거나 결과가 없으면 반영하지 않음', () => {
    const edited = { ...basis, confirm_on: '2026-11-30' }
    expect(reflectsRecord(shown(basis), draftOf(edited), basis, 'A1')).toBe(false)
    expect(reflectsRecord(shown(basis), '{oops', basis, 'A1')).toBe(false)
    expect(reflectsRecord(shown(basis, 'A2'), draftOf(basis), basis, 'A1')).toBe(false)
    expect(reflectsRecord(null, draftOf(basis), basis, 'A1')).toBe(false)
  })
})

describe('sameRequest', () => {
  it('키 순서·공백이 달라도 같은 요청', () => {
    const a = JSON.parse('{"as_of":"2026-10-07","change":{"ecn_id":"E","ops":[{"op":"thickness","to_mm":17}]}}')
    const b = JSON.parse('{ "change": { "ops": [ { "to_mm": 17, "op": "thickness" } ], "ecn_id": "E" }, "as_of": "2026-10-07" }')
    expect(sameRequest(a, b)).toBe(true)
  })

  it('값·배열 순서·확정일이 다르면 다른 요청', () => {
    const base = { as_of: '2026-10-07', change: { ops: [1, 2] } }
    expect(sameRequest(base, { ...base, as_of: '2026-10-08' })).toBe(false)
    expect(sameRequest(base, { ...base, change: { ops: [2, 1] } })).toBe(false)
    expect(sameRequest(base, { ...base, confirm_on: '2026-10-21' })).toBe(false)
    expect(sameRequest(JSON.parse(withConfirmOn(JSON.stringify(base), '2026-10-21')), { ...base, confirm_on: '2026-10-21' })).toBe(true)
  })
})

describe('conditionSummary', () => {
  const base = { ecnId: 'ECN-D-0038', title: '평형수 배관', shipIds: ['S-001'], asOf: '2026-10-20', confirmOn: null, horizonDays: 60 }

  it('확정일(없으면 기준일) · 설계 승인 · 변경 원인, 적용 시작일은 넣었을 때만', () => {
    expect(conditionSummary(base)).toBe('확정일 10월 20일(화) · 설계 승인 미입력 · 변경 원인 미입력')
    expect(
      conditionSummary({
        ...base,
        confirmOn: '2026-10-27',
        designStatus: 'owner_pending',
        effectiveOn: '2026-11-02',
        cause: 'owner_request',
      }),
    ).toBe('확정일 10월 27일(화) · 설계 승인 선주 승인 대기 · 적용 시작 11월 2일(월) · 변경 원인 선주 요청')
  })
})