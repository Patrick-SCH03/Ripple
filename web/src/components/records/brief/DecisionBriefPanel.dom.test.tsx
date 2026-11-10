// @vitest-environment jsdom
// 결정 도우미 자리(DOM): 과거 사례를 만드는 중이면 잠시 뒤 다시 불러 사례를 채우고, 다른 기록의 도우미는 그리지 않는다.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type AnalysisResult, type DecisionBrief, type EcnDetail, type Me, type PastCases } from '@/api/client'
import { DecisionBriefPanel } from './DecisionBriefPanel'
import { CASES_RETRY_MS } from './useDecisionBrief'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const lead = { permissions: ['view', 'approve'] } as unknown as Me
const detail = {
  status: { ecn_id: 'ECN-D-0043', state: 'in_review', review: { seq: 3, revision: 1 } },
  revisions: [
    {
      revision: 1,
      record_id: 'R-00000000000000a1',
      title: 'E21C 배관 경로 변경(이번 건)',
      total: { value: 43_340_000, low: 12_360_000, high: 102_500_000 },
      deadline: { kind: 'by_date', last_day: '2026-11-11' },
    },
  ],
} as unknown as EcnDetail
/** 화면의 분석(같은 개정이 아니면 숫자를 읽지 않음 — shownMatches=false). */
const shown = { request: { change: { op: 'pipe_reroute' } }, alternatives: [], impacts: [] } as unknown as AnalysisResult
const TODAY = '2026-11-04'

function brief(cases: Partial<PastCases>, recordId = 'R-00000000000000a1'): DecisionBrief {
  return {
    ecn_id: 'ECN-D-0043',
    revision: 1,
    record_id: recordId,
    data_mode: 'synthetic',
    lines: [
      { kind: 'change', text: '바뀌는 문장', template_id: 'change.summary' },
      { kind: 'loss', text: '안 정하면 문장', template_id: 'loss.by_date' },
      { kind: 'advice', text: '권고 문장', template_id: 'advice.hold' },
    ],
    checks: [],
    cases: { items: [], summary: null, library_size: 0, synthetic: true, status: 'ready', ...cases },
    picked_by: 'rule',
  }
}

const READY_CASE = {
  case_id: 'ECN-D-0090',
  title: 'E21C 평형수 배관 경로 변경',
  same: ['같은 블록 E21C'],
  decision: 'approve' as const,
  chosen: '요청대로 승인',
  predicted: { value: 3_590_000, low: 3_000_000, high: 4_000_000 },
  actual_krw: 3_910_000,
  predicted_delay_days: 0,
  actual_delay_days: 0,
  days_before_deadline: 4,
  note: '',
  synthetic: true,
}

const mounted: Root[] = []
afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  document.body.innerHTML = ''
  vi.restoreAllMocks()
  vi.useRealTimers()
})

async function mount() {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  mounted.push(root)
  await act(async () => root.render(<DecisionBriefPanel me={lead} detail={detail} result={shown} shownMatches={false} today={TODAY} />))
  return container
}

describe('결정 도우미 자리', () => {
  it('과거 사례를 만드는 중이면 한 줄을 보이고, 잠시 뒤 다시 불러 사례를 채운다(세 줄은 그대로)', async () => {
    vi.useFakeTimers()
    const calls = vi
      .spyOn(api, 'brief')
      .mockResolvedValueOnce(brief({ status: 'building' }))
      .mockResolvedValueOnce(brief({ items: [READY_CASE], summary: '비슷한 1건은 실적이 예측보다 컸어요' }))
    const container = await mount()
    expect(container.textContent).toContain('과거 사례 준비 중')
    // 맨 위 큰 숫자 카드(개정 요약) · 세 줄 문장은 펼침 안
    expect(container.querySelector('[data-brief-card="total"]')?.textContent).toContain('4,334만원')
    expect(container.querySelector('[data-brief-card="deadline"]')?.textContent).toContain('D-7')
    expect(container.textContent).not.toContain('바뀌는 문장')
    await act(async () => container.querySelector<HTMLButtonElement>('[data-testid="decision-brief-lines-toggle"]')!.click())
    expect(container.textContent).toContain('바뀌는 문장')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CASES_RETRY_MS)
    })
    expect(calls).toHaveBeenCalledTimes(2)
    expect(container.textContent).not.toContain('과거 사례 준비 중')
    expect(container.textContent).toContain('비슷한 1건은 실적이 예측보다 컸어요')
    expect(container.textContent).not.toContain('E21C 평형수 배관 경로 변경') // 접어서 시작
    const toggle = container.querySelector<HTMLButtonElement>('[data-testid="decision-brief-cases-toggle"]')!
    expect(toggle.textContent).toContain('사례 1건 보기')
    await act(async () => toggle.click())
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('E21C 평형수 배관 경로 변경')
    expect(toggle.textContent).toContain('사례 접기')
    expect(container.textContent).toContain('합성 과거 사례')
  })

  it('한국 시간 자정이 지나 다시 그리면 다시 부른다(D-n이 하루 줄어서), 같은 날 다시 그리면 그대로', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-26T14:50:00Z')) // KST 10-26 23:50
    const calls = vi.spyOn(api, 'brief').mockResolvedValue(brief({}))
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    mounted.push(root)
    await act(async () => root.render(<DecisionBriefPanel me={lead} detail={detail} result={shown} shownMatches={false} today={TODAY} />))
    await act(async () => root.render(<DecisionBriefPanel me={lead} detail={{ ...detail }} result={shown} shownMatches={false} today={TODAY} />))
    expect(calls).toHaveBeenCalledTimes(1)
    vi.setSystemTime(new Date('2026-10-26T15:05:00Z')) // KST 10-27 00:05
    await act(async () => root.render(<DecisionBriefPanel me={lead} detail={{ ...detail }} result={shown} shownMatches={false} today={TODAY} />))
    expect(calls).toHaveBeenCalledTimes(2)
  })

  it('사례가 준비돼 있으면 다시 부르지 않고, 다른 기록의 도우미(새 개정 전 응답)는 그리지 않는다', async () => {
    vi.useFakeTimers()
    const calls = vi.spyOn(api, 'brief').mockResolvedValue(brief({}, 'R-00000000000000ff'))
    const container = await mount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CASES_RETRY_MS * 2)
    })
    expect(calls).toHaveBeenCalledTimes(1)
    expect(container.querySelector('[data-testid="decision-brief"]')).toBeNull()
  })
})
