// 상세 판단 요약의 '변경 내용' 전 → 후 대조표(DESIGN.md 6절): 설계·생산 담당자가 무엇이 어떻게 바뀌는지 한눈에.
// 행은 요청 연산(request.change.ops)의 대상마다 하나 — 값은 연산 필드 그대로, 부재 이름·도면(번호·개정)은 연결 추적(trace)의
// 부재별 도면 → 분석 그래프의 노드·'drawn_in' 연결 순으로만 가져온다(결과에 없는 도면은 만들지 않음). 순수 함수 — changeTable.test.ts가 성질을 검사한다.
import type { AnalysisResult } from '@/api/client'

type ChangeOp = AnalysisResult['request']['change']['ops'][number]
type GraphPart = Pick<AnalysisResult, 'request' | 'graph'> & { trace?: AnalysisResult['trace'] }

/** 처음 보이는 행 수(넘으면 '전체 n행' 펼침). */
export const CHANGE_ROWS_SHOWN = 5

export interface ChangeRow {
  key: string
  /** 대상 엔터티 ID(부재·블록). 영향 지도에 카드가 있으면 selectable. */
  entityId: string | null
  /** 부재 이름(그래프 노드 이름, 없으면 ID). */
  part: string
  /** 부재 번호(호선 앞머리를 뺀 ID, 이름과 같으면 null). */
  code: string | null
  item: string
  before: string
  after: string
  /** 도면 번호·개정(그래프의 drawn_in 연결, 없으면 null). */
  drawing: { no: string; revision: string | null; more: number } | null
  /** 영향 지도에 이 엔터티 카드가 있는가(누르면 그 카드 선택). */
  selectable: boolean
}

export interface ChangeTableView {
  rows: ChangeRow[]
  /** 도면 칸을 낼까(한 행이라도 도면이 있을 때만 — 빈 칸만 있는 열을 두지 않음). */
  hasDrawing: boolean
}

const DIMENSION_NAMES: Record<string, string> = {
  length_mm: '길이',
  width_mm: '폭',
  height_mm: '높이',
  diameter_mm: '지름',
}

const NONE = '—'

const MM = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 1 })

/** 판 두께는 규격 표기(17.0)처럼 소수 한 자리. */
function thicknessText(mm: number): string {
  return `${mm.toFixed(1)}mm`
}

function mmText(mm: number): string {
  return `${MM.format(mm)}mm`
}

/** 'S-001:B31P-PL-002' → 'B31P-PL-002'(호선 앞머리 제거). */
export function shortCode(id: string): string {
  return id.includes(':') ? id.slice(id.indexOf(':') + 1) : id
}

/** 'DWG-B31P-H01@A' → 번호·개정. 개정 표기가 없으면 번호만. */
export function drawingOf(id: string): { no: string; revision: string | null } {
  const at = id.lastIndexOf('@')
  return at > 0 ? { no: id.slice(0, at), revision: id.slice(at + 1) || null } : { no: id, revision: null }
}

interface Lookup {
  name: (id: string) => string
  has: (id: string) => boolean
  spec: (id: string) => string | null
  drawings: (id: string) => string[]
}

function lookup(result: GraphPart): Lookup {
  const nodes = new Map(result.graph.nodes.map((node) => [node.id, node]))
  const drawn = new Map<string, string[]>()
  const labels = new Map<string, string>()
  // 연결 추적은 대상 부재마다 도면을 싣는다(그래프는 영향 경로 위 연결만 남겨 도면 연결이 빠질 수 있음)
  for (const chain of result.trace ?? []) {
    labels.set(chain.part_id, chain.label)
    if (chain.drawing) drawn.set(chain.part_id, [chain.drawing.entity_id])
  }
  for (const edge of result.graph.edges) {
    if (edge.relation !== 'drawn_in' || nodes.get(edge.target)?.type !== 'drawing') continue
    const list = drawn.get(edge.source) ?? []
    if (!list.includes(edge.target)) list.push(edge.target)
    drawn.set(edge.source, list)
  }
  return {
    name: (id) => nodes.get(id)?.label ?? labels.get(id) ?? id,
    has: (id) => nodes.has(id),
    spec: (id) => {
      const value = nodes.get(id)?.attrs?.spec_id
      return typeof value === 'string' && value ? value : null
    },
    drawings: (id) => drawn.get(id) ?? [],
  }
}

function row(look: Lookup, key: string, entityId: string | null, item: string, before: string, after: string, label?: string): ChangeRow {
  const drawings = entityId ? look.drawings(entityId) : []
  const first = drawings[0]
  const part = label ?? (entityId ? look.name(entityId) : NONE)
  const code = entityId ? shortCode(entityId) : null
  return {
    key,
    entityId,
    part,
    code: code && code !== part ? code : null,
    item,
    before,
    after,
    drawing: first ? { ...drawingOf(first), more: drawings.length - 1 } : null,
    selectable: entityId !== null && look.has(entityId),
  }
}

function opRows(op: ChangeOp, index: number, look: Lookup): ChangeRow[] {
  const key = (suffix: string) => `${index}:${suffix}`
  switch (op.op) {
    case 'thickness':
      return op.part_ids.map((id) => row(look, key(id), id, '두께', thicknessText(op.from_mm), thicknessText(op.to_mm)))
    case 'grade':
      return op.part_ids.map((id) => row(look, key(id), id, '강종', op.from_grade, op.to_grade))
    case 'dimension': {
      const item = DIMENSION_NAMES[op.field] ?? op.field
      return op.part_ids.map((id) => row(look, key(id), id, item, mmText(op.from_value), mmText(op.to_value)))
    }
    case 'equipment_spec':
      return op.part_ids.map((id) => row(look, key(id), id, '장비 사양', op.from_spec_id, op.to_spec_id))
    case 'remove_part':
      return op.part_ids.map((id) => row(look, key(id), id, '부재 삭제', look.spec(id) ?? NONE, '삭제'))
    case 'add_part': {
      const block = shortCode(op.block_id)
      return [row(look, key('add'), op.block_id, '부재 추가', NONE, `${op.spec_id} × ${MM.format(op.qty)}`, `블록 ${block}`)]
    }
    case 'add_penetration':
      return [row(look, key(op.plate_part_id), op.plate_part_id, '관통부', NONE, `지름 ${mmText(op.diameter_mm)}`)]
    case 'reroute_pipe':
      return [
        ...op.removed_part_ids.map((id) => row(look, key(`rm:${id}`), id, '배관 스풀', look.spec(id) ?? NONE, '제거')),
        ...op.added_spool_spec_ids.map((spec, i) => row(look, key(`add:${i}`), null, '배관 스풀', NONE, spec, '새 스풀')),
        ...op.crosses_part_ids.map((id) => row(look, key(`x:${id}`), id, '배관 관통', NONE, '관통 추가')),
      ]
    default:
      return []
  }
}

/** 요청 연산 → 대조표 행(연산 순, 연산 안은 대상 순). 연산이 없으면 빈 표. */
export function changeTable(result: GraphPart): ChangeTableView {
  const look = lookup(result)
  const rows = result.request.change.ops.flatMap((op, index) => opRows(op, index, look))
  return { rows, hasDrawing: rows.some((r) => r.drawing !== null) }
}

/** 도면 칸 글: 'DWG-B31P-H01 · 개정 A'(+ '외 n'). */
export function drawingText(drawing: NonNullable<ChangeRow['drawing']>): string {
  const rev = drawing.revision ? ` · 개정 ${drawing.revision}` : ''
  const more = drawing.more > 0 ? ` 외 ${drawing.more}` : ''
  return `${drawing.no}${rev}${more}`
}
