// 파급 그래프의 카드(React Flow 사용자 노드): 종류 아이콘 · 이름 · 심각도 배지(DESIGN.md 6절).
// 테두리 = 심각도 색, 변경 지점 = 굵은 테두리, 변경으로 생긴 노드 = 점선. 묶음 카드는 펼치기 단추가 있다.
import { Handle, type Node, type NodeProps, Position } from '@xyflow/react'
import {
  Box,
  Boxes,
  CalendarClock,
  ChevronsUpDown,
  FileText,
  Map as MapIcon,
  Package,
  ReceiptText,
  Ship,
  type LucideIcon,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { SeverityBadge } from '@/components/common/SeverityBadge'
import type { GraphCard } from '@/lib/graphModel'
import { cn } from '@/lib/utils'

const TYPE_ICONS: Record<string, LucideIcon> = {
  part: Box,
  block: Boxes,
  po: ReceiptText,
  po_line: ReceiptText,
  stock: Package,
  drawing: FileText,
  activity: CalendarClock,
  zone: MapIcon,
  ship: Ship,
}

const BORDER: Record<string, string> = {
  high: 'border-danger',
  medium: 'border-warning',
  low: 'border-primary',
  info: 'border-border-strong',
}

export type CardData = {
  card: GraphCard
  /** 카드 제목(노드 이름, 묶음은 "테이퍼 가공 · 부재 8개"). */
  title: string
  /** 아래 줄(종류 · 역할 등). */
  meta: string
  /** 나타나기 지연(ms). 다시 보기 때 바뀌면 애니메이션이 다시 돈다. */
  delay: number
  /** 고른 카드인지(테두리 강조). */
  current: boolean
  /** 주요 경로 끝(가장 심각한 영향) — 테두리 바깥으로 맥동한다. */
  peak?: boolean
  /** 움직임이 켜져 있나(꺼지면 맥동을 멈추고 고리를 지운다 — 나타나기 애니메이션은 그대로). */
  moving?: boolean
  onExpand?: (id: string) => void
}

export type CardNode = Node<CardData, 'card'>

export function FlowCard({ data }: NodeProps<CardNode>) {
  const { card, title, meta, delay, current, peak, moving, onExpand } = data
  const Icon = TYPE_ICONS[card.type] ?? Box
  const group = card.members.length > 1
  return (
    <div
      className={cn(
        'ripple-appear flex h-full w-full flex-col justify-between rounded-md border bg-surface px-2.5 py-2 text-left',
        BORDER[card.severity ?? 'info'],
        card.role && 'border-2 border-foreground',
        card.virtual && 'border-dashed',
        current && 'ring-2 ring-ring ring-offset-2 ring-offset-surface',
        peak && 'rp-pulse',
      )}
      style={
        peak
          ? ({
              animationDelay: `${delay}ms`,
              animationPlayState: `running, ${moving ? 'running' : 'paused'}`,
              '--rp-pulse': moving ? undefined : 'transparent',
            } as CSSProperties)
          : { animationDelay: `${delay}ms` }
      }
    >
      <Handle type="target" position={Position.Left} isConnectable={false} className="!size-1 !min-h-0 !border-0 !bg-transparent" />
      <div className="flex min-w-0 items-start gap-1.5">
        <Icon aria-hidden className="mt-0.5 size-3.5 shrink-0 text-foreground-secondary" />
        <p className="line-clamp-2 min-w-0 flex-1 text-sm leading-tight font-medium">{title}</p>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-xs text-foreground-secondary">{meta}</span>
        {card.severity && <SeverityBadge severity={card.severity} />}
        {group && onExpand && (
          <button
            type="button"
            tabIndex={-1}
            aria-label={`${title} 펼치기`}
            title="펼치기"
            onClick={(event) => {
              event.stopPropagation()
              onExpand(card.id)
            }}
            className="nodrag nopan grid size-5 place-items-center rounded-sm text-foreground-secondary hover:bg-hover"
          >
            <ChevronsUpDown aria-hidden className="size-3.5" />
          </button>
        )}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} className="!size-1 !min-h-0 !border-0 !bg-transparent" />
    </div>
  )
}
