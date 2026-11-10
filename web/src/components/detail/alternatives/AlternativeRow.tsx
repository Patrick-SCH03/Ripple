// 대안 표 한 줄: 이름(권고) · 판정 칩 · 출구 예상 지연 · 마감일 D-n · 총변경비용 → 펼치면 판정 근거 · 바꾸는 것 · 늦어지면 ·
// '이 대안으로 분석 보기'. 넓으면 한 줄, 좁으면 위아래(컨테이너 폭 기준).
import { ChevronRight, CircleAlert, CircleCheck, CircleHelp, type LucideIcon } from 'lucide-react'
import type { AnalysisRequest, AnalysisResult } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  ELIGIBILITY_NAMES,
  ELIGIBILITY_TONES,
  REQUEST_ALT,
  keepUntilText,
  opText,
  ratioText,
  requestFor,
  shortName,
} from '@/lib/alternatives'
import { deadlineMark } from '@/lib/ecnList'
import { formatMoney, formatRange } from '@/lib/money'
import { cn } from '@/lib/utils'

type Alternative = AnalysisResult['alternatives'][number]

const TONE_CLASS = {
  success: 'border-success/40 bg-success/8 text-success',
  danger: 'border-danger/40 bg-danger/8 text-danger',
  warning: 'border-warning/40 bg-warning/8 text-warning',
} as const

const ICONS: Record<Alternative['eligibility']['status'], LucideIcon> = {
  meets: CircleCheck,
  short: CircleAlert,
  designer: CircleHelp,
}

export function EligibilityBadge({ alternative }: { alternative: Alternative }) {
  const status = alternative.eligibility.status
  const Icon = ICONS[status]
  if (alternative.alt_id === REQUEST_ALT) {
    return <span className="text-sm text-foreground-secondary">비교 기준</span>
  }
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center gap-1 rounded-sm border px-1.5 text-xs font-medium whitespace-nowrap',
        TONE_CLASS[ELIGIBILITY_TONES[status]],
      )}
    >
      <Icon aria-hidden className="size-3" />
      {ELIGIBILITY_NAMES[status]}
    </span>
  )
}

interface OpenProps {
  alternative: Alternative
  /** 상세에 보이는 분석의 요청(연산만 대안 연산으로 바꾼다). */
  request: AnalysisRequest
  compact: boolean
  onOpen: (request: AnalysisRequest, label: string) => void
}

/** '이 대안으로 분석 보기'(좁은 화면은 터치 높이). */
export function OpenAlternative({ alternative, request, compact, onOpen }: OpenProps) {
  return (
    <Button
      variant="outline"
      size="sm"
      className={cn(compact && 'h-11 px-3')}
      onClick={() => onOpen(requestFor(request, alternative), `대안: ${shortName(alternative)}`)}
    >
      이 대안으로 분석 보기
    </Button>
  )
}

interface RowProps extends OpenProps {
  index: number
  expanded: boolean
  onToggle: () => void
  recommended: boolean
  /** 기준일(마감일 D-n). */
  asOf: string
}

export function AlternativeRow({ alternative, index, expanded, onToggle, recommended, asOf, ...open }: RowProps) {
  const detailId = `alternative-${index}`
  const mark = alternative.deadline ? deadlineMark(alternative.deadline, asOf) : null
  return (
    <li>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={expanded ? detailId : undefined}
        onClick={onToggle}
        className="flex min-h-9 w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left hover:bg-hover @min-[52rem]:flex-nowrap"
      >
        <ChevronRight
          aria-hidden
          className={cn('size-4 shrink-0 text-foreground-secondary transition-transform', expanded && 'rotate-90')}
        />
        {/* 좁으면(52rem 미만 — 1024px 화면 포함) 이름이 첫 줄 전체, 판정 · 지연 · 기한 · 금액은 둘째 줄(이름 칸이 한 글자씩 접히지 않게) */}
        <span className="min-w-0 flex-1 basis-[calc(100%-2rem)] @min-[52rem]:basis-0">
          {alternative.label}
          {recommended && (
            <span className="ml-2 inline-flex h-6 items-center rounded-sm border border-primary/40 bg-primary/8 px-1.5 align-middle text-xs font-medium text-primary">
              권고
            </span>
          )}
        </span>
        <span className="ml-7 shrink-0 @min-[52rem]:ml-0 @min-[52rem]:w-28">
          <EligibilityBadge alternative={alternative} />
        </span>
        <span className="shrink-0 text-sm tabular-nums @min-[52rem]:w-36 @min-[52rem]:text-right">
          <span className="@min-[52rem]:hidden text-foreground-secondary">출구 예상 지연 </span>
          {alternative.max_exit_delay_days > 0 ? `${alternative.max_exit_delay_days}일` : '없음'}
        </span>
        <span className="shrink-0 text-sm tabular-nums @min-[52rem]:w-24 @min-[52rem]:text-right" title={mark?.label}>
          <span className="@min-[52rem]:hidden text-foreground-secondary">결정 기한 </span>
          {mark?.text ?? '-'}
        </span>
        <span className="ml-auto shrink-0 text-right tabular-nums @min-[52rem]:w-48">
          <span className="block font-semibold">{formatMoney(alternative.total.value)}</span>
          {alternative.total.low !== alternative.total.high && (
            <span className="block text-sm whitespace-nowrap text-foreground-secondary">
              {formatRange(alternative.total.low, alternative.total.high)}
            </span>
          )}
        </span>
      </button>
      {expanded && (
        <div id={detailId} className="bg-muted px-3 py-3 pl-10 text-sm">
          <dl className="space-y-2">
            {alternative.alt_id !== REQUEST_ALT && (
              <div className="grid gap-0.5 @md:grid-cols-[6.5rem_minmax(0,1fr)] @md:gap-3">
                <dt className="font-medium text-foreground-secondary">판정</dt>
                <dd className="min-w-0 space-y-0.5">
                  {alternative.eligibility.note && <p>{alternative.eligibility.note}</p>}
                  {ratioText(alternative) && <p className="tabular-nums">{ratioText(alternative)}</p>}
                  {alternative.eligibility.basis && (
                    <p className="text-foreground-secondary">{alternative.eligibility.basis}</p>
                  )}
                </dd>
              </div>
            )}
            <div className="grid gap-0.5 @md:grid-cols-[6.5rem_minmax(0,1fr)] @md:gap-3">
              <dt className="font-medium text-foreground-secondary">바꾸는 것</dt>
              <dd className="min-w-0 space-y-0.5">
                {alternative.ops.map((op, i) => (
                  <p key={i}>{opText(op)}</p>
                ))}
              </dd>
            </div>
            {keepUntilText(alternative) && (
              <div className="grid gap-0.5 @md:grid-cols-[6.5rem_minmax(0,1fr)] @md:gap-3">
                <dt className="font-medium text-foreground-secondary">늦어지면</dt>
                <dd className="min-w-0">{keepUntilText(alternative)}</dd>
              </div>
            )}
          </dl>
          {alternative.alt_id !== REQUEST_ALT && (
            <div className="mt-3 border-t border-border pt-2.5">
              <OpenAlternative alternative={alternative} {...open} />
            </div>
          )}
        </div>
      )}
    </li>
  )
}
