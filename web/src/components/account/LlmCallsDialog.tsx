// AI 호출 기록(관리자 사용자 메뉴, docs/input.md(외부 AI) 7절): 지금 외부 AI를 부를 수 있는지와 서버가 켜진 뒤 최근 호출
// (시각·작업·모델·결과·걸린 시간). 문장·응답·키는 서버가 남기지 않는다. 열 때마다 새로 읽고 '새로 고침'으로 다시 읽는다.
import { useState } from 'react'
import { api } from '@/api/client'
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
import { useReturnFocus } from '@/lib/focus'
import { useFetched } from '@/state/useFetched'
import { callSummary, callTime, latencyLabel, outcomeLabel, taskLabel } from '@/lib/llmCalls'

export function LlmCallsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const returnFocus = useReturnFocus(open)
  const [round, setRound] = useState(0)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl" onCloseAutoFocus={returnFocus} data-testid="llm-calls-dialog">
        <DialogHeader>
          <DialogTitle>AI 호출 기록</DialogTitle>
          <DialogDescription>
            AI 비서의 외부 AI(Claude) 호출 기록 · 문장·응답 저장 없음 · 서버 재시작 시 초기화
          </DialogDescription>
        </DialogHeader>
        {open && <CallList key={round} />}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
          <Button onClick={() => setRound((n) => n + 1)} data-testid="llm-calls-refresh">
            새로 고침
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const loadCalls = () => api.llmCalls()

function CallList() {
  const { data, error } = useFetched(loadCalls)
  if (error) return <p className="rounded-sm border border-danger/40 px-3 py-2 text-sm text-danger">{error}</p>
  if (!data) return <p className="text-sm text-foreground-secondary">불러오는 중…</p>
  const summary = callSummary(data.calls)
  return (
    <div className="min-w-0 space-y-3 text-sm" role="status" aria-live="polite">
      <p
        className={
          data.external
            ? 'rounded-sm border border-success/50 px-3 py-2 text-success'
            : 'rounded-sm border border-border px-3 py-2 text-foreground-secondary'
        }
        data-testid="llm-calls-state"
      >
        {data.external
          ? '외부 AI 사용 가능'
          : '외부 AI 미사용(키 없음 또는 실제 데이터 지도 — 서버 규칙으로 해석·설명)'}
      </p>
      {summary ? (
        <>
          <p className="text-foreground-secondary">{summary}</p>
          <div className="max-h-80 overflow-auto rounded-sm border border-border">
            <table className="w-full min-w-[34rem] text-left text-xs">
              <thead className="sticky top-0 bg-surface text-foreground-secondary">
                <tr>
                  <th className="px-2 py-1.5 font-medium">시각(KST)</th>
                  <th className="px-2 py-1.5 font-medium">작업</th>
                  <th className="px-2 py-1.5 font-medium">모델</th>
                  <th className="px-2 py-1.5 font-medium">결과</th>
                  <th className="px-2 py-1.5 text-right font-medium">걸린 시간</th>
                </tr>
              </thead>
              <tbody>
                {data.calls.map((call, index) => (
                  <tr key={`${call.at}-${index}`} className="border-t border-border" data-testid="llm-call-row">
                    <td className="px-2 py-1.5 tabular-nums whitespace-nowrap">{callTime(call.at)}</td>
                    <td className="px-2 py-1.5 whitespace-nowrap">{taskLabel(call.task)}</td>
                    <td className="px-2 py-1.5 font-mono whitespace-nowrap">{call.model}</td>
                    <td className={`px-2 py-1.5 whitespace-nowrap ${call.ok ? '' : 'text-danger'}`}>
                      {outcomeLabel(call)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums whitespace-nowrap">
                      {latencyLabel(call.latency_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="text-foreground-secondary" data-testid="llm-calls-empty">
          서버 시작 뒤 외부 AI 호출 없음
        </p>
      )}
    </div>
  )
}
