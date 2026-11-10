// 결과 알림(상세 맨 위): 마지막 요청의 오류(연결·서버 오류면 '다시 시도') · 아래가 이전 결과라는 안내(다시 계산 중·거절·
// 초안 수정 뒤 — 고친 초안은 '분석 보기').
import { CircleAlert, LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { AnalysisSession, ResultState } from '@/state/useAnalysisSession'

const NOTICE: Record<Exclude<ResultState, 'none' | 'current'>, string> = {
  running: '새 조건으로 다시 계산 중 · 아래는 이전 결과',
  failed: '요청 거절 · 아래는 이전 결과',
  edited: '고친 요청 미계산 · 아래는 이전 결과',
}

export function ResultNotice({ session }: { session: AnalysisSession }) {
  const { state, error } = session
  // 연결 끊김·서버 오류·혼잡은 같은 요청을 다시 보내면 될 수 있다(요청이 틀린 422는 고쳐야 해서 단추 없음)
  const retryable = error !== null && (error.status === 0 || error.status === 429 || error.status >= 500)
  return (
    <>
      {error && (
        <div role="alert" className="mx-4 mt-3 rounded-md border border-danger/40 bg-danger/8 px-3 py-2 text-sm">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="min-w-0 flex-1 font-semibold">{error.message}</p>
            {retryable && session.draftValid && (
              <Button size="sm" variant="outline" onClick={session.runDraft} disabled={session.busy}>
                다시 시도
              </Button>
            )}
          </div>
          {error.problems.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-foreground-secondary">
              {error.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div role="status" aria-live="polite">
        {state !== 'none' && state !== 'current' && (
          <div className="flex min-h-10 items-center gap-2 border-b border-border bg-warning/8 px-4 py-1.5 text-sm">
            {state === 'running' ? (
              <LoaderCircle aria-hidden className="size-4 shrink-0 animate-spin text-warning" />
            ) : (
              <CircleAlert aria-hidden className="size-4 shrink-0 text-warning" />
            )}
            <span className="min-w-0 flex-1">{NOTICE[state]}</span>
            {state === 'edited' && session.draftValid && (
              <Button size="sm" onClick={session.runDraft}>
                분석 보기
              </Button>
            )}
          </div>
        )}
      </div>
    </>
  )
}
