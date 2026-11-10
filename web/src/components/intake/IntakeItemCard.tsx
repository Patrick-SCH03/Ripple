// 확인표 한 항목(DESIGN.md 6절 '문서로 넣기'): 원문 조각(어느 말을 어느 칸으로 읽었는지) · 칸마다 값과 채움 방식(AI·추정은
// agent 색) · 문제 · 사람 결정(맞음 / 고침 / 비서로 / 뺌). 고침은 대상(후보)과 수치만, 나머지는 비서로 넘긴다.
// 판단 확률·AI가 읽은 원래 값은 펼침 안에만 둔다. 읽은 것·고침 칸은 itemCard/의 부품.
import { AlertTriangle, CheckCircle2, Eye } from 'lucide-react'
import type { ChangeDraft, IntakeItem, TurnContext } from '@/api/client'
import { Button } from '@/components/ui/button'
import { isUnsupported, itemTone, rowProblem, type ItemTone, type RowAction, type RowState } from '@/lib/intake'
import { OP_NAMES } from '@/lib/labels'
import { cn } from '@/lib/utils'
import { HandoffPanel } from './HandoffPanel'
import { ItemEditForm } from './itemCard/ItemEditForm'
import { ItemEvidence, ItemIssues, ItemSlots, ItemSource } from './itemCard/ItemFacts'

interface Props {
  item: IntakeItem
  row: RowState
  onRow: (row: RowState) => void
  context: TurnContext
  compact: boolean
  busy: boolean
  /** 서버가 확정하지 못한 이유(422). */
  problems: string[]
}

const ACTIONS: { action: RowAction; label: string }[] = [
  { action: 'accept', label: '맞음' },
  { action: 'edit', label: '고침' },
  { action: 'handoff', label: '비서로' },
  { action: 'drop', label: '뺌' },
]

const TONE: Record<ItemTone, { label: string; className: string; Icon: typeof Eye }> = {
  blocked: { label: '확인 필요', className: 'text-warning', Icon: AlertTriangle },
  look: { label: '살펴보기', className: 'text-primary', Icon: Eye },
  clean: { label: '문제 없음', className: 'text-success', Icon: CheckCircle2 },
}

export function IntakeItemCard({ item, row, onRow, context, compact, busy, problems }: Props) {
  const tone = TONE[itemTone(item)]
  const draft = item.draft ?? null
  const op = draft?.op ? String(draft.op.value) : null
  const problem = row.action ? rowProblem(item, row) : null
  const height = compact ? 'h-11' : 'h-9'
  const choose = (action: RowAction) =>
    onRow({ ...row, action, ...(action === 'handoff' ? { draft: null, summary: null } : {}) })
  const drafted = (next: ChangeDraft, summary: string | null) => onRow({ ...row, action: 'handoff', draft: next, summary })

  return (
    <li className="space-y-2 rounded-md border border-border bg-surface p-3" data-testid="intake-item" data-item={item.item_id}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-sm text-foreground-secondary">{item.item_id}</span>
        <span className="font-medium">{op ? (OP_NAMES[op] ?? op) : '변경 종류 판독 불가'}</span>
        <span className={cn('inline-flex items-center gap-1 text-xs font-medium', tone.className)}>
          <tone.Icon aria-hidden className="size-3.5" />
          {tone.label}
        </span>
        {item.extractor === 'llm' && <span className="text-xs font-medium text-agent">AI 추출 항목</span>}
      </div>

      <ItemSource item={item} draft={draft} />

      {draft && item.slots.length > 0 && <ItemSlots item={item} draft={draft} />}

      {item.issues.length > 0 && <ItemIssues issues={item.issues} />}

      {(item.ai || item.candidates.some((candidate) => candidate.probability != null)) && <ItemEvidence item={item} />}

      <div role="group" aria-label={`${item.item_id} 결정`} className="flex flex-wrap gap-1.5">
        {ACTIONS.map(({ action, label }) => {
          const needsDraft = (action === 'accept' || action === 'edit') && !draft
          const dropOnly = action !== 'drop' && isUnsupported(item)
          return (
            <Button
              key={action}
              size="sm"
              variant={row.action === action ? 'default' : 'outline'}
              aria-pressed={row.action === action}
              disabled={busy || needsDraft || dropOnly}
              title={
                dropOnly
                  ? '지원하지 않는 변경 — 빼기만 가능'
                  : needsDraft
                    ? '읽지 못한 항목 — 비서로 넘기기 또는 빼기'
                    : undefined
              }
              onClick={() => choose(action)}
              className={height}
            >
              {label}
            </Button>
          )
        })}
      </div>

      {row.action === 'edit' && draft && (
        <ItemEditForm item={item} draft={draft} row={row} onRow={onRow} compact={compact} busy={busy} />
      )}

      {row.action === 'handoff' && !row.draft && (
        <HandoffPanel item={item} context={context} partIds={row.partIds} compact={compact} onDrafted={drafted} />
      )}
      {row.action === 'handoff' && row.draft && (
        <p className="text-sm">
          <span className="font-medium text-agent">비서가 마친 초안</span>
          {row.summary ? ` · ${row.summary}` : ''}
        </p>
      )}

      {problem && <p className="text-sm text-warning">{problem}</p>}
      {problems.map((message) => (
        <p key={message} role="alert" className="text-sm text-danger">
          {message}
        </p>
      ))}
    </li>
  )
}
