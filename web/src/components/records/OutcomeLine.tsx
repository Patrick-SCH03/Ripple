// 실적(실행·종료한 설계변경, docs/records.md(기록·결재) 11절): 결재 띠 아래 한 줄 — 실제 비용·출구 지연과 예측 대비 오차.
// 담당자는 '실적 입력…'으로 넣고 고친다(고치면 새 줄이 쌓이고 마지막 값이 보임). 예측은 승인한 개정의 총변경비용.
import { useEffect, useState } from 'react'
import { ApiError, api, type Amount, type OutcomeEntry } from '@/api/client'
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
import { formatKstTime, whoLabel } from '@/lib/account'
import { useReturnFocus } from '@/lib/focus'
import { errorText, manwonToWon } from '@/lib/manage'
import { formatMoney, formatRange } from '@/lib/money'

// 서버 계약(ripple/contracts/outcomes.py)과 같은 상한 — 자릿수 실수를 입력 칸에서 바로 알린다
const COST_MAX_WON = 10 ** 12
const DELAY_MAX_DAYS = 3650

interface Props {
  ecnId: string
  /** 상태 판(바뀌면 다시 읽음). */
  version: number
  /** 승인한 개정의 총변경비용(예측). 모르면 null. */
  predicted: Amount | null
  canEnter: boolean
}

export function OutcomeLine({ ecnId, version, predicted, canEnter }: Props) {
  const [entry, setEntry] = useState<OutcomeEntry | null>(null)
  // 마지막으로 읽은 ECN: 상태 판이 바뀌어 다시 읽는 동안에도 줄과 열린 대화상자(쓰던 값)를 그대로 둔다
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let live = true
    api.outcome(ecnId).then(
      (found) => {
        if (!live) return
        setEntry(found)
        setLoadedFor(ecnId)
      },
      (caught: unknown) => {
        if (!live) return
        // 404 = 아직 없음. 그 밖 실패는 보조 정보라 조용히 — 이 ECN에서 읽은 값이 있으면 그대로 둔다
        const missing = caught instanceof ApiError && caught.status === 404
        setEntry((prev) => (!missing && prev?.ecn_id === ecnId ? prev : null))
        setLoadedFor(ecnId)
      },
    )
    return () => {
      live = false
    }
  }, [ecnId, version])
  if (loadedFor !== ecnId) return null
  const rate = entry && predicted && predicted.value > 0 ? (entry.cost_krw - predicted.value) / predicted.value : null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" data-testid="outcome-line">
      {entry ? (
        <p className="min-w-0 flex-1">
          <span className="font-medium">실적</span> {formatMoney(entry.cost_krw)}
          {rate !== null && <span className="text-foreground-secondary"> (예측 대비 {errorText(rate)})</span>}
          {entry.exit_delay_days != null && <> · 구역 출구 {entry.exit_delay_days}일 지연</>}
          <span className="text-foreground-secondary">
            {' · '}
            {whoLabel(entry.entered_by)} · {formatKstTime(entry.entered_at)}
          </span>
        </p>
      ) : (
        <p className="min-w-0 flex-1 text-foreground-secondary">
          {canEnter ? '실행 후 실제 비용·지연 입력 → 성과 탭 ‘예측 대비 실적’' : '실적 미입력'}
        </p>
      )}
      {canEnter && (
        <Button size="sm" variant="outline" onClick={() => setOpen(true)} data-testid="outcome-open">
          {entry ? '실적 고치기…' : '실적 입력…'}
        </Button>
      )}
      <OutcomeDialog
        open={open}
        ecnId={ecnId}
        entry={entry}
        predicted={predicted}
        onOpenChange={setOpen}
        onSaved={(saved) => {
          setEntry(saved)
          setOpen(false)
        }}
      />
    </div>
  )
}

function OutcomeDialog({
  open,
  ecnId,
  entry,
  predicted,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  ecnId: string
  entry: OutcomeEntry | null
  predicted: Amount | null
  onOpenChange: (open: boolean) => void
  onSaved: (entry: OutcomeEntry) => void
}) {
  const returnFocus = useReturnFocus(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" onCloseAutoFocus={returnFocus} data-testid="outcome-dialog">
        {open && <OutcomeForm ecnId={ecnId} entry={entry} predicted={predicted} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  )
}

function OutcomeForm({
  ecnId,
  entry,
  predicted,
  onSaved,
}: {
  ecnId: string
  entry: OutcomeEntry | null
  predicted: Amount | null
  onSaved: (entry: OutcomeEntry) => void
}) {
  const [cost, setCost] = useState(entry ? String(entry.cost_krw / 10_000) : '')
  const [delay, setDelay] = useState(entry?.exit_delay_days != null ? String(entry.exit_delay_days) : '')
  const [note, setNote] = useState(entry?.note ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    const won = manwonToWon(cost)
    const days = delay.trim() === '' ? null : Number(delay)
    if (won === null) return setProblem('실제 비용은 만원 단위 숫자(예: 3,100)')
    if (won > COST_MAX_WON) return setProblem('실제 비용이 너무 큼 · 만원 단위·자릿수 확인')
    if (days !== null && (!Number.isInteger(days) || days < 0)) return setProblem('출구 지연은 0 이상의 정수(일)')
    if (days !== null && days > DELAY_MAX_DAYS) return setProblem(`출구 지연은 ${DELAY_MAX_DAYS}일 이하`)
    setBusy(true)
    setProblem(null)
    try {
      onSaved(await api.putOutcome(ecnId, { cost_krw: won, exit_delay_days: days, note }))
    } catch (caught) {
      setProblem(caught instanceof ApiError ? caught.message : '실적 저장 실패')
    } finally {
      setBusy(false)
    }
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
        <DialogTitle>{entry ? '실적 고치기' : '실적 입력'}</DialogTitle>
        <DialogDescription>
          실행 후 실제 변경 비용·구역 출구 지연 · 고쳐도 이전 값은 기록에 남음
          {predicted && ` 승인한 예측: ${formatMoney(predicted.value)}(${formatRange(predicted.low, predicted.high)}).`}
        </DialogDescription>
      </DialogHeader>
      <label className="block space-y-1.5 text-sm">
        <span className="font-semibold">실제 비용(만원)</span>
        <Input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="예: 3,100" data-testid="outcome-cost" />
      </label>
      <label className="block space-y-1.5 text-sm">
        <span className="font-semibold">구역 출구 지연(일, 모르면 비움)</span>
        <Input inputMode="numeric" value={delay} onChange={(e) => setDelay(e.target.value)} placeholder="예: 9" />
      </label>
      <label className="block space-y-1.5 text-sm">
        <span className="font-semibold">메모(선택)</span>
        <Input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="예: 협력사 재가공비 포함" />
      </label>
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
        <Button type="submit" disabled={busy} data-testid="outcome-submit">
          {busy ? '저장 중…' : '실적 남기기'}
        </Button>
      </DialogFooter>
    </form>
  )
}
