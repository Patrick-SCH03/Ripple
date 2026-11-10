import { describe, expect, it } from 'vitest'
import type { AnalysisResult, DecisionBrief, EcnDetail, Me, PastCase } from '@/api/client'
import {
  briefFor,
  briefHead,
  briefTarget,
  casesToggleLabel,
  changeHead,
  checkTitle,
  cheaperOf,
  wantsCheaper,
  casesView,
  outcomeText,
  pickedLabel,
  syntheticCases,
  timingText,
} from './brief'

const lead = { permissions: ['view', 'approve'] } as unknown as Me
const member = { permissions: ['view', 'record'] } as unknown as Me

function detail(state: string, reviewRevision: number | null = 2): EcnDetail {
  return {
    status: {
      ecn_id: 'ECN-D-0119',
      state,
      review: reviewRevision === null ? null : { seq: 7, revision: reviewRevision },
    },
    revisions: [
      { revision: 1, record_id: 'R-0000000000000001' },
      { revision: 2, record_id: 'R-0000000000000002' },
    ],
  } as unknown as EcnDetail
}

const brief = (recordId: string, ecnId = 'ECN-D-0119') => ({ ecn_id: ecnId, record_id: recordId }) as DecisionBrief

describe('결정 도우미를 그릴 대상', () => {
  it('팀장 + 검토·보류 중이면 진행 중 검토 개정의 기록, 담당자·검토 밖·상세 없음은 null', () => {
    expect(briefTarget(lead, detail('in_review'))).toEqual({ ecnId: 'ECN-D-0119', recordId: 'R-0000000000000002' })
    expect(briefTarget(lead, detail('on_hold', 1))).toEqual({ ecnId: 'ECN-D-0119', recordId: 'R-0000000000000001' })
    expect(briefTarget(member, detail('in_review'))).toBeNull()
    expect(briefTarget(lead, detail('analyzed', null))).toBeNull()
    expect(briefTarget(lead, detail('approved', null))).toBeNull()
    expect(briefTarget(lead, null)).toBeNull()
    expect(briefTarget(null, detail('in_review'))).toBeNull()
  })

  it('받은 도우미는 같은 설계변경 · 같은 기록일 때만(새 개정이 오면 옛 도우미를 그리지 않음)', () => {
    const target = { ecnId: 'ECN-D-0119', recordId: 'R-0000000000000002' }
    expect(briefFor(brief('R-0000000000000002'), target)).toBe(true)
    expect(briefFor(brief('R-0000000000000001'), target)).toBe(false)
    expect(briefFor(brief('R-0000000000000002', 'ECN-D-0043'), target)).toBe(false)
  })
})

describe('결정 도우미 문구', () => {
  it('칩: AI는 확인할 것만 고른다는 범위, 아니면 기본 순서', () => {
    expect(pickedLabel('ai')).toBe('확인 항목 AI 선택')
    expect(pickedLabel('rule')).toBe('기본 순서')
  })

  const item = (predicted: number, actual: number | null): Pick<PastCase, 'predicted' | 'actual_krw'> => ({
    predicted: { value: predicted, low: predicted, high: predicted },
    actual_krw: actual,
  })

  it('예측 → 실적(차이 %, 반올림·부호), 실적 없음, 예측 0 이하는 % 없이', () => {
    expect(outcomeText(item(2_980_000, 3_300_000))).toBe('예측 298만원 → 실적 330만원(+11%)')
    expect(outcomeText(item(10_000_000, 9_500_000))).toBe('예측 1,000만원 → 실적 950만원(−5%)')
    expect(outcomeText(item(5_000_000, 5_000_000))).toBe('예측 500만원 → 실적 500만원(±0%)')
    expect(outcomeText(item(2_980_000, null))).toBe('예측 298만원 · 실적 없음')
    expect(outcomeText(item(0, 120_000))).toBe('예측 0원 → 실적 12만원')
  })

  it('마감 며칠 전 결정 · 마감일 · 마감 뒤 · 모름', () => {
    expect(timingText(3)).toBe('결정 기한 3일 전 결정')
    expect(timingText(0)).toBe('결정 기한 당일 결정')
    expect(timingText(-2)).toBe('결정 기한 2일 뒤 결정')
    expect(timingText(null)).toBeNull()
    expect(timingText(undefined)).toBeNull()
  })

  it('합성 과거 사례: 묶음 표시나 사례 하나라도 합성이면', () => {
    const one = { synthetic: true } as PastCase
    const real = { synthetic: false } as PastCase
    expect(syntheticCases({ items: [], synthetic: true, library_size: 0, status: 'ready' })).toBe(true)
    expect(syntheticCases({ items: [real, one], synthetic: false, library_size: 2, status: 'ready' })).toBe(true)
    expect(syntheticCases({ items: [real], synthetic: false, library_size: 1, status: 'ready' })).toBe(false)
  })

  it('과거 사례 펼치기 단추: 접혀 있으면 사례 n건 보기, 펼쳤으면 사례 접기', () => {
    expect(casesToggleLabel(3, false)).toBe('사례 3건 보기')
    expect(casesToggleLabel(3, true)).toBe('사례 접기')
  })

  it('과거 사례 절: 있으면 목록 · 만드는 중이면 한 줄 · 묶음 없음(unavailable)·0건이면 그리지 않음', () => {
    const one = { synthetic: true } as PastCase
    expect(casesView({ status: 'ready', items: [one] })).toBe('list')
    expect(casesView({ status: 'building', items: [] })).toBe('building')
    expect(casesView({ status: 'unavailable', items: [one] })).toBeNull()
    expect(casesView({ status: 'ready', items: [] })).toBeNull()
  })
})

describe('결정 도우미 한눈에 보기(큰 숫자 카드 · 바뀌는 것 · 확인할 것 제목)', () => {
  const LINES = {
    lines: [
      {
        kind: 'change' as const,
        template_id: 'change.summary',
        text: 'B31P 판 두께 17.0→20.0mm (3장) — 영향 20곳(블록 B31P, L31C) · 총변경비용 4,334만원(1,236만~1억 250만원) · 추가 공수 807 MH · 재료비 327만원',
      },
      {
        kind: 'loss' as const,
        template_id: 'loss.by_date',
        text: '11월 11일(수)까지(D-7) 확정 시 비용 그대로 — 다음 날부터 1,867만원 증가',
      },
      {
        kind: 'advice' as const,
        template_id: 'advice.cheaper',
        text: "더 저렴한 충족 대안 '판 두께 대신 보강재 추가(판 3장에 보강재 11개)' — 11월 4일(수) 확정 시 720만원, 요청안(4,334만원) 대비 3,614만원 절감",
      },
    ],
  }
  const revision = {
    total: { value: 43_340_000, low: 12_360_000, high: 102_500_000 },
    deadline: { kind: 'by_date' as const, last_day: '2026-11-11' },
  } as Parameters<typeof briefHead>[1]
  const curve = (nextDay: number) =>
    ({
      timing: {
        curve: [
          { confirm_on: '2026-11-11', additional_loss: { value: 0, low: 0, high: 0 } },
          { confirm_on: '2026-11-12', additional_loss: { value: nextDay, low: nextDay, high: nextDay } },
        ],
      },
    }) as unknown as Pick<AnalysisResult, 'timing'>
  const alternatives = {
    alternatives: [
      { alt_id: 'ALT-REQ', label: '요청안', total: { value: 43_340_000 }, best_total: { value: 43_340_000 } },
      { alt_id: 'ALT-1', label: '판 두께 대신 보강재 추가(판 3장에 보강재 11개)', total: { value: 7_200_000 } },
    ],
    recommendation: { alt_id: 'ALT-1', total: { value: 7_200_000 } },
  } as unknown as Pick<AnalysisResult, 'alternatives' | 'recommendation'>

  it('권고 대안 절감 = 요청안 최적 총액 − 권고 총액(서버 advice.cheaper와 같은 공식), 요청안이 권고·싸지 않으면 null', () => {
    expect(cheaperOf(alternatives)).toEqual({ name: '판 두께 대신 보강재 추가', total: 7_200_000, saving: 36_140_000 })
    const own = { ...alternatives, recommendation: { alt_id: 'ALT-REQ', total: { value: 43_340_000 } } }
    expect(cheaperOf(own as typeof alternatives)).toBeNull()
    expect(cheaperOf({ alternatives: [], recommendation: null } as unknown as typeof alternatives)).toBeNull()
    expect(wantsCheaper(LINES)).toBe(true)
  })

  it('카드 셋: 총변경비용(범위 없음) · D-7 + 그날까지 · 다음 날부터 +금액 · 권고 대안 절감 + 이름 · 총액', () => {
    const head = briefHead(LINES, revision, '2026-11-04', curve(18_670_000), cheaperOf(alternatives))
    expect(head.total).toEqual({ label: '총변경비용', value: '4,334만원', line: null, tone: 'neutral' })
    expect(head.deadline).toEqual({
      label: '결정 기한',
      value: 'D-7',
      line: '11월 11일(수)까지 · 다음 날부터 +1,867만원',
      tone: 'neutral',
    })
    expect(head.advice).toEqual({
      label: '권고 대안 절감',
      value: '3,614만원',
      line: '판 두께 대신 보강재 추가 · 720만원',
      tone: 'success',
    })
  })

  it('서버 문장과 다른 금액·화면 분석이 기록과 다름(shown=null)·대안 없음이면 숫자 대신 날짜·문장만', () => {
    const differs = briefHead(LINES, revision, '2026-11-04', curve(5_000_000), null)
    expect(differs.deadline.line).toBe('11월 11일(수)까지')
    expect(differs.advice).toEqual({ label: '권고', value: null, line: LINES.lines[2]!.text, tone: 'neutral' })
    expect(briefHead(LINES, revision, '2026-11-04', null, null).deadline.line).toBe('11월 11일(수)까지')
    // 절감액이 서버 문장과 다르면 싣지 않음
    const other = { name: '다른 대안', total: 1_000_000, saving: 42_340_000 }
    expect(briefHead(LINES, revision, '2026-11-04', null, other).advice.value).toBeNull()
  })

  it("다음 날 대표값이 0이고 최대만 있으면 '최대 +n'('+최대 n'이 아님)", () => {
    const upTo = {
      lines: [{ kind: 'loss' as const, template_id: 'loss.by_date', text: '11월 11일(수)까지 확정 시 비용 그대로 — 다음 날부터 최대 35만원 증가' }],
    }
    const onlyHigh = {
      timing: {
        curve: [
          { confirm_on: '2026-11-11', additional_loss: { value: 0, low: 0, high: 0 } },
          { confirm_on: '2026-11-12', additional_loss: { value: 0, low: 0, high: 350_000 } },
        ],
      },
    } as unknown as Pick<AnalysisResult, 'timing'>
    expect(briefHead(upTo, revision, '2026-11-04', onlyHigh, null).deadline.line).toBe('11월 11일(수)까지 · 다음 날부터 최대 +35만원')
    expect(briefHead(upTo, revision, '2026-11-11', onlyHigh, null).deadline.line).toBe('내일부터 최대 +35만원')
  })

  it('결정 기한: D-3 이하 위험 색 · 오늘 · 지남 · 기간 안 없음(업무상 오늘 기준)', () => {
    const at = (today: string) => briefHead(LINES, revision, today, curve(18_670_000), null).deadline
    expect(at('2026-11-08')).toMatchObject({ value: 'D-3', tone: 'danger' })
    expect(at('2026-11-11')).toMatchObject({ value: '오늘', line: '내일부터 +1,867만원', tone: 'danger' })
    expect(at('2026-11-13')).toMatchObject({ value: '기한 지남', line: '11월 11일(수) 지남', tone: 'danger' })
    const none = { ...revision, deadline: { kind: 'none_in_horizon' as const, last_day: '2026-12-19' } }
    expect(briefHead(LINES, none, '2026-11-04', null, null).deadline).toMatchObject({
      value: '기간 안 없음',
      line: '12월 19일(토)까지 추가손실 없음',
      tone: 'success',
    })
  })

  it('바뀌는 것: 제목 · 영향 n곳(서버 문장과 같을 때만) · 블록 코드(ID 순, 3개 + 나머지 수)', () => {
    const impacts = (blocks: string[], extra = 0) =>
      ({
        impacts: [
          ...blocks.map((id) => ({ entity_type: 'block', entity_id: id })),
          ...Array.from({ length: extra }, (_, i) => ({ entity_type: 'part', entity_id: `P-${i}` })),
        ],
      }) as unknown as Pick<AnalysisResult, 'impacts'>
    const line = LINES.lines[0]!.text
    expect(changeHead('제목', impacts(['S-001:L31C', 'S-001:B31P'], 18), line)).toEqual({
      title: '제목',
      impacts: 20,
      blocks: ['B31P', 'L31C'],
      moreBlocks: 0,
    })
    expect(changeHead('제목', impacts(['S:A', 'S:B', 'S:C', 'S:D']), line)).toMatchObject({
      impacts: null,
      blocks: ['A', 'B', 'C'],
      moreBlocks: 1,
    })
    expect(changeHead('제목', null, line)).toEqual({ title: '제목', impacts: null, blocks: [], moreBlocks: 0 })
  })

  it('확인할 것 제목: 첫 조각 · 사전 점검 머리 빼고 — · 괄호 속 세부 뺌(글자를 새로 만들지 않음)', () => {
    expect(checkTitle({ text: '새 자재 리드타임 대표값으로 계산 — 협력사 납기 확인' })).toBe(
      '새 자재 리드타임 대표값으로 계산 — 협력사 납기 확인',
    )
    expect(
      checkTitle({
        text: '사전 점검 현장 통보 필수: B31P 블록에서 이미 한 공정(소조립·판넬조립·대조립 완료, 선행의장 진행 중)을 맡은 직영·해송 작업반에 변경 내용 통보 필요 · 같은 유형 합성 NCR 3건(합성 묶음(시연))',
      }),
    ).toBe('현장 통보 필수 — B31P 블록에서 이미 한 공정을 맡은 직영·해송 작업반에 변경 내용 통보 필요')
    expect(checkTitle({ text: '발주 2건(PO-1, PO-2) 보류 포함 계산 — 협력사 확인' })).toBe('발주 2건 보류 포함 계산 — 협력사 확인')
  })
})