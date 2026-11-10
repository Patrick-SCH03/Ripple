// @vitest-environment jsdom
// 성과 탭(DOM): '지표 계산 방법'의 결정 정의 = 집계(마지막 단계 승인 · 어느 단계든 반려·보류),
// 좁은 폭에서 표 머리글이 잘려 보이지 않게 — 머리글은 줄을 바꾸지 않고, 표가 칸보다 넓으면 가로 스크롤 안내 한 줄과
// 키보드로 밀 수 있는 스크롤 영역.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import type { ManageOverview } from '@/api/client'
import { PerformancePanel } from './PerformancePanel'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const mounted: Root[] = []
const restore: (() => void)[] = []
afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  for (const undo of restore.splice(0)) undo()
  document.body.innerHTML = ''
})

const actor = { login_id: 'kim', name: '김설계', role: 'member' as const }

const DATA = {
  generated_at: '2026-10-28T09:40:00+00:00',
  today: '2026-10-28',
  inbox: [],
  proxy: [],
  blocks: [],
  states: [],
  kpis: {},
  performance: {
    approved: 8,
    rejected: 2,
    held: 2,
    decided: 12,
    settled: 1,
    reject_rate: 2 / 12,
    on_time: 6,
    on_time_rate: 0.75,
    protected: 0,
    protected_cases: 0,
    cheaper_cases: 0,
    cheaper_total: 0,
    steps: [],
    people: [{ actor, recorded: 6, requested: 5, rejected: 1, open: 3 }],
  },
  outcomes: {
    count: 1,
    median_abs_error: 0.1,
    in_range_rate: 1,
    rows: [
      {
        ecn_id: 'ECN-D-0099',
        title: '판 두께 변경',
        revision: 1,
        entered_at: '2026-10-27T01:00:00+00:00',
        predicted: { value: 10_000_000, low: 8_000_000, high: 12_000_000 },
        actual_krw: 11_000_000,
        error_rate: 0.1,
        in_range: true,
        predicted_delay_days: 3,
        actual_delay_days: 4,
      },
    ],
  },
} as unknown as ManageOverview

/** 레이아웃이 없는 jsdom에서 표가 칸보다 넓은(375 폭) 것처럼 보이게 한다. */
function pretendWide(scroll: number, client: number) {
  const proto = HTMLElement.prototype
  const before = {
    scroll: Object.getOwnPropertyDescriptor(proto, 'scrollWidth'),
    client: Object.getOwnPropertyDescriptor(proto, 'clientWidth'),
  }
  Object.defineProperty(proto, 'scrollWidth', { configurable: true, get: () => scroll })
  Object.defineProperty(proto, 'clientWidth', { configurable: true, get: () => client })
  restore.push(() => {
    if (before.scroll) Object.defineProperty(proto, 'scrollWidth', before.scroll)
    if (before.client) Object.defineProperty(proto, 'clientWidth', before.client)
  })
}

async function mount() {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  mounted.push(root)
  await act(async () => root.render(<PerformancePanel data={DATA} days={null} />))
  return container
}

describe('성과 — 지표 계산 방법', () => {
  it("결정 정의가 집계와 같음: '마지막 단계 승인 · 어느 단계든 반려·보류'", async () => {
    const container = await mount()
    const rules = container.querySelector('details')!.textContent ?? ''
    expect(rules).toContain('마지막 단계 승인 · 어느 단계든 반려·보류')
    expect(rules).not.toContain('마지막 단계의 승인·반려·보류')
  })
})

describe('성과 — 좁은 폭의 표', () => {
  it('머리글은 줄을 바꾸지 않음', async () => {
    const container = await mount()
    const heads = Array.from(container.querySelectorAll('th'))
    expect(heads.length).toBeGreaterThanOrEqual(10)
    for (const head of heads) expect(head.className).toContain('whitespace-nowrap')
  })

  it('표가 칸보다 넓으면 표마다 가로 스크롤 안내 한 줄 + 키보드로 밀 수 있는 영역', async () => {
    pretendWide(576, 343)
    const container = await mount()
    const hints = container.querySelectorAll('[data-testid="scroll-hint"]')
    expect(hints).toHaveLength(2)
    expect(hints[0].textContent).toContain('옆으로 스크롤')
    const regions = Array.from(container.querySelectorAll<HTMLElement>('[data-testid="wide-table"]'))
    expect(regions.map((r) => r.getAttribute('aria-label'))).toEqual(['담당자별 업무량 표', '예측 대비 실적 표'])
    for (const region of regions) expect(region.tabIndex).toBe(0)
  })

  it('표가 칸에 들어가면 안내 없음', async () => {
    pretendWide(343, 343)
    const container = await mount()
    expect(container.querySelectorAll('[data-testid="scroll-hint"]')).toHaveLength(0)
    expect(container.querySelectorAll('[data-testid="wide-table"]')).toHaveLength(2)
  })
})
