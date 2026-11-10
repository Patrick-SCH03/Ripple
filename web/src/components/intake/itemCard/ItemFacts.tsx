// 확인표 항목의 읽은 것: 원문 조각(읽은 말에 밑줄, AI·추정 값은 agent 색) · 칸마다 값과 채움 방식 · 문제 · 근거 더 보기
// (AI가 읽은 것, 대상 후보 판단 확률 — 첫 화면에 확률을 두지 않는다).
import { AlertTriangle } from 'lucide-react'
import type { ChangeDraft, IntakeItem } from '@/api/client'
import { BLOCKING, METHOD_LABEL, fillText, fragmentParts, needsLook } from '@/lib/intake'
import { OP_NAMES } from '@/lib/labels'
import { cn } from '@/lib/utils'

export function ItemSource({ item, draft }: { item: IntakeItem; draft: ChangeDraft | null }) {
  return (
    <p className="border-l-2 border-border-strong pl-2 text-sm [overflow-wrap:anywhere] [word-break:keep-all]">
      {fragmentParts(item.source.text, draft).map((part, i) =>
        part.slot ? (
          <mark
            key={i}
            className={cn(
              'rounded-sm bg-transparent underline decoration-2 underline-offset-2',
              part.method && needsLook(part.method) ? 'text-agent decoration-agent/60' : 'text-foreground decoration-primary/50',
            )}
          >
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </p>
  )
}

export function ItemSlots({ item, draft }: { item: IntakeItem; draft: ChangeDraft }) {
  return (
    <dl className="grid grid-cols-[minmax(6rem,auto)_1fr] gap-x-3 gap-y-0.5 text-sm">
      {item.slots.map((slot) => {
        const fill = draft.slots?.[slot.name]
        const text = fillText(fill)
        return (
          <div key={slot.name} className="contents">
            <dt className="text-foreground-secondary">{slot.label}</dt>
            <dd className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className={cn('min-w-0 [overflow-wrap:anywhere]', slot.kind === 'parts' && 'font-mono text-sm')}>
                {text ?? '—'}
              </span>
              {fill && <MethodBadge method={fill.method} />}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

export function ItemIssues({ issues }: { issues: IntakeItem['issues'] }) {
  return (
    <ul className="space-y-0.5 text-sm">
      {issues.map((issue, i) => (
        <li
          key={`${issue.code}-${issue.slot ?? ''}-${i}`}
          className={cn('flex gap-1.5', BLOCKING.has(issue.code) ? 'text-warning' : 'text-foreground-secondary')}
        >
          <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  )
}

export function ItemEvidence({ item }: { item: IntakeItem }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-foreground-secondary">근거 더 보기</summary>
      <div className="mt-1 space-y-1 pl-3">
        {item.ai && (
          <p>
            <span className="text-agent">AI가 읽은 것</span> ·{' '}
            {[
              item.ai.op && (OP_NAMES[item.ai.op] ?? item.ai.op),
              item.ai.target,
              item.ai.before && item.ai.after ? `${item.ai.before} → ${item.ai.after}` : (item.ai.after ?? item.ai.before),
              item.ai.reason,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
        {item.candidates.length > 0 && (
          <p className="text-foreground-secondary">
            대상 후보 판단 확률:{' '}
            {item.candidates
              .map((c) => `${c.label} ${c.probability != null ? `${Math.round(c.probability * 100)}%` : '—'}`)
              .join(' · ')}
          </p>
        )}
      </div>
    </details>
  )
}

function MethodBadge({ method }: { method: keyof typeof METHOD_LABEL }) {
  return (
    <span
      className={cn(
        'rounded-sm border px-1 text-xs leading-4',
        needsLook(method) ? 'border-agent/40 text-agent' : 'border-border text-foreground-secondary',
      )}
    >
      {METHOD_LABEL[method]}
    </span>
  )
}
