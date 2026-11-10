// 확인표 '비서로'(docs/input.md(문서 접수)): 이 항목 조각만 비서에게 넘겨 되묻기로 초안을 마친다(분석하지 않음, draft_only).
// 표에서 이미 정한 연산·대상은 씨앗(seed)으로 넘겨 다시 묻지 않는다. 비서가 초안을 마치면(drafted) 확인표로 돌려보내고,
// 서버는 확정할 때 그 초안을 다시 검증한다. 패널을 닫거나 다시 넘기면(새 판) 기다리던 응답은 버린다.
import { LoaderCircle, MessagesSquare } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  api,
  type Answer,
  type AssistantTurn,
  type ChangeDraft,
  type IntakeItem,
  type TurnContext,
} from '@/api/client'
import { QuestionCard } from '@/components/assistant/QuestionCard'
import { Button } from '@/components/ui/button'
import { seedFor } from '@/lib/intake'
import type { Reply } from '@/state/useAssistant'

interface Props {
  item: IntakeItem
  context: TurnContext
  /** 표에서 고른 대상(있으면 씨앗으로). */
  partIds: string[] | null
  compact: boolean
  onDrafted: (draft: ChangeDraft, summary: string | null) => void
}

/** 다시 넘기기 = 새 판(새 대화). */
export function HandoffPanel(props: Props) {
  const [round, setRound] = useState(0)
  return <HandoffRound key={round} {...props} onRetry={() => setRound((n) => n + 1)} />
}

function failureText(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : '비서 연결 실패'
}

const ANALYZED = '비서가 초안 대신 분석 결과를 반환 · 다시 넘기기'

function HandoffRound({ item, context, partIds, compact, onDrafted, onRetry }: Props & { onRetry: () => void }) {
  // 넘긴 그때의 맥락·조각·씨앗으로 대화를 한 번 연다(화면이 다시 그려져도 다시 보내지 않게)
  const [start] = useState(() => ({ context, message: item.source.text, seed: seedFor(item, partIds) }))
  const [turn, setTurn] = useState<AssistantTurn | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const pending = useRef<AbortController | null>(null)
  const drafted = useRef(onDrafted)
  useEffect(() => {
    drafted.current = onDrafted
  })
  // 패널이 닫히면(다른 결정을 골랐거나 확인표를 닫음) 기다리던 답 차례도 버린다 — 늦은 초안이 사람이 고른 결정을
  // 되돌리지 않게
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
      pending.current?.abort()
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    pending.current = controller
    api
      .assistantTurn({ context: start.context, message: start.message, draft_only: true, seed: start.seed }, controller.signal)
      .then(
        (next) => {
          if (controller.signal.aborted) return
          setTurn(next)
          setBusy(false)
          if (next.state === 'drafted' && next.draft) drafted.current(next.draft, next.summary ?? null)
          else if (next.state === 'analyzed') setError(ANALYZED)
        },
        (caught: unknown) => {
          if (controller.signal.aborted) return
          setBusy(false)
          setError(failureText(caught))
        },
      )
    return () => controller.abort()
  }, [start])

  const question = turn?.state === 'asking' ? (turn.questions[0] ?? null) : null
  const answer = async (reply: Reply) => {
    if (!turn || !question) return
    const body: Answer =
      'optionId' in reply
        ? { question_id: question.question_id, option_id: reply.optionId }
        : { question_id: question.question_id, text: reply.text }
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    setBusy(true)
    setError(null)
    try {
      const next = await api.assistantTurn(
        { context: start.context, conversation_id: turn.conversation_id, answer: body, draft_only: false },
        controller.signal,
      )
      if (controller.signal.aborted || !live.current) return
      setTurn(next)
      setText('')
      setBusy(false)
      if (next.state === 'drafted' && next.draft) drafted.current(next.draft, next.summary ?? null)
      else if (next.state === 'analyzed') setError(ANALYZED)
    } catch (caught) {
      if (controller.signal.aborted) return
      setBusy(false)
      setError(failureText(caught))
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-agent/40 bg-agent/5 p-3" data-testid="intake-handoff">
      <p className="flex items-center gap-1.5 text-xs font-medium text-agent">
        <MessagesSquare aria-hidden className="size-3.5" />
        AI 비서가 이 항목만 다시 질문 — 끝나면 확인표로
      </p>
      {busy && (
        <p role="status" className="flex items-center gap-1.5 text-sm text-foreground-secondary">
          <LoaderCircle aria-hidden className="size-4 animate-spin text-agent" />
          비서가 읽는 중…
        </p>
      )}
      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-danger">
          {error}
          <Button variant="outline" size="sm" onClick={onRetry} className={compact ? 'h-11' : undefined}>
            다시 넘기기
          </Button>
        </div>
      )}
      {turn && turn.state === 'asking' && !question && !busy && <p className="text-sm">{turn.message}</p>}
      {question && (
        <QuestionCard
          question={question}
          remaining={Math.max(0, (turn?.questions.length ?? 1) - 1)}
          busy={busy}
          compact={compact}
          text={text}
          onText={setText}
          onAnswer={(reply) => void answer(reply)}
        />
      )}
      {turn?.state === 'drafted' && turn.draft && (
        <div className="text-sm" data-testid="intake-handoff-done">
          <p className="font-medium">{turn.message}</p>
          {turn.summary && <p className="text-foreground-secondary">{turn.summary}</p>}
        </div>
      )}
    </div>
  )
}
