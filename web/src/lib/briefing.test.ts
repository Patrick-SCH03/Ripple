import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { briefingText } from './briefing'

const amount = (value: number, low = value, high = value) => ({ value, low, high })

function result(over: Record<string, unknown> = {}): AnalysisResult {
  const base = {
    request: { as_of: '2026-10-20', holds: [], change: { ecn_id: 'ECN-D-0038', title: '배관 경로 변경' } },
    verdict: { level: 'warn', reasons: ['블록 탑재 지연 가능', '발주된 자재 변경·취소 필요'] },
    total: amount(2984205, 664313, 7893318),
    cost_lines: [],
    schedule: {
      zone_exits: [
        {
          zone_id: 'S-001:ZER',
          zone_name: '기관실·펌프룸',
          exit_activity_id: 'x',
          base_date: '2026-11-01',
          new_date: '2026-11-04',
          delay_days: 3,
        },
      ],
      max_exit_delay_days: 3,
      delivery: { added_delay_days: 0 },
    },
    timing: { deadline: { kind: 'by_date', last_day: '2026-10-23' }, holds: [], reallocations: [], curve: [] },
  }
  return { ...base, ...over } as unknown as AnalysisResult
}

describe('메신저용 요약', () => {
  it('판정·이유 → 총비용(범위) → 마감일 D-n → 출구 지연 → 기준일, 0인 지연은 빼고', () => {
    expect(briefingText(result()).split('\n')).toEqual([
      '[설계변경] ECN-D-0038 배관 경로 변경',
      '판정: 경고 — 블록 탑재 지연 가능 · 발주된 자재 변경·취소 필요',
      '총변경비용: 298만원(66만~789만원)',
      '결정 기한: 10월 23일(금)(D-3)',
      '구역 출구 최대 지연: 3일',
      '(Ripple 분석 · 기준일 10월 20일(화))',
    ])
  })

  it('오늘 확정·기간 안 없음은 그 뜻을 문장으로', () => {
    const now = result({ timing: { ...result().timing, deadline: { kind: 'confirm_now', last_day: '2026-10-20' } } })
    expect(briefingText(now)).toContain('결정 기한: 오늘 확정 필요')
    const free = result({ timing: { ...result().timing, deadline: { kind: 'none_in_horizon', last_day: '2026-12-19' } } })
    expect(briefingText(free)).toContain('기간 안 없음(12월 19일(토)까지 추가손실 없음)')
  })

  it('할 일은 세 개까지, 나머지는 외 n건', () => {
    const holds = ['PO-1', 'PO-2', 'PO-3', 'PO-4'].map((po_id) => ({
      po_id,
      max_hold_days: 5,
      hold_until: '2026-10-25',
      deadline_after: { kind: 'by_date', last_day: '2026-10-28' },
      avoided: amount(1_000_000),
    }))
    // 보류 권고에는 결재 기간 꼬리 — 서버 결재 계획(approval_plan.holds)의 짧은 문구 그대로(이 권고는 결재 기간보다 짧다)
    const windows = holds.map((h) => ({ po_id: h.po_id, outlasts: false, text: '권고 5일은 결재 기간보다 짧음', short: '결재 기간보다 짧은 보류' }))
    const text = briefingText(result({ timing: { ...result().timing, holds }, approval_plan: { holds: windows } }))
    const tail = '(결재 기간보다 짧은 보류)'
    expect(text).toContain(`할 일: 발주 PO-1 보류 권고${tail} · 발주 PO-2 보류 권고${tail} · 발주 PO-3 보류 권고${tail} 외 1건`)
    // 결재 계획이 없으면(옛 응답) 꼬리 없이 — 화면이 짐작해 만들지 않는다
    expect(briefingText(result({ timing: { ...result().timing, holds } }))).toContain('할 일: 발주 PO-1 보류 권고 · ')
  })

  it('적용한 보류는 가정 계산이라고 적음', () => {
    const held = result({ request: { ...result().request, holds: [{ po_id: 'PO-0131', hold_days: 12 }] } })
    expect(briefingText(held)).toContain('할 일: 발주 PO-0131 12일 보류(가정 계산)')
  })

  it('변경 원인이 있으면 제목 다음 줄에, 없으면 줄 없음', () => {
    const base = result()
    const owner = result({ request: { ...base.request, change: { ...base.request.change, cause: 'owner_request' } } })
    expect(briefingText(owner).split('\n')[1]).toBe('변경 원인: 선주 요청')
    expect(briefingText(base)).not.toContain('변경 원인')
  })

  it('범위가 없으면 괄호 없이, 인도 지연이 있으면 지체상금과 함께 한 줄 더', () => {
    const text = briefingText(
      result({ total: amount(8500), schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: { added_delay_days: 12 } } }),
    )
    expect(text).toContain('총변경비용: 8,500원\n')
    expect(text).toContain('늘어난 인도 지연: 12일(유예 기간 안 · 지체상금 없음)')
    expect(text).not.toContain('구역 출구')
  })

  it('대표 지연이 0일이어도 자재가 늦게 오면 늦는 위험은 화면 카드처럼 적음', () => {
    const risky = result({
      schedule: { zone_exits: [], max_exit_delay_days: 0, delivery: null, risk: { max_exit_delay_days: 9, ratios: [] } },
    })
    expect(briefingText(risky)).toContain('구역 출구 최대 지연: 0일(자재가 늦게 오면 최대 9일)')
  })
})
