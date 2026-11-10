// ECN 목록 한 줄(DESIGN.md 6·13절): 크게 읽히는 것 셋만 — 제목(한 줄, 넘치면 말줄임) · 결정 기한(D-n, 색) · 총변경비용.
// 둘째 줄은 작게: 판정 칩 하나 + 결재 상태(작은 글자) · ECN 번호 · 블록. 나머지 부가 정보(개정·요청한 사람)는 마우스 올림(title).
// 샘플 목록 · 결재 대기 · 기록된 다른 설계변경이 같은 모양을 쓴다.
import type { ReactNode } from 'react'
import type { DeadlineMark } from '@/lib/ecnList'
import { formatMoney } from '@/lib/money'
import { cn } from '@/lib/utils'

const TONES = { danger: 'text-danger', neutral: 'text-foreground', relaxed: 'text-foreground-secondary font-normal' }

/** 목록 표지: data-ecn-item(키보드 이동·시험) · data-recorded(기록된 다른 설계변경) · data-pending-item(결재 대기). */
export type RowMarks = Partial<Record<'data-ecn-item' | 'data-recorded' | 'data-pending-item', true>>

interface Props {
  title: string
  mark: DeadlineMark | null
  /** 판정 칩(하나) — 결재 상태는 meta 앞 작은 글자로. */
  tag: ReactNode
  /** 둘째 줄 작은 글: 결재 상태 · ECN 번호 · 블록. */
  meta: ReactNode
  /** 마우스 올림: 제목 전체와 부가 정보(개정·요청한 사람 등). */
  hint: string
  /** 반려·보류 사유처럼 줄마다 다른 한 줄: 줄에 셋째 줄을 세우지 않고 마우스 올림에 붙인다(사유는 고른 건의 결재 띠에 한 줄). */
  extra?: string
  total: number | null
  /** 금액이 무엇의 총변경비용인지(툴팁). */
  totalTitle: string
  current: boolean
  onClick: () => void
  marks: RowMarks
}

export function EcnRow({ title, mark, tag, meta, hint, extra, total, totalTitle, current, onClick, marks }: Props) {
  return (
    <li>
      <button
        type="button"
        {...marks}
        title={extra ? `${hint}\n${extra}` : hint}
        aria-current={current ? 'true' : undefined}
        onClick={onClick}
        className={cn(
          'relative grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-4 py-3 text-left hover:bg-hover',
          'aria-[current=true]:bg-muted aria-[current=true]:before:absolute aria-[current=true]:before:inset-y-0 aria-[current=true]:before:left-0 aria-[current=true]:before:w-0.5 aria-[current=true]:before:bg-primary',
        )}
      >
        <span className="truncate text-base font-semibold">{title}</span>
        <span className={cn('text-base font-semibold whitespace-nowrap tabular-nums', mark && TONES[mark.tone])}>
          {mark && (
            <>
              <span className="sr-only">결정 기한 </span>
              <span title={mark.label}>{mark.text}</span>
            </>
          )}
        </span>
        <span className="flex min-w-0 items-center gap-2 text-xs text-foreground-secondary">
          {tag}
          <span className="min-w-0 truncate">{meta}</span>
        </span>
        <span className="text-base font-semibold whitespace-nowrap text-foreground tabular-nums" title={totalTitle}>
          {total !== null && (
            <>
              <span className="sr-only">총변경비용 </span>
              {formatMoney(total)}
            </>
          )}
        </span>

      </button>
    </li>
  )
}
