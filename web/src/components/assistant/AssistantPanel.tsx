// AI 비서 칸(DESIGN.md 6절): 대화 기록 + 입력창. 설계변경을 문장으로 적으면 비서가 되묻고,
// 분석하면 가운데 상세가 그 결과로 바뀌고 이 칸에는 설명·알림 초안이 남는다. 요청 JSON 편집은 개발용 보기로 바꿔 연다.
import { ArrowLeft, LoaderCircle } from 'lucide-react'
import { useLayoutEffect, useRef, type FormEvent, type ReactNode } from 'react'
import type { AssistantTurn } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { MAX_MESSAGE, isShown, isSubmitKey } from '@/lib/assistant'
import { ASSISTANT_INPUT_ID } from '@/lib/domIds'
import { cn } from '@/lib/utils'
import type { AssistantState } from '@/state/useAssistant'
import { useMailer } from '@/state/useMailer'
import { TurnView } from './TurnView'

/** 빈 대화에서 보여 줄 예시(데모 1·2 문장). 누르면 입력창에 채운다. */
const EXAMPLES = [
  '3번 탱크 횡격벽 7번 판 두께 15에서 17로 올려 주세요 (강도 보강)',
  '선주 요청으로 펌프룸 스트리핑 글로브 밸브 1번을 볼 밸브로 바꿔 주세요',
]

/** 빈 대화 아래 '쓰는 순서': 처음 쓰는 사람이 화면 전체의 흐름(고르기 → 바꿔 보기 → 결재 → 새 변경)을 한눈에. */
const GUIDE = [
  '목록에서 설계변경 선택 → 판정·총변경비용·결정 기한',
  "권고 대안·'할 일'(보류 적용·후행 설치)로 다시 계산 · 바뀐 점 비교",
  '결재 띠에서 검토 요청 → 결재선 파트장 → 팀장 → 본부장',
  "새 설계변경: 여기에 문장으로, 문서·변경 리스트는 '문서로 넣기'",
]

interface Props {
  assistant: AssistantState
  /** 화면 맥락(고른 설계변경의 호선·기준일)이 있어 물을 수 있는가. */
  ready: boolean
  shownAnalysisId: string | null
  compact: boolean
  onOpenTurn: (turn: AssistantTurn) => void
  onEntity: (turn: AssistantTurn, entityId: string) => (() => void) | undefined
  /** 개발용 요청 JSON 보기. 열려 있으면 대화 대신 보인다. */
  json: { open: boolean; onClose: () => void; editor: ReactNode }
  /** 대화 시작 안내 위의 한 줄(예: 실제 데이터 지도라 AI 외부 호출을 하지 않음). */
  note?: string | null
  /** 알림 초안을 Gmail로 열 수 있는가: 합성 데이터 지도일 때만(실데이터는 복사만). */
  webMail: boolean
}

export function AssistantPanel({
  assistant,
  ready,
  shownAnalysisId,
  compact,
  onOpenTurn,
  onEntity,
  json,
  note,
  webMail,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const mailer = useMailer(webMail)
  const { entries, latest, busy, error, draft: text, setDraft: setText } = assistant

  // 새 차례·보내는 중 표시가 생기면 기록 맨 아래로(바깥 뼈대는 움직이지 않게 scrollTop만)
  useLayoutEffect(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [entries.length, busy, error])

  if (json.open) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-2 py-1">
          <Button variant="ghost" size="sm" onClick={json.onClose}>
            <ArrowLeft aria-hidden />
            대화로 돌아가기
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{json.editor}</div>
      </div>
    )
  }

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (!ready || busy || !text.trim()) return
    assistant.send(text)
  }

  return (
    <div className="flex h-full flex-col">
      <div ref={scroller} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {entries.length === 0 && (
          <div className="space-y-3 text-sm">
            {note && (
              <p data-testid="assistant-note" className="rounded-md border border-warning/50 bg-warning/10 px-3 py-2">
                {note}
              </p>
            )}
            <p className="text-foreground-secondary">
              설계변경을 문장으로 입력 · 대상·값·사유가 있으면 바로 분석, 빠진 정보는 되물음
            </p>
            <div className="space-y-1.5">
              <p className="text-xs text-foreground-secondary">예시(누르면 입력창에)</p>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  disabled={!ready}
                  onClick={() => {
                    setText(example)
                    document.getElementById(ASSISTANT_INPUT_ID)?.focus()
                  }}
                  className="block w-full rounded-md border border-border px-3 py-2 text-left hover:bg-hover focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
                >
                  {example}
                </button>
              ))}
            </div>
            <section aria-labelledby="assistant-guide-title" className="rounded-md bg-muted px-3 py-3" data-testid="assistant-guide">
              <h3 id="assistant-guide-title" className="text-sm font-semibold">
                쓰는 순서
              </h3>
              <ol className="mt-2 space-y-2">
                {GUIDE.map((line, i) => (
                  <li key={line} className="flex gap-2.5 text-foreground-secondary">
                    <span
                      aria-hidden
                      className="flex size-5 shrink-0 items-center justify-center rounded-full bg-surface text-xs font-semibold text-primary tabular-nums"
                    >
                      {i + 1}
                    </span>
                    <span>{line}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-2.5 text-xs text-foreground-secondary">Ctrl+K: 설계변경·부재·발주 찾기</p>
            </section>
          </div>
        )}
        {entries.map((entry) => {
          if (entry.kind === 'notice') {
            return (
              <p key={entry.id} className="text-center text-xs text-foreground-secondary">
                {entry.text}
              </p>
            )
          }
          if (entry.kind !== 'turn') {
            const failed = entry.kind === 'said' && entry.failed
            return (
              <div key={entry.id} className="relative ml-8 rounded-md bg-muted px-3 py-2 text-sm">
                <span className="sr-only">나: </span>
                {entry.text}
                {failed && (
                  <span className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-danger">
                    보내기 실패
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={busy}
                      onClick={() => assistant.retry(entry.id)}
                      className={cn(compact && 'h-11 px-3')}
                    >
                      다시 보내기
                    </Button>
                  </span>
                )}
              </div>
            )
          }
          const { turn } = entry
          return (
            <TurnView
              key={entry.id}
              turn={turn}
              restated={turn.reason_recorded}
              live={turn === latest}
              opened={entry.opened}
              shown={isShown(turn, shownAnalysisId)}
              busy={busy}
              compact={compact}
              answerText={assistant.answerDraft(turn)}
              onAnswerText={(value) => assistant.setAnswerDraft(turn, value)}
              onAnswer={(question, reply) => assistant.answer(turn, question, reply)}
              onOpen={() => onOpenTurn(turn)}
              onEntity={(entityId) => onEntity(turn, entityId)}
              mailer={mailer}
            />
          )
        })}
        <div role="status" aria-live="polite">
          {busy && (
            <p className="flex items-center gap-2 text-sm text-foreground-secondary">
              <LoaderCircle aria-hidden className="size-4 animate-spin text-agent" />
              읽는 중…
            </p>
          )}
        </div>
        {error && (
          <div role="alert" className="space-y-2 rounded-md border border-danger/40 bg-danger/8 px-3 py-2 text-sm">
            <p className="font-semibold">{error.message}</p>
            {error.problems.length > 0 && (
              <ul className="list-disc pl-5 text-foreground-secondary">
                {error.problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
            {error.status === 409 && (
              <Button size="sm" variant="outline" onClick={assistant.reset}>
                새 대화로 시작
              </Button>
            )}
          </div>
        )}
      </div>
      <form onSubmit={submit} className="relative shrink-0 border-t border-border p-3">
        <label htmlFor={ASSISTANT_INPUT_ID} className="sr-only">
          설계변경 요청 문장
        </label>
        <Textarea
          id={ASSISTANT_INPUT_ID}
          value={text}
          rows={2}
          maxLength={MAX_MESSAGE}
          disabled={!ready}
          placeholder={ready ? '예: T31C 판 7번 두께 15에서 17로 (강도 보강)' : '목록에서 설계변경을 고르면 입력 가능'}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (isSubmitKey({ key: event.key, shiftKey: event.shiftKey, isComposing: event.nativeEvent.isComposing })) {
              submit(event)
            }
          }}
          className="max-h-40 min-h-16 resize-none rounded-sm"
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-xs text-foreground-secondary">Enter 보내기 · Shift+Enter 줄바꿈</span>
          <Button type="submit" disabled={!ready || busy || !text.trim()} className={cn(compact && 'h-11')}>
            보내기
          </Button>
        </div>
      </form>
    </div>
  )
}
