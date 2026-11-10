// '고치기' 대화상자(DESIGN.md 13절 대화상자 규칙): 발주는 오늘 단계 + 납기(입고까지 일수), 공정은 실제 착수·완료일 또는
// 아직 미착수. 오류는 단추 위, 왼쪽 '닫기'. 값은 오늘 날짜로 지도에 남는다(정정이 아니라 새 확인).
import { useState } from 'react'
import type { StateBasis, StatusUpdate } from '@/api/client'
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
import { Input } from '@/components/ui/input'
import { useReturnFocus } from '@/lib/focus'
import { formatDay } from '@/lib/format'
import { PO_STATUS_NAMES } from '@/lib/labels'
import { PO_STEPS, activityFixUpdate, poFixUpdate, stateText, type PoStep } from '@/lib/stateBasis'

interface Props {
  row: StateBasis | null
  today: string
  busy: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (update: StatusUpdate) => Promise<string | null>
}

export function StateFixDialog({ row, today, busy, onOpenChange, onSubmit }: Props) {
  const open = row !== null
  const returnFocus = useReturnFocus(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" onCloseAutoFocus={returnFocus} data-testid="state-fix-dialog">
        {row && <FixForm key={`${row.entity_type}-${row.entity_id}`} row={row} today={today} busy={busy} onSubmit={onSubmit} />}
      </DialogContent>
    </Dialog>
  )
}

function FixForm({ row, today, busy, onSubmit }: Omit<Props, 'row' | 'onOpenChange'> & { row: StateBasis }) {
  const initial = (PO_STEPS as readonly string[]).includes(row.po_status ?? '') ? (row.po_status as PoStep) : 'ordered'
  const [status, setStatus] = useState<PoStep>(initial)
  const [lead, setLead] = useState('')
  const [started, setStarted] = useState('')
  const [finished, setFinished] = useState('')
  const [notStarted, setNotStarted] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const isPo = row.entity_type === 'po'

  const submit = async () => {
    const update = isPo
      ? poFixUpdate(row, { status, leadTimeDays: lead }, today)
      : activityFixUpdate(row, { started, finished, notStarted }, today)
    if (typeof update === 'string') {
      setProblem(update)
      return
    }
    setProblem(await onSubmit(update))
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}
      className="space-y-4"
    >
      <DialogHeader>
        <DialogTitle>{row.label} 상태 고치기</DialogTitle>
        <DialogDescription>
          지금 보이는 상태: {stateText(row)} · 고친 값 → 오늘({formatDay(today)}) 확인으로 지도에 저장
        </DialogDescription>
      </DialogHeader>
      {isPo ? (
        <div className="space-y-3">
          <label className="block space-y-1.5 text-sm">
            <span className="font-semibold">오늘 단계</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value as PoStep)}
              className="h-9 w-full rounded-sm border border-border bg-background px-2"
              data-testid="fix-status"
            >
              {PO_STEPS.map((step) => (
                <option key={step} value={step}>
                  {PO_STATUS_NAMES[step]}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1.5 text-sm">
            <span className="font-semibold">입고까지 일수(발주 뒤, 납기가 바뀌었을 때만)</span>
            <Input
              inputMode="numeric"
              value={lead}
              onChange={(event) => setLead(event.target.value)}
              placeholder="예: 47"
              data-testid="fix-lead"
            />
          </label>
          <p className="text-sm text-foreground-secondary">가공 = 그 자재를 쓰는 공정의 착수로 확인</p>
        </div>
      ) : (
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-[var(--primary)]"
              checked={notStarted}
              onChange={(event) => setNotStarted(event.target.checked)}
              data-testid="fix-not-started"
            />
            아직 착수 전
          </label>
          {!notStarted && (
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-1.5 text-sm">
                <span className="font-semibold">실제 착수일</span>
                <Input
                  type="date"
                  max={today}
                  value={started || row.actual_start || ''}
                  disabled={!!row.actual_start}
                  onChange={(event) => setStarted(event.target.value)}
                  data-testid="fix-started"
                />
              </label>
              <label className="block space-y-1.5 text-sm">
                <span className="font-semibold">실제 완료일(선택)</span>
                <Input
                  type="date"
                  max={today}
                  value={finished}
                  onChange={(event) => setFinished(event.target.value)}
                  data-testid="fix-finished"
                />
              </label>
            </div>
          )}
        </div>
      )}
      {problem && (
        <p role="alert" className="rounded-sm border border-danger/40 px-3 py-2 text-sm text-danger">
          {problem}
        </p>
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            닫기
          </Button>
        </DialogClose>
        <Button type="submit" disabled={busy} data-testid="fix-submit">
          {busy ? '저장 중…' : '오늘 확인으로 남기기'}
        </Button>
      </DialogFooter>
    </form>
  )
}
