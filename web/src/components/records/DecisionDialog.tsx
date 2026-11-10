// 결정 대화상자(승인·반려·보류·무비용 담당자 처리, DESIGN.md 13절): 무엇을 결정하는지(그 개정의 판정·핵심 수치·가정 —
// 기록 본문 그대로) · 결재선 단계·전결 안내 · 확인 필요 항목 체크(승인·담당자 처리) · 사유 · 오류는 단추 위 · 왼쪽 '닫기'.
import { useState } from 'react'
import type { ChecklistItem, EcnAction, VerdictLevel } from '@/api/client'
import { GlanceTiles } from '@/components/common/GlanceTiles'
import { SegmentText } from '@/components/common/SegmentText'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useReturnFocus } from '@/lib/focus'
import { ACTION_LABEL, decisionProblem } from '@/lib/records'
import { restFacts, type Fact, type GlanceFact } from '@/lib/revisions'

const DESCRIPTION: Partial<Record<EcnAction, string>> = {
  approve: '이 개정의 분석대로 진행 · 사유·확인 항목은 승인 기록에',
  reject: '이 개정 반려 · 담당자가 다시 분석해 새 개정으로',
  hold: '결정 미룸 · 같은 검토를 나중에 승인·반려 가능',
  settle: '도면 개정뿐 · 승인 가능 — 결재선 없이 담당자 처리 · 승인 상태로 기록 · 감사 기록: 무비용 담당자 처리',
}

/** 확인 목록을 체크해 보내는 행동(승인 · 무비용 담당자 처리). */
const CHECKED: readonly EcnAction[] = ['approve', 'settle']

interface Props {
  action: EcnAction | null
  revision: number
  /** 결정 대상이 바뀌면(다른 행동·개정·상태 판) 입력을 새로 시작한다. */
  formKey: string
  /** 결정할 개정의 요약(열 때 고정, lib/records revisionFacts). 개정 요약이 없으면 빈 목록. */
  facts: readonly Fact[]
  /** 맨 위 큰 숫자 칸(lib/revisions revisionGlance). 있으면 표는 칸과 겹치는 줄을 뺀다(restFacts). */
  glance?: readonly GlanceFact[]
  /** 제목 옆 판정 배지(그 개정의 판정). */
  verdict?: VerdictLevel | null
  checklist: readonly ChecklistItem[]
  /** 결재선 안내 한 줄(지금 단계·다음 단계·전결). 없으면 그리지 않는다. */
  note?: string | null
  busy: boolean
  serverError: string | null
  onOpenChange: (open: boolean) => void
  onSubmit: (reason: string, acknowledged: string[]) => void
}

export function DecisionDialog({
  action,
  revision,
  formKey,
  facts,
  glance = [],
  verdict = null,
  checklist,
  note = null,
  busy,
  serverError,
  onOpenChange,
  onSubmit,
}: Props) {
  const open = action !== null
  const returnFocus = useReturnFocus(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl" onCloseAutoFocus={returnFocus} data-testid="decision-dialog">
        {action && (
          <DecisionForm
            key={formKey}
            action={action}
            revision={revision}
            facts={facts}
            glance={glance}
            verdict={verdict}
            checklist={checklist}
            note={note}
            busy={busy}
            serverError={serverError}
            onSubmit={onSubmit}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function DecisionForm({
  action,
  revision,
  facts,
  glance = [],
  verdict = null,
  checklist,
  note,
  busy,
  serverError,
  onSubmit,
}: Omit<Props, 'action' | 'onOpenChange' | 'formKey'> & { action: EcnAction }) {
  const rows = glance.length > 0 ? restFacts(facts) : facts
  const [reason, setReason] = useState('')
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set())
  const [tried, setTried] = useState(false)
  const keys = CHECKED.includes(action) ? checklist.map((item) => item.key) : []
  const problem = decisionProblem(action, reason, keys, acknowledged)
  const toggle = (key: string) =>
    setAcknowledged((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  const submit = () => {
    setTried(true)
    if (problem === null) onSubmit(reason, [...acknowledged])
  }
  const needsReason = !CHECKED.includes(action) || keys.length > 0
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      className="space-y-4"
    >
      <DialogHeader>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <DialogTitle>
            개정 {revision} {ACTION_LABEL[action]}
          </DialogTitle>
          {verdict && <VerdictBadge level={verdict} />}
        </div>
        <DialogDescription>{DESCRIPTION[action]}</DialogDescription>
      </DialogHeader>
      {note && (
        <p className="rounded-sm border border-primary/30 px-3 py-2 text-sm font-medium" data-testid="decision-note">
          <SegmentText text={note} />
        </p>
      )}
      <GlanceTiles testId="decision-glance" tiles={glance} />
      {rows.length > 0 && (
        <dl className="divide-y divide-border rounded-sm border border-border text-sm" data-testid="decision-summary">
          {rows.map((fact) => (
            <div key={fact.id} className="flex gap-3 px-3 py-2">
              <dt className="w-28 shrink-0 text-foreground-secondary">{fact.label}</dt>
              <dd className={fact.warn ? 'min-w-0 text-warning' : 'min-w-0 tabular-nums'}>
                <SegmentText text={fact.value} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      {keys.length > 0 && (
        <fieldset className="space-y-2" data-testid="decision-checklist">
          <legend className="mb-1 text-sm font-semibold">확인 필요 항목 {keys.length}개 — 확인 후 체크</legend>
          {checklist.map((item) => (
            <label key={item.key} className="flex items-start gap-2 rounded-sm border border-border px-3 py-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
                checked={acknowledged.has(item.key)}
                onChange={() => toggle(item.key)}
              />
              <span>
                <span className="text-foreground-secondary">{item.source === 'import' ? '엑셀 ' : '분석 '}</span>
                {item.text}
              </span>
            </label>
          ))}
        </fieldset>
      )}
      <label className="block space-y-1.5 text-sm">
        <span className="font-semibold">사유{needsReason ? '' : '(선택)'}</span>
        <Textarea
          value={reason}
          maxLength={500}
          rows={3}
          onChange={(event) => setReason(event.target.value)}
          placeholder={
            action === 'settle'
              ? '예: 도면 개정만 있는 변경 — 담당자 처리'
              : action === 'approve'
                ? '예: 보강재 추가안으로 진행, 선주 통보는 내일'
                : '예: 발주 상태 확인 뒤 다시 상신'
          }
          data-testid="decision-reason"
        />
      </label>
      {((tried && problem) || serverError) && (
        <p role="alert" className="rounded-sm border border-danger/40 px-3 py-2 text-sm text-danger">
          {(tried && problem) || serverError}
        </p>
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            닫기
          </Button>
        </DialogClose>
        <Button type="submit" disabled={busy} variant={action === 'reject' ? 'destructive' : 'default'} data-testid="decision-submit">
          {busy ? `${ACTION_LABEL[action]}하는 중…` : ACTION_LABEL[action]}
        </Button>
      </DialogFooter>
    </form>
  )
}
