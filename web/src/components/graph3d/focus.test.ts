import { describe, expect, it } from 'vitest'
import type { ImpactView } from '@/api/client'
import { focusNotice, focusOf, selectedBlock } from './focus'

type Node = { id: string; type: string; label?: string; attrs?: Record<string, string | number | boolean | null> }

function view(nodes: Node[], edges: [string, string, string][]): ImpactView {
  return {
    analysis_id: 'A-1',
    graph: {
      nodes: nodes.map((n) => ({ virtual: false, attrs: {}, label: n.id, ...n })),
      edges: edges.map(([source, relation, target]) => ({ source, relation, target, virtual: false })),
      snapshot_id: 'G-1',
      truncated: false,
    },
    impacts: [],
  } as unknown as ImpactView
}

// ECN-D-0119(B31P 판 두께) 결과 지도와 같은 연결 + 두 블록에 걸친 발주·구역 출구·배치 밖 블록
const sample = view(
  [
    { id: 'S-001:B31P', type: 'block' },
    { id: 'S-001:L31C', type: 'block' },
    { id: 'S-001:B31P-PL-002', type: 'part', attrs: { block_id: 'S-001:B31P', role: 'target' } },
    { id: 'S-001:B31P-BR-004', type: 'part', attrs: { block_id: 'S-001:B31P' } },
    { id: 'S-001:L31C-PL-007', type: 'part', attrs: { block_id: 'S-001:L31C' } },
    { id: 'S-001:B31S-PL-004', type: 'part', attrs: { block_id: 'S-001:B31S' } },
    { id: 'DWG-B31P-H01@A', type: 'drawing' },
    { id: 'DWG-L31C-H01@A', type: 'drawing' },
    { id: 'PO-0037#1', type: 'po_line' },
    { id: 'PO-0099#1', type: 'po_line' },
    { id: 'PO-0099', type: 'po' },
    { id: 'S-001:B31P:sub_assembly', type: 'activity' },
    { id: 'S-001:B31P:erection', type: 'activity' },
    { id: 'S-001:ZCT:exit', type: 'activity' },
    { id: 'S-001:ZCT', type: 'zone' },
    { id: 'STK-01', type: 'stock', attrs: { reserved_block_id: 'S-001:B31S' } },
    { id: 'S-001:X99P', type: 'block' },
    { id: 'S-001:X99P-PL-001', type: 'part', attrs: { block_id: 'S-001:X99P' } },
    { id: 'DWG-X99P@A', type: 'drawing' },
    { id: 'DWG-LONE@A', type: 'drawing' },
  ],
  [
    ['S-001:B31P-PL-002', 'drawn_in', 'DWG-B31P-H01@A'],
    ['S-001:B31P-PL-002', 'supplied_by', 'PO-0037#1'],
    ['PO-0037#1', 'consumed_by', 'S-001:B31P:sub_assembly'],
    ['S-001:L31C-PL-007', 'drawn_in', 'DWG-L31C-H01@A'],
    ['S-001:L31C-PL-007', 'supplied_by', 'PO-0099#1'],
    ['S-001:B31S-PL-004', 'supplied_by', 'PO-0099#1'],
    ['PO-0099', 'has_line', 'PO-0099#1'],
    ['S-001:B31P:erection', 'precedes', 'S-001:ZCT:exit'],
    ['S-001:ZCT', 'contains', 'S-001:B31P'],
    ['S-001:ZCT', 'contains', 'S-001:L31C'],
    ['S-001:X99P-PL-001', 'drawn_in', 'DWG-X99P@A'],
  ],
)

describe('엔터티 → 3D 이동 대상', () => {
  it('블록·부재·블록 공정은 2D와 같은 규칙으로 그 블록', () => {
    expect(focusOf(sample, 'S-001:B31P')).toEqual({ kind: 'block', code: 'B31P' })
    expect(focusOf(sample, 'S-001:B31P-BR-004')).toEqual({ kind: 'block', code: 'B31P' })
    expect(focusOf(sample, 'S-001:B31P:erection')).toEqual({ kind: 'block', code: 'B31P' })
  })

  it('도면·발주 품목은 연결된 부재·공정의 블록이 하나면 그 블록', () => {
    expect(focusOf(sample, 'DWG-B31P-H01@A')).toEqual({ kind: 'block', code: 'B31P' })
    expect(focusOf(sample, 'DWG-L31C-H01@A')).toEqual({ kind: 'block', code: 'L31C' })
    expect(focusOf(sample, 'PO-0037#1')).toEqual({ kind: 'block', code: 'B31P' })
  })

  it('재고는 예약 블록', () => {
    expect(focusOf(sample, 'STK-01')).toEqual({ kind: 'block', code: 'B31S' })
  })

  it('여러 블록에 걸친 발주 품목·발주(2단계)는 카메라 이동 없이 관련 블록 강조', () => {
    expect(focusOf(sample, 'PO-0099#1')).toEqual({ kind: 'blocks', codes: ['B31S', 'L31C'] })
    expect(focusOf(sample, 'PO-0099')).toEqual({ kind: 'blocks', codes: ['B31S', 'L31C'] })
  })

  it('구역·구역 출구는 블록 하나로 정하지 않는다(이웃 블록이 하나여도 강조만)', () => {
    expect(focusOf(sample, 'S-001:ZCT')).toEqual({ kind: 'blocks', codes: ['B31P', 'L31C'] })
    expect(focusOf(sample, 'S-001:ZCT:exit')).toEqual({ kind: 'blocks', codes: ['B31P'] })
  })

  it('배치 표 밖 블록·연결 없는 엔터티·지도에 없는 ID는 배치 위치 없음', () => {
    expect(focusOf(sample, 'S-001:X99P')).toEqual({ kind: 'none' })
    expect(focusOf(sample, 'DWG-X99P@A')).toEqual({ kind: 'none' })
    expect(focusOf(sample, 'DWG-LONE@A')).toEqual({ kind: 'none' })
    expect(focusOf(sample, 'NOPE')).toEqual({ kind: 'none' })
    expect(focusOf(sample, null)).toEqual({ kind: 'none' })
    // 지도에 노드가 없어도 배치 표의 블록 ID면 그 블록
    expect(focusOf(sample, 'S-001:F11C')).toEqual({ kind: 'block', code: 'F11C' })
  })

  it('외곽선·요약에 쓰는 고른 블록은 블록 하나로 정해질 때만', () => {
    expect(selectedBlock(sample, 'DWG-B31P-H01@A')).toBe('B31P')
    expect(selectedBlock(sample, 'PO-0099#1')).toBeNull()
    expect(selectedBlock(sample, 'S-001:ZCT:exit')).toBeNull()
  })

  it('안내는 명사형, 블록 하나면 안내 없음', () => {
    expect(focusNotice({ kind: 'none' })).toBe('배치 위치 없음')
    expect(focusNotice({ kind: 'blocks', codes: ['B31S', 'L31C'] })).toBe('배치 위치 여러 블록 · B31S · L31C')
    expect(focusNotice({ kind: 'block', code: 'B31P' })).toBeNull()
  })
})
