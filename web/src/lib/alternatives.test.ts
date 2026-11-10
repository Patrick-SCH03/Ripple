import { describe, expect, it } from 'vitest'
import type { AnalysisRequest, AnalysisResult } from '@/api/client'
import {
  alternativesKey,
  earliestText,
  keepUntilText,
  mayHaveAlternatives,
  opText,
  ratioText,
  recommendationHeadline,
  recommendationKeepText,
  requestFor,
  shortName,
  sortedAlternatives,
  spanSentences,
  spanTitle,
} from './alternatives'

type Alternative = AnalysisResult['alternatives'][number]

const amount = (value: number) => ({ value, low: value, high: value })

function alt(over: Partial<Alternative> & Pick<Alternative, 'alt_id'>): Alternative {
  return {
    label: over.alt_id,
    origin: 'template',
    ops: [{ op: 'thickness', part_ids: ['S-001:B31P-PL-002'], from_mm: 17, to_mm: 20 }],
    scope_reduced: false,
    eligibility: { status: 'meets', criterion: 'x', basis: '', ratio_vs_request: 1, note: '' },
    total: amount(1_000_000),
    max_exit_delay_days: 0,
    impacted_count: 1,
    deadline: { kind: 'by_date', last_day: '2026-10-27' },
    best_confirm_on: '2026-10-20',
    best_total: amount(1_000_000),
    best_holds: [],
    rank: 1,
    ...over,
  } as Alternative
}

const request = alt({ alt_id: 'ALT-REQ', label: '요청안: 판 두께 17 → 20mm(3장)', origin: 'request', total: amount(35_288_231), best_total: amount(35_288_231), rank: 2 })
const stiffener = alt({ alt_id: 'ALT-T1', label: '판 두께 대신 보강재 추가(판 3장에 보강재 11개)', total: amount(6_237_861), best_total: amount(6_237_861), rank: 1, eligibility: { status: 'meets', criterion: 'x', basis: '', ratio_vs_request: 1.657, note: '' } })
const scoped = alt({ alt_id: 'ALT-T5', label: '적용 범위 축소(판 3장 중 2장)', total: amount(22_660_058), rank: null, best_total: null, best_confirm_on: null, scope_reduced: true, eligibility: { status: 'designer', criterion: 'x', basis: '', ratio_vs_request: null, note: '설계자' } })
const grade = alt({ alt_id: 'ALT-T2', label: '강종 상향(A → AH32)', total: amount(4_519_018), rank: null, best_total: null, best_confirm_on: null, eligibility: { status: 'short', criterion: 'x', basis: '', ratio_vs_request: 0.971, note: '' } })

describe('대안 결과 키', () => {
  it('분석 ID가 같아도 변경 사유가 다르면 다른 키(사유 미정 → 강도 보강 → 규칙·선급 요구)', () => {
    const base = { analysis_id: 'A-same', request: { change: { intent: null } } } as unknown as AnalysisResult
    const keys = [null, 'strength', 'rule_change'].map((intent) =>
      alternativesKey({ ...base, request: { ...base.request, change: { ...base.request.change, intent } } } as AnalysisResult),
    )
    expect(new Set(keys).size).toBe(3)
    expect(alternativesKey(base)).toBe('A-same|none')
  })
})

describe('대안이 생길 수 있는 요청(엔진 plan과 같은 조건)', () => {
  const req = (ops: { op: string }[], intent: string | null = null) =>
    ({ change: { ops, intent } }) as unknown as Pick<AnalysisRequest, 'change'>
  it('연산 하나 · 판 두께·강종·보강재 추가 · 사유 없음이나 강도 보강', () => {
    expect(mayHaveAlternatives(req([{ op: 'thickness' }]))).toBe(true)
    expect(mayHaveAlternatives(req([{ op: 'grade' }], 'strength'))).toBe(true)
    expect(mayHaveAlternatives(req([{ op: 'add_part' }]))).toBe(true)
  })
  it('배관·장비·삭제, 연산 여럿, 강도 밖 사유는 계산을 보내지 않음', () => {
    expect(mayHaveAlternatives(req([{ op: 'reroute_pipe' }]))).toBe(false)
    expect(mayHaveAlternatives(req([{ op: 'remove_part' }]))).toBe(false)
    expect(mayHaveAlternatives(req([{ op: 'thickness' }, { op: 'grade' }]))).toBe(false)
    expect(mayHaveAlternatives(req([{ op: 'thickness' }], 'rule_change'))).toBe(false)
  })
})

describe('대안 표', () => {
  it('요청안 → 충족(순위) → 나머지(총액 작은 순)', () => {
    expect(sortedAlternatives([scoped, stiffener, grade, request]).map((a) => a.alt_id)).toEqual([
      'ALT-REQ',
      'ALT-T1',
      'ALT-T2',
      'ALT-T5',
    ])
  })

  it('판정 비율은 소수 둘째 자리, 요청안·판정 안 한 대안은 없음', () => {
    expect(ratioText(stiffener)).toBe('요청안 대비 강도 여유 1.66배')
    expect(ratioText(request)).toBeNull()
    expect(ratioText(scoped)).toBeNull()
  })

  it('짧은 이름은 괄호 앞, 요청안은 요청안', () => {
    expect(shortName(stiffener)).toBe('판 두께 대신 보강재 추가')
    expect(shortName(request)).toBe('요청안')
  })
})

describe('권고', () => {
  it('요청안이 아닌 대안을 권고하면 요청안 대비 차이를 만원으로', () => {
    const headline = recommendationHeadline({
      alternatives: [request, stiffener],
      recommendation: { alt_id: 'ALT-T1', confirm_on: '2026-10-20', holds: [], total: amount(6_237_861) },
    })
    expect(headline?.title).toBe('판 두께 대신 보강재 추가(판 3장에 보강재 11개)')
    expect(headline?.detail).toBe('10월 20일(화) 확정 시 624만원 · 요청안(3,529만원)보다 2,905만원 적음')
  })

  it('요청안이 가장 싸면 그렇게 말하고, 보류가 있으면 발주를 적음', () => {
    const headline = recommendationHeadline({
      alternatives: [request],
      recommendation: {
        alt_id: 'ALT-REQ',
        confirm_on: '2026-10-20',
        holds: [{ po_id: 'PO-0037', hold_days: 5 }],
        total: amount(35_288_231),
      },
    })
    expect(headline?.title).toBe('요청안이 최저가')
    expect(headline?.detail).toContain(' · 발주 PO-0037 5일 보류 포함')
  })

  it('확정일을 늦게 잡으면 그날부터 골랐다는 안내, 기준일이거나 비면 없음', () => {
    expect(earliestText({ as_of: '2026-10-20', confirm_on: '2026-10-30' })).toBe(
      '10월 30일(금) 전 확정 불가로 보고 그날부터 최저가 조합 선택',
    )
    expect(earliestText({ as_of: '2026-10-20', confirm_on: '2026-10-20' })).toBeNull()
    expect(earliestText({ as_of: '2026-10-20', confirm_on: null })).toBeNull()
  })

  it('권고 카드 마감일 문장은 권고 확정일이 마감일 안일 때만(확정 가능일이 마감일 뒤면 뺌)', () => {
    const rec = (confirm_on: string) => ({ alt_id: 'ALT-REQ', confirm_on, holds: [], total: amount(35_288_231) })
    expect(recommendationKeepText({ alternatives: [request], recommendation: rec('2026-10-20') })).toBe(
      '10월 27일(화)까지 확정 시 금액 그대로',
    )
    expect(recommendationKeepText({ alternatives: [request], recommendation: rec('2026-10-27') })).toBe(
      '10월 27일(화)까지 확정 시 금액 그대로',
    )
    expect(recommendationKeepText({ alternatives: [request], recommendation: rec('2026-10-30') })).toBeNull()
    const now = alt({ alt_id: 'ALT-REQ', deadline: { kind: 'confirm_now', last_day: '2026-10-20' } })
    expect(recommendationKeepText({ alternatives: [now], recommendation: rec('2026-10-20') })).toBe('오늘 확정해야 이 금액')
    expect(recommendationKeepText({ alternatives: [now], recommendation: rec('2026-10-21') })).toBeNull()
    expect(recommendationKeepText({ alternatives: [request], recommendation: null })).toBeNull()
  })

  it('마감일 문장: 날짜까지·오늘·기간 안 없음', () => {
    expect(keepUntilText(stiffener)).toBe('10월 27일(화)까지 확정 시 금액 그대로')
    expect(keepUntilText({ deadline: { kind: 'confirm_now', last_day: '2026-10-20' } })).toBe('오늘 확정해야 이 금액')
    expect(keepUntilText({ deadline: { kind: 'none_in_horizon', last_day: '2026-12-19' } })).toBe(
      '12월 19일(토)까지 늦게 확정해도 금액 그대로',
    )
  })
})

describe('날짜별 최저 비용 대안', () => {
  const names: Record<string, string> = { 'ALT-REQ': '요청안', 'ALT-T1': '판 두께 대신 보강재 추가' }
  it('구간이 하나면 문장을 내지 않음', () => {
    expect(spanSentences([{ alt_id: 'ALT-T1', start: '2026-10-20', end: '2026-12-19', total: amount(1) }], (id) => names[id])).toBeNull()
  })

  it('첫 구간은 끝일까지, 마지막 구간은 시작일부터', () => {
    const lines = spanSentences(
      [
        { alt_id: 'ALT-REQ', start: '2026-10-20', end: '2026-11-06', total: amount(983_756) },
        { alt_id: 'ALT-T1', start: '2026-11-07', end: '2026-12-19', total: amount(1_550_278) },
      ],
      (id) => names[id],
    )
    expect(lines).toEqual([
      '11월 6일(금)까지 확정 시 요청안 최저가(기준일 98만원)',
      '11월 7일(토)부터 판 두께 대신 보강재 추가 최저가(155만원부터)',
    ])
  })

  it('제목: 요청에 보류가 없으면 보류 없이, 넣었으면 그 보류(발주·일수)를 적음', () => {
    expect(spanTitle({ holds: [] })).toBe('보류 없이 확정을 미루면')
    expect(spanTitle({ holds: [{ po_id: 'PO-0098', hold_days: 23 }] })).toBe('넣은 보류(발주 PO-0098 23일) 그대로 확정을 미루면')
    expect(
      spanTitle({
        holds: [
          { po_id: 'PO-0037', hold_days: 5 },
          { po_id: 'PO-0098', hold_days: 23 },
        ],
      }),
    ).toBe('넣은 보류(발주 PO-0037 5일·발주 PO-0098 23일) 그대로 확정을 미루면')
  })
})

describe('연산과 다시 분석', () => {
  it('연산 요약', () => {
    expect(opText({ op: 'thickness', part_ids: ['a', 'b'], from_mm: 17, to_mm: 20 })).toBe('판 2장 두께 17 → 20mm')
    expect(opText({ op: 'grade', part_ids: ['a'], from_grade: 'A', to_grade: 'AH32' })).toBe('1개 강종 A → AH32')
    expect(
      opText({ op: 'add_part', block_id: 'S-001:B31P', kind: 'stiffener', spec_id: 'HP240x11-AH36', qty: 0.406, attach_to_part_id: 'a' }),
    ).toBe('보강재 HP240x11-AH36 0.406t 추가')
  })

  it('대안으로 다시 분석: 연산만 바꾸고 제목에 대안 이름, 대안 판정은 끔', () => {
    const base = {
      change: { ecn_id: 'ECN-D-0119', title: 'B31P 판 두께', ship_ids: ['S-001'], intent: 'strength', ops: request.ops },
      as_of: '2026-10-20',
      include_alternatives: true,
    } as AnalysisRequest
    const next = requestFor(base, stiffener)
    expect(next.include_alternatives).toBe(false)
    expect(next.change.ops).toBe(stiffener.ops)
    expect(next.change.title).toBe('B31P 판 두께 — 대안: 판 두께 대신 보강재 추가(판 3장에 보강재 11개)')
    expect(next.change.ecn_id).toBe('ECN-D-0119')
  })
})
