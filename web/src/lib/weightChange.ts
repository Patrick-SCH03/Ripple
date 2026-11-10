// 블록별 강재 중량 변화(계약 1.34.0, docs/engine.md(비용·일정) 12절)의 화면 표기: 중량 포맷 · 블록 줄 정렬 · 합계 · 안내.
// 숫자는 결과의 weight_change 필드 그대로이고(합계 = 블록 합은 계약이 검사), 여기서는 고르고 줄 세우고 글로 만들기만 한다.
// 무게중심은 좌표가 없어 계산하지 않는다 — 안내 한 줄(COG_NOTE)만.
import type { components } from '@/api/schema'

type Schemas = components['schemas']
export type WeightChangeData = Schemas['WeightChange']
export type BlockWeight = Schemas['BlockWeight']
export type WeightSource = Schemas['WeightSource']

/** 부재 중량 근거 이름(엑셀 ripple/ingest/out_labels.py WEIGHT_SOURCE와 같은 말 — 검사 tests/checks/weight.py). */
export const WEIGHT_SOURCE_NAMES: Record<WeightSource, string> = {
  qty_t: '규격 수량(t) — 자재비 차이와 같은 값',
  weight_kg: '부재 중량(kg ÷ 1000)',
  none: '중량 정보 없음',
}

/** 무게중심 안내(엑셀 COG_NOTE와 같은 글). */
export const COG_NOTE = '무게중심: 좌표 정보 필요(다음 단계)'

/** 중량 근거 한 줄(표 아래). */
export const WEIGHT_BASIS =
  '규격 단위 t 부재는 자재비 차이와 같은 수량(두께 변경 = 원래 × 새 두께 ÷ 원래 두께) · 그 밖은 지도 부재 중량이 있을 때만'

const MINUS = '−'

/**
 * 중량(t) 표기: 소수 둘째 자리('1.33t', DESIGN.md 8절). 0이 아닌데 둘째 자리에서 0이 되면 셋째 자리까지('0.004t') — 작은
 * 변화가 '0.00t'로 사라지지 않게. 음수는 '−'.
 */
export function formatTons(tons: number): string {
  const size = Math.abs(tons)
  const digits = size > 0 && size < 0.005 ? 3 : 2
  const text = size.toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return `${tons < 0 && Number(text.replace(/,/g, '')) !== 0 ? MINUS : ''}${text}t`
}

/** 차이 표기: 늘면 '+0.69t', 줄면 '−0.12t', 같으면 '0.00t'. */
export function formatDelta(tons: number): string {
  const text = formatTons(tons)
  return tons > 0 && !/^0\.0+t$/.test(text) ? `+${text}` : text
}

/** 블록 칸 이름: 블록 코드(호선 앞자리를 뗀 ID) + 이름. 블록을 모르면 이름('블록 모름')만. */
export function blockLabel(block: Pick<BlockWeight, 'block_id' | 'name'>): { code: string | null; name: string } {
  if (!block.block_id) return { code: null, name: block.name }
  const code = block.block_id.split(':').at(-1) ?? block.block_id
  return { code, name: block.name === code ? '' : block.name }
}

export interface WeightRow {
  key: string
  code: string | null
  name: string
  before: string
  after: string
  delta: string
  /** 중량을 센 부재 수. */
  parts: number
  /** 중량 정보 없는 부재 수(합계 제외). */
  missing: number
  /** 셀 수 있는 부재가 하나도 없는 블록(중량 칸을 '—'로). */
  unknown: boolean
}

export interface WeightView {
  rows: WeightRow[]
  total: { before: string; after: string; delta: string; parts: number; missing: number }
  /** 중량이 바뀌는 부재가 없음. */
  empty: boolean
  /** '중량 정보 없음 n개 · 합계 제외'(없으면 null). */
  missingNote: string | null
}

/**
 * 블록 줄: 차이의 크기 큰 순(같으면 블록 코드 순), 셀 수 있는 부재가 없는 블록은 끝. 합계는 결과 값 그대로.
 * 이 판 전 기록(필드 없음)이면 null — 화면은 줄을 그리지 않거나 '이 판 전 기록'으로 안내한다.
 */
export function weightView(weight: WeightChangeData | null | undefined): WeightView | null {
  if (!weight) return null
  const rows = [...weight.blocks]
    .sort(
      (a, b) =>
        Number(a.counted === 0) - Number(b.counted === 0) ||
        Math.abs(b.delta_t) - Math.abs(a.delta_t) ||
        (a.block_id ?? '￿').localeCompare(b.block_id ?? '￿'),
    )
    .map((block): WeightRow => {
      const label = blockLabel(block)
      const unknown = block.counted === 0
      return {
        key: block.block_id ?? '(블록 모름)',
        code: label.code,
        name: label.name,
        before: unknown ? '—' : formatTons(block.before_t),
        after: unknown ? '—' : formatTons(block.after_t),
        delta: unknown ? '—' : formatDelta(block.delta_t),
        parts: block.counted,
        missing: block.missing,
        unknown,
      }
    })
  return {
    rows,
    total: {
      before: formatTons(weight.before_t),
      after: formatTons(weight.after_t),
      delta: formatDelta(weight.delta_t),
      parts: weight.counted,
      missing: weight.missing,
    },
    empty: weight.blocks.length === 0,
    missingNote: weight.missing > 0 ? `중량 정보 없음 ${weight.missing}개 · 합계 제외` : null,
  }
}

/** 부재 수 칸: '3' 또는 '2 · 정보 없음 1'. */
export function partsText(row: Pick<WeightRow, 'parts' | 'missing'>): string {
  return row.missing > 0 ? `${row.parts} · 정보 없음 ${row.missing}` : `${row.parts}`
}

/** 한 줄 요약(검토서 핵심 수치 아래 등): '강재 +0.69t(3.89t → 4.57t) · 블록 1 · 부재 3'. 바뀌는 부재가 없으면 null. */
export function weightSummary(weight: WeightChangeData | null | undefined): string | null {
  const view = weightView(weight)
  if (!view || view.empty || !weight) return null
  const parts = [
    `강재 ${view.total.delta}(${view.total.before} → ${view.total.after})`,
    `블록 ${weight.blocks.length}`,
    `부재 ${view.total.parts}`,
  ]
  if (view.total.missing > 0) parts.push(`중량 정보 없음 ${view.total.missing}`)
  return parts.join(' · ')
}
