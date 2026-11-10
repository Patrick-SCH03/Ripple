// 결정 도우미의 비슷한 과거 사례(DESIGN.md 13절): 접어서 시작한다 — 머리(합성이면 늘 '합성 과거 사례' 칩) · 요약 한 줄 ·
// '사례 n건 보기' 단추만 보이고, 펼치면 사례마다 번호·제목 · 같은 점 · 결정 · 무엇으로 진행 · 예측 → 실적(차이 %) ·
// 마감 며칠 전 결정. 카드가 핵심 수치 카드를 화면 밖으로 밀지 않게. 사례가 있을 때만 그린다(카드가 판단).
import { ChevronDown, History } from 'lucide-react'
import { useId, useState } from 'react'
import type { PastCases } from '@/api/client'
import { DECISION_LABEL, casesToggleLabel, outcomeText, syntheticCases, timingText } from '@/lib/brief'
import { cn } from '@/lib/utils'

const CHIP = 'inline-flex h-6 shrink-0 items-center rounded-sm border px-1.5 text-xs font-medium whitespace-nowrap'

export function PastCasesList({ cases, defaultOpen = false }: { cases: PastCases; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const listId = useId()
  return (
    <div className="mt-3 border-t border-border pt-2.5" data-testid="decision-brief-cases">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h4 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold">
          <History aria-hidden className="size-4 text-foreground-secondary" />
          비슷한 과거 사례
          {syntheticCases(cases) && (
            <span className={cn(CHIP, 'border-border text-foreground-secondary')} data-testid="decision-brief-synthetic">
              합성 과거 사례
            </span>
          )}
        </h4>
        <button
          type="button"
          className="inline-flex min-h-6 items-center gap-1 text-sm font-semibold text-primary underline-offset-2 hover:underline"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
          data-testid="decision-brief-cases-toggle"
        >
          {casesToggleLabel(cases.items.length, open)}
          <ChevronDown aria-hidden className={cn('size-4 transition-transform', open && 'rotate-180')} />
        </button>
      </div>
      {cases.summary && <p className="mt-1 text-sm text-foreground-secondary break-keep">{cases.summary}</p>}
      {open && (
        <ol id={listId} className="mt-1.5 space-y-2" data-testid="decision-brief-cases-list">
          {cases.items.map((item, index) => {
            const when = timingText(item.days_before_deadline)
            return (
              <li key={item.case_id} className="text-sm" data-case={item.case_id}>
                <p className="break-keep">
                  <span className="tabular-nums text-foreground-secondary">{index + 1}.</span> {item.title}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {item.same.map((same) => (
                    <span key={same} className={cn(CHIP, 'border-border text-foreground-secondary')}>
                      {same}
                    </span>
                  ))}
                  <span className={cn(CHIP, 'border-primary/40 text-primary')}>{DECISION_LABEL[item.decision]}</span>
                </div>
                <p className="mt-0.5 text-foreground-secondary tabular-nums break-keep">
                  {[item.chosen, outcomeText(item), when].filter(Boolean).join(' · ')}
                </p>
                {item.note && <p className="mt-0.5 text-foreground-secondary break-keep">{item.note}</p>}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
