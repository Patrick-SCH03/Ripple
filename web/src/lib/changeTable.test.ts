import { describe, expect, it } from 'vitest'
import type { AnalysisResult } from '@/api/client'
import { CHANGE_ROWS_SHOWN, changeTable, drawingOf, drawingText, shortCode } from './changeTable'

type Input = Pick<AnalysisResult, 'request' | 'graph'>
type Op = AnalysisResult['request']['change']['ops'][number]

function input(ops: Op[], nodes: Input['graph']['nodes'] = [], edges: Input['graph']['edges'] = []): Input {
  return {
    request: { change: { ecn_id: 'ECN-1', title: 't', ship_ids: ['S-001'], ops } } as unknown as Input['request'],
    graph: { nodes, edges } as Input['graph'],
  }
}

const part = (id: string, label: string, spec = 'PL-AH36-17.0') => ({
  id,
  type: 'part' as const,
  label,
  attrs: { spec_id: spec },
  virtual: false,
})
const dwg = (id: string) => ({ id, type: 'drawing' as const, label: id, attrs: {}, virtual: false })
const drawn = (source: string, target: string) => ({ source, target, relation: 'drawn_in' as const, virtual: false })

describe('changeTable', () => {
  it('두께 변경: 대상 부재마다 한 행, 이름·번호·전후·도면은 결과 그대로', () => {
    const view = changeTable(
      input(
        [{ op: 'thickness', part_ids: ['S-001:B31P-PL-002', 'S-001:B31P-PL-005'], from_mm: 17, to_mm: 20 }],
        [part('S-001:B31P-PL-002', '이중저 판 2'), part('S-001:B31P-PL-005', '이중저 판 5'), dwg('DWG-B31P-H01@A')],
        [drawn('S-001:B31P-PL-002', 'DWG-B31P-H01@A')],
      ),
    )
    expect(view.rows).toHaveLength(2)
    expect(view.rows[0]).toMatchObject({
      part: '이중저 판 2',
      code: 'B31P-PL-002',
      item: '두께',
      before: '17.0mm',
      after: '20.0mm',
      drawing: { no: 'DWG-B31P-H01', revision: 'A', more: 0 },
      selectable: true,
    })
    // 도면 연결이 없는 부재는 도면을 지어내지 않는다
    expect(view.rows[1].drawing).toBeNull()
    expect(view.hasDrawing).toBe(true)
  })

  it('그래프에 없는 부재: ID 그대로, 누를 수 없음, 도면 칸 없음', () => {
    const view = changeTable(input([{ op: 'grade', part_ids: ['S-001:X-1'], from_grade: 'AH32', to_grade: 'AH36' }]))
    expect(view.rows[0]).toMatchObject({ part: 'S-001:X-1', code: 'X-1', item: '강종', before: 'AH32', after: 'AH36' })
    expect(view.rows[0].selectable).toBe(false)
    expect(view.hasDrawing).toBe(false)
  })

  it('drawn_in이라도 대상이 도면 노드가 아니면 도면으로 쓰지 않음', () => {
    const view = changeTable(
      input(
        [{ op: 'remove_part', part_ids: ['S-001:A'] }],
        [part('S-001:A', '판 A', 'PL-1'), part('S-001:B', '판 B')],
        [drawn('S-001:A', 'S-001:B')],
      ),
    )
    expect(view.rows[0]).toMatchObject({ item: '부재 삭제', before: 'PL-1', after: '삭제', drawing: null })
  })

  it('여러 도면이면 첫 도면 + 외 n', () => {
    const view = changeTable(
      input(
        [{ op: 'dimension', part_ids: ['S-001:A'], field: 'length_mm', from_value: 12000, to_value: 12500 }],
        [part('S-001:A', '판 A'), dwg('D1@B'), dwg('D2@A')],
        [drawn('S-001:A', 'D1@B'), drawn('S-001:A', 'D2@A'), drawn('S-001:A', 'D2@A')],
      ),
    )
    const row = view.rows[0]
    expect(row).toMatchObject({ item: '길이', before: '12,000mm', after: '12,500mm' })
    expect(row.drawing && drawingText(row.drawing)).toBe('D1 · 개정 B 외 1')
  })

  it('행 순서 = 연산 순 · 대상 순, 키는 모두 다름', () => {
    const ids = Array.from({ length: CHANGE_ROWS_SHOWN + 2 }, (_, i) => `S-001:P-${i}`)
    const view = changeTable(
      input([
        { op: 'thickness', part_ids: ids, from_mm: 15.5, to_mm: 18.5 },
        { op: 'grade', part_ids: [ids[0]], from_grade: 'A', to_grade: 'AH36' },
        { op: 'add_part', block_id: 'S-001:B31P', kind: 'bracket', spec_id: 'BR-1', qty: 4 },
        { op: 'add_penetration', plate_part_id: ids[1], pipe_part_id: 'S-001:PP-1', diameter_mm: 150 },
        { op: 'reroute_pipe', removed_part_ids: ['S-001:SP-1'], added_spool_spec_ids: ['SP-NEW'], crosses_part_ids: [] },
      ] as Op[]),
    )
    expect(view.rows.map((r) => r.item)).toEqual([
      ...ids.map(() => '두께'),
      '강종',
      '부재 추가',
      '관통부',
      '배관 스풀',
      '배관 스풀',
    ])
    expect(new Set(view.rows.map((r) => r.key)).size).toBe(view.rows.length)
    expect(view.rows[0]).toMatchObject({ before: '15.5mm', after: '18.5mm' })
    const add = view.rows.find((r) => r.item === '부재 추가')
    expect(add).toMatchObject({ part: '블록 B31P', before: '—', after: 'BR-1 × 4' })
    expect(view.rows.find((r) => r.item === '관통부')?.after).toBe('지름 150mm')
  })

  it('연결 추적의 부재별 도면을 먼저 쓴다(그래프에 도면 연결이 없어도)', () => {
    const base = input(
      [{ op: 'thickness', part_ids: ['S-001:A', 'S-001:B'], from_mm: 15.5, to_mm: 18.5 }],
      [part('S-001:A', '판 A'), dwg('DWG-1@A')],
      [drawn('S-001:A', 'DWG-1@A')],
    )
    const link = (id: string) => ({ kind: 'drawing' as const, entity_id: id, label: id, status: null, affected: true })
    const view = changeTable({
      ...base,
      trace: [
        { part_id: 'S-001:A', label: '판 A', drawing: link('DWG-1@A'), po_lines: [], activities: [], gaps: [], new: false, removed: false },
        { part_id: 'S-001:B', label: '판 B', drawing: link('DWG-1@A'), po_lines: [], activities: [], gaps: [], new: false, removed: false },
      ],
    })
    // 같은 도면이 추적·그래프에 모두 있어도 한 번만, 그래프에 없는 부재 B는 추적의 이름과 도면
    expect(view.rows[0].drawing).toEqual({ no: 'DWG-1', revision: 'A', more: 0 })
    expect(view.rows[1]).toMatchObject({ part: '판 B', drawing: { no: 'DWG-1', revision: 'A', more: 0 }, selectable: false })
  })

  it('연산이 없으면 빈 표', () => {
    expect(changeTable(input([])).rows).toEqual([])
  })
})

describe('도면·번호 표기', () => {
  it('drawingOf: @ 뒤가 개정, 없으면 번호만', () => {
    expect(drawingOf('DWG-B31P-H01@A')).toEqual({ no: 'DWG-B31P-H01', revision: 'A' })
    expect(drawingOf('DWG-X')).toEqual({ no: 'DWG-X', revision: null })
  })
  it('shortCode: 호선 앞머리만 뺀다', () => {
    expect(shortCode('S-001:B31P-PL-002')).toBe('B31P-PL-002')
    expect(shortCode('B31P')).toBe('B31P')
  })
})
