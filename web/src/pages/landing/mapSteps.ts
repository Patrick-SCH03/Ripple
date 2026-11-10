// 영향 지도 둘러보기 단계 문구(DESIGN.md 12절): 바뀐 판 → 용접한 판 → 블록 재작업 → 이웃 블록 → 도면 개정 → 발주 → 탑재 일정.
// 단계마다 만드는 함수 하나 — 이름·금액·단계·일수는 모두 example.json 값이고, 그 값이 없는 단계는 null(빠짐).
import { PO_STATUS_NAMES } from '@/lib/labels'
import { formatMoney } from '@/lib/money'
import { blockStageName, nodeText, type Showcase } from './example'

/** 단계 이름(실제 지도 그림 위에서 차례로 확대하는 곳 — captures.ts가 카드 자리를 단다). */
export type MapStepKey = 'change' | 'weld' | 'block' | 'neighbor' | 'drawings' | 'po' | 'erection'

export interface MapStep {
  key: MapStepKey
  title: string
  body: string
}

type Builder = (showcase: Showcase) => MapStep | null

const changeStep: Builder = ({ change }) => {
  const thickness = change.from_mm !== null && change.to_mm !== null ? `, 두께 ${change.from_mm}→${change.to_mm}mm` : ''
  return { key: 'change', title: `바뀐 판 ${change.part_count}장`, body: `${change.block}(${change.block_name}) 블록의 판${thickness}` }
}

const weldStep: Builder = ({ nodes }) => {
  const taper = nodes.find((node) => node.key === 'taper')
  if (!taper) return null
  const t = nodeText(taper)
  const weld = nodes.find((node) => node.key === 'weld_recheck')
  const w = weld ? nodeText(weld) : null
  const rest = w ? ` · ${w.subject}는 ${w.action} ${w.amount}` : ''
  return { key: 'weld', title: t.subject, body: `${t.action} ${t.amount}${rest}` }
}

const blockStep: Builder = ({ nodes }) => {
  const own = nodes.find((node) => node.entity_type === 'block' && node.parent === null)
  if (!own) return null
  const stage = own.stage ? `${blockStageName(own.stage)} 중인 블록이라 ` : ''
  return { key: 'block', title: `${own.name} 블록 재작업`, body: `${stage}재작업비 ${formatMoney(own.amount)}` }
}

const neighborStep: Builder = ({ nodes }) => {
  const neighbor = nodes.find((node) => node.entity_type === 'block' && node.parent !== null)
  if (!neighbor) return null
  const stage = neighbor.stage ? `(${blockStageName(neighbor.stage)} 중)` : ''
  const via = neighbor.relation === 'butt_weld' ? '맞대기 용접으로' : '연결로'
  return {
    key: 'neighbor',
    title: `이웃 ${neighbor.name} 블록`,
    body: `${via} 이어진 ${neighbor.full_name ?? neighbor.name} 블록${stage}도 재작업 ${formatMoney(neighbor.amount)}`,
  }
}

const drawingsStep: Builder = ({ nodes }) => {
  const drawings = nodes.filter((node) => node.entity_type === 'drawing')
  if (!drawings.length) return null
  const same = drawings.every((d) => d.amount === drawings[0].amount)
  const cost = same ? `장마다 ${formatMoney(drawings[0].amount)}` : formatMoney(drawings.reduce((sum, d) => sum + d.amount, 0))
  return { key: 'drawings', title: `도면 개정 ${drawings.length}장`, body: `${drawings.map((d) => d.name ?? d.key).join(' · ')}, ${cost}` }
}

const poStep: Builder = ({ nodes }) => {
  const po = nodes.find((node) => node.entity_type === 'po_line')
  if (!po) return null
  const t = nodeText(po)
  const status = po.stage ? `${PO_STATUS_NAMES[po.stage] ?? po.stage} 단계에 들어간 발주라 ` : ''
  return { key: 'po', title: `발주 ${po.name}`, body: `${status}${t.action} ${t.amount}` }
}

/** 제품 판정과 같은 뜻('예상 최대 지연', '지연 가능')을 소개 화면 말투(합니다체)로 — 엔진 출력에 없는 인과 서술은 붙이지 않는다. */
const erectionStep: Builder = ({ change, zone_exit: exit }) =>
  exit && exit.delay_days > 0
    ? { key: 'erection', title: `${change.block} 탑재 일정`, body: `${exit.name} 출구가 최대 ${exit.delay_days}일 늦어질 수 있습니다` }
    : null

const BUILDERS: Builder[] = [changeStep, weldStep, blockStep, neighborStep, drawingsStep, poStep, erectionStep]

export function mapSteps(showcase: Showcase): MapStep[] {
  return BUILDERS.map((build) => build(showcase)).filter((step): step is MapStep => step !== null)
}
