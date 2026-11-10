// 일정 탭 공정 흐름: 블록 공정 일곱(PE 포함) 순서 · 늘어난 일수 그대로 · 이정표(구역 출구 → 진수 → 시운전 → 인도).
import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { BLOCK_PROCESS_ORDER, processFlow, stepDays } from './processFlow'

function schedule(added: Record<string, number>, over: Record<string, unknown> = {}) {
  return {
    schedule: {
      added_days_by_activity: added,
      zone_exits: [
        { zone_id: 'S-001:ZCT', zone_name: '화물탱크 구역', exit_activity_id: 'S-001:ZCT:exit', base_date: '2026-11-01', new_date: '2026-11-04', delay_days: 3 },
      ],
      max_exit_delay_days: 3,
      delivery: { added_delay_days: 0 },
      ...over,
    },
  } as unknown as Pick<AnalysisResult, 'schedule'>
}

describe('공정 흐름', () => {
  it('블록마다 소조립 → 판넬조립 → 대조립 → 선행의장 → 선행도장 → PE → 탑재, 일수는 결과 그대로', () => {
    const flow = processFlow(
      schedule({
        'S-001:B31P:erection': 67,
        'S-001:B31P:pre_erection': 6,
        'S-001:B31P:pre_outfitting': 9,
        'S-001:L31C:assembly': 1,
        'S-001:ZCT:exit': 3,
      }),
    )
    expect(flow.blocks.map((b) => b.block)).toEqual(['B31P', 'L31C'])
    expect(flow.blocks[0].steps.map((s) => s.name)).toEqual(['소조립', '판넬조립', '대조립', '선행의장', '선행도장', 'PE', '탑재'])
    expect(flow.blocks[0].steps.map((s) => s.days)).toEqual([0, 0, 0, 9, 0, 6, 67])
    expect(BLOCK_PROCESS_ORDER.indexOf('pre_erection')).toBe(BLOCK_PROCESS_ORDER.indexOf('erection') - 1)
    expect(flow.others).toEqual([])
  })

  it('이정표: 가장 늦는 구역 출구와 인도(계산 못 했으면 null), 블록 공정 꼴이 아닌 공정은 따로', () => {
    const flow = processFlow(schedule({ 'ACT-17': 4, 'S-001:B31P:erection': 2 }, { delivery: null }))
    expect(flow.milestones).toEqual({ exit: { zone: '화물탱크 구역', days: 3 }, delivery: { days: null } })
    expect(flow.others).toEqual([{ id: 'ACT-17', days: 4 }])
    const quiet = processFlow(schedule({}, { zone_exits: [], max_exit_delay_days: 0 }))
    expect(quiet.milestones.exit).toEqual({ zone: null, days: 0 })
    expect([stepDays(9), stepDays(0), stepDays(null)]).toEqual(['+9일', '그대로', ''])
  })
})
