// 설명·알림 블록 한 줄(DESIGN.md 6절 AI 비서): 서버가 준 조각대로 그린다. 엔터티 이름은 근거 칩(누르면 상세 영향 지도
// 탭에서 그 엔터티 근거), 값은 굵은 숫자. 화면은 글에서 이름·숫자를 다시 찾지 않는다.
import { Fragment } from 'react'
import type { RenderedBlock } from '@/api/client'
import { partsOf } from '@/lib/assistant'
import { cn } from '@/lib/utils'

interface Props {
  block: RenderedBlock
  /** 근거 칩을 누를 수 있는 엔터티면 그 동작(그래프에 없으면 undefined를 돌려 글로 둔다). */
  onEntity?: (entityId: string) => (() => void) | undefined
  className?: string
}

export function BlockText({ block, onEntity, className }: Props) {
  return (
    <p className={cn(block.kind === 'metric' && 'tabular-nums', className)}>
      {partsOf(block).map((part, index) => {
        if (part.entity_id) {
          const open = onEntity?.(part.entity_id)
          return open ? (
            <button
              key={index}
              type="button"
              data-entity={part.entity_id}
              onClick={open}
              className="mx-px inline rounded-sm border border-border bg-muted px-1 py-px font-medium text-primary hover:bg-hover focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              {part.text}
            </button>
          ) : (
            <span key={index} className="font-medium">
              {part.text}
            </span>
          )
        }
        if (part.value) {
          return (
            <strong key={index} className="font-semibold">
              {part.text}
            </strong>
          )
        }
        return <Fragment key={index}>{part.text}</Fragment>
      })}
    </p>
  )
}
