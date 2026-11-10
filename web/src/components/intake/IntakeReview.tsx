// 문서로 넣기 확인표(docs/input.md(문서 접수) 3절): 요약 · 문서 문제 · 문서 머리글(고치기) · 같은 원문 번호의 기존 설계변경(이어 가기) ·
// 항목 카드 · 정할 것 · 원문에서 항목 위치. 상태는 대화상자(IntakeDialog)가 들고, 여기는 그리기와 고침 전달만 한다.
import { useState } from 'react'
import type { IntakeHeader, IntakeProposal, TurnContext } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatDay } from '@/lib/format'
import { EMPTY_ROW, documentParts, itemTone, proposalSummary, type RowState } from '@/lib/intake'
import { cn } from '@/lib/utils'
import { IntakeItemCard } from './IntakeItemCard'

/** 확인표 단계의 상태(대화상자가 든다). */
export interface Review {
  proposal: IntakeProposal
  rows: Record<string, RowState>
  header: IntakeHeader
  continueEcn: boolean
  busy: boolean
  error: string | null
  problems: Record<string, string[]>
}

const HEADER_FIELDS: {
  key: keyof IntakeHeader
  label: string
  type?: string
  max: number
}[] = [
  { key: 'ecn_ref', label: '원문 번호', max: 120 },
  { key: 'revision', label: '개정', max: 40 },
  { key: 'title', label: '제목', max: 200 },
  { key: 'requested_by', label: '요청', max: 80 },
  { key: 'requested_on', label: '요청일', type: 'date', max: 10 },
  { key: 'reason', label: '사유', max: 300 },
]

/** 문서 머리글 한 줄: 읽은 칸만 '원문 번호 … · 제목 · 요청 … · 사유 …'. 하나도 없으면 안내. */
function headerLine(header: IntakeHeader): string {
  const parts = [
    header.ecn_ref && `원문 번호 ${header.ecn_ref}${header.revision ? ` 개정 ${header.revision}` : ''}`,
    header.title,
    header.requested_by && `요청 ${header.requested_by}`,
    header.requested_on && formatDay(header.requested_on),
    header.reason && `사유 ${header.reason}`,
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : '읽은 머리글 정보 없음(제목은 항목으로)'
}

interface ReviewProps {
  review: Review
  context: TurnContext | null
  compact: boolean
  reasons: string[]
  onRow: (itemId: string, row: RowState) => void
  onHeader: (header: IntakeHeader) => void
  onContinue: (value: boolean) => void
  onAcceptClean: () => void
}

export function IntakeReview({ review, context, compact, reasons, onRow, onHeader, onContinue, onAcceptClean }: ReviewProps) {
  const { proposal } = review
  const [headerOpen, setHeaderOpen] = useState(false)
  const clean = proposal.items.filter(
    (item) => itemTone(item) === 'clean' && !review.rows[item.item_id]?.action,
  ).length
  return (
    <div className="space-y-3" data-testid="intake-review">
      <div className="rounded-md border border-border bg-muted/40 px-3 py-2">
        <p className="font-semibold">
          {proposalSummary(proposal)}
          <span className="ml-2 text-sm font-normal text-foreground-secondary">
            {proposal.extractor === 'rule+llm' ? '읽기: AI + 규칙' : '읽기: 규칙'}
          </span>
        </p>
        <p className="mt-0.5 text-sm text-foreground-secondary">
          항목마다 맞음·고침·비서로·뺌 선택 · 고침은 대상·수치만 · 그 밖의 수정은 비서로
        </p>
      </div>

      {proposal.problems.length > 0 && (
        <ul className="space-y-0.5 rounded-md border border-warning/40 bg-warning/8 px-3 py-2 text-sm">
          {proposal.problems.map((problem, i) => (
            <li key={i}>{problem.message}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
        <span className="font-medium">문서 머리글</span>
        <span className="min-w-0 text-foreground-secondary [overflow-wrap:anywhere]">{headerLine(review.header)}</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setHeaderOpen((open) => !open)}
          aria-expanded={headerOpen}
          className={compact ? 'h-11' : 'h-9'}
        >
          {headerOpen ? '접기' : '고치기'}
        </Button>
      </div>
      {headerOpen && (
        <fieldset className="grid gap-2 sm:grid-cols-3" disabled={review.busy} aria-label="문서 머리글 고치기">
          {HEADER_FIELDS.map((field) => (
            <label
              key={field.key}
              className={cn(
                'space-y-0.5 text-sm',
                (field.key === 'title' || field.key === 'reason') && 'sm:col-span-3',
              )}
            >
              <span className="text-foreground-secondary">{field.label}</span>
              <Input
                type={field.type ?? 'text'}
                value={review.header[field.key] ?? ''}
                maxLength={field.max}
                onChange={(event) =>
                  onHeader({
                    ...review.header,
                    [field.key]: event.target.value || null,
                  })
                }
                className={cn('rounded-sm', compact ? 'h-11' : 'h-9')}
              />
            </label>
          ))}
        </fieldset>
      )}

      {proposal.existing && (
        <div className="rounded-md border border-primary/40 bg-primary/8 px-3 py-2 text-sm">
          <p>
            같은 원문 번호로 기록한 설계변경 있음: <span className="font-medium">{proposal.existing.title}</span>
            <span className="ml-1 font-mono text-sm text-foreground-secondary">{proposal.existing.ecn_id}</span>
          </p>
          {proposal.existing.can_continue ? (
            <label className="mt-1 flex items-center gap-2">
              <input
                type="checkbox"
                checked={review.continueEcn}
                disabled={review.busy}
                onChange={(event) => onContinue(event.target.checked)}
                className="size-4"
              />
              그 설계변경의 새 개정으로 이어 가기
            </label>
          ) : (
            <p className="mt-0.5 text-foreground-secondary">실행·종료된 설계변경 — 새 설계변경으로 확정</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">항목 {proposal.items.length}개</h3>
        {clean > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={onAcceptClean}
            disabled={review.busy}
            className={compact ? 'h-11' : undefined}
          >
            문제 없는 {clean}개 맞음으로
          </Button>
        )}
      </div>
      {context && (
        <ol className="space-y-2">
          {proposal.items.map((item) => (
            <IntakeItemCard
              key={item.item_id}
              item={item}
              row={review.rows[item.item_id] ?? EMPTY_ROW}
              onRow={(row) => onRow(item.item_id, row)}
              context={context}
              compact={compact}
              busy={review.busy}
              problems={review.problems[item.item_id] ?? []}
            />
          ))}
        </ol>
      )}

      {reasons.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-warning">정할 것 {reasons.length}개</summary>
          <ul className="mt-1 space-y-0.5 pl-3 text-foreground-secondary">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </details>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer text-foreground-secondary">원문에서 항목 위치 보기</summary>
        <p className="mt-1 max-h-64 overflow-y-auto rounded-md border border-border p-2 whitespace-pre-wrap [overflow-wrap:anywhere]">
          {documentParts(proposal.document, proposal.items).map((part, i) =>
            part.itemId ? (
              <mark key={i} className="rounded-sm bg-primary/10 text-foreground">
                <span className="mr-1 font-mono text-xs text-primary">{part.itemId}</span>
                {part.text}
              </mark>
            ) : (
              <span key={i} className="text-foreground-secondary">
                {part.text}
              </span>
            ),
          )}
        </p>
        <p className="mt-1 text-xs text-foreground-secondary">판단 확률 근거: {proposal.calibration_note}</p>
      </details>
    </div>
  )
}
