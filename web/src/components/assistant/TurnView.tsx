// 비서 차례 하나: 묻는 차례는 안내 · 이해한 변경 · 질문 카드(마지막 차례만), 분석한 차례는 판정 · 설명(근거 칩·수치)
// · 알림 초안 · 변경 사유(분석 뒤 질문). 상세에 보이는 분석이 아니면(다시 계산했거나 다른 설계변경을 골랐으면) 그 사실과
// '이 분석 열기'를 보인다. 같은 분석에 사유만 기록한 차례(restated)는 안내·요약만 짧게.
// 하루 외부 AI 사용 한도로 못 부른 호출이 있었던 차례(llm_limited)는 한 줄 안내 — 무엇이 빠졌는지는 단정하지 않는다.
import { Bot, Mail } from 'lucide-react'
import { useState } from 'react'
import type { AssistantTurn, Question } from '@/api/client'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { Button } from '@/components/ui/button'
import { subcontractNote } from '@/lib/assistant'
import type { Reply } from '@/state/useAssistant'
import type { Mailer } from '@/state/useMailer'
import { BlockText } from './BlockText'
import { MailDialog } from './MailDialog'
import { NotificationCard } from './NotificationCard'
import { QuestionCard } from './QuestionCard'

interface Props {
  turn: AssistantTurn
  /** 앞 분석과 같은 분석에 변경 사유만 기록한 차례. */
  restated: boolean
  /** 기록의 마지막 차례면 질문에 답할 수 있다. */
  live: boolean
  /** 도착했을 때 상세에 열었는가. */
  opened: boolean
  /** 지금 상세에 보이는 분석인가. */
  shown: boolean
  busy: boolean
  compact: boolean
  /** 첫 질문에 쓰던 답. */
  answerText: string
  onAnswerText: (text: string) => void
  onAnswer: (question: Question, reply: Reply) => void
  onOpen: () => void
  /** 근거 칩: 누를 수 있으면 동작, 그래프에 없는 엔터티면 undefined. */
  onEntity: (entityId: string) => (() => void) | undefined
  /** 알림 초안을 메일 도구로 여는 방식·보내는 사람. */
  mailer: Mailer
}

export function TurnView({
  turn,
  restated,
  live,
  opened,
  shown,
  busy,
  compact,
  answerText,
  onAnswerText,
  onAnswer,
  onOpen,
  onEntity,
  mailer,
}: Props) {
  const question = turn.questions[0]
  const reason = turn.follow_ups[0]
  const recorded = turn.request?.change.intent != null
  const [mailOpen, setMailOpen] = useState(false)
  const mailable = turn.notifications.filter((notification) => notification.email).length
  const subcontract = subcontractNote(turn.notifications)
  return (
    // data-turn-state·data-shown: 되묻는 차례인지, 상세에 지금 보이는 분석인지(시연 실행기가 분석이 열렸는지 가른다)
    <article
      aria-label={`비서 ${turn.turn}번째 답`}
      className="space-y-2"
      data-turn-state={restated ? 'restated' : turn.state}
      data-shown={shown || undefined}
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-agent">
        <Bot aria-hidden className="size-3.5" />
        비서
      </p>
      {turn.llm_limited && (
        <p className="text-xs text-foreground-secondary">
          오늘 AI 보조 사용 한도 도달 · 일부 보조 기능 사용 불가
        </p>
      )}
      {turn.state === 'asking' && <p>{turn.message}</p>}
      {turn.summary && (
        <p className="text-sm">
          <span className="text-foreground-secondary">이해한 변경 </span>
          {turn.summary}
        </p>
      )}
      {turn.state === 'asking' &&
        question &&
        (live ? (
          <QuestionCard
            key={question.question_id}
            question={question}
            remaining={turn.questions.length - 1}
            busy={busy}
            compact={compact}
            text={answerText}
            onText={onAnswerText}
            onAnswer={(reply) => onAnswer(question, reply)}
          />
        ) : (
          <p className="text-sm text-foreground-secondary">{question.prompt}</p>
        ))}
      {turn.state === 'analyzed' && restated && <p>{turn.message}</p>}
      {turn.state === 'analyzed' && turn.result && !restated && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge level={turn.result.verdict.level} />
            <Button variant="link" size="sm" className="h-7 px-1" data-open-turn onClick={onOpen}>
              {shown ? '상세 보기' : '이 분석 열기'}
            </Button>
          </div>
          {!shown && (
            <p className="text-sm text-warning">
              {opened
                ? '지난 분석 · 이후 조건 변경 또는 다른 설계변경 선택'
                : '보낸 뒤 화면 전환 — 상세 미표시'}
            </p>
          )}
          {turn.explanation && (
            <div className="space-y-1.5">
              {turn.explanation.blocks.map((block, index) => (
                <BlockText key={index} block={block} onEntity={onEntity} />
              ))}
            </div>
          )}
          {turn.notifications.length > 0 && (
            <section aria-label="알림 초안" className="space-y-2 pt-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-base font-semibold">메일 초안 {turn.notifications.length}건</h4>
                {mailable > 0 && (
                  <Button size="sm" variant="outline" onClick={() => setMailOpen(true)} data-testid="mail-dialog-open">
                    <Mail aria-hidden />
                    메일 보내기…
                  </Button>
                )}
              </div>
              {subcontract && (
                <p className="text-xs text-foreground-secondary" data-testid="subcontract-note">
                  {subcontract}
                </p>
              )}
              <ul className="space-y-3">
                {turn.notifications.map((notification) => (
                  <NotificationCard
                    key={`${notification.target}-${notification.recipient_id}`}
                    notification={notification}
                    stale={!shown}
                    mailer={mailer}
                  />
                ))}
              </ul>
              <MailDialog
                open={mailOpen}
                onOpenChange={setMailOpen}
                notifications={turn.notifications}
                mailer={mailer}
              />
            </section>
          )}
        </>
      )}
      {reason && live && (
        <ReasonCard
          key={reason.question_id}
          question={reason}
          recorded={recorded}
          busy={busy}
          compact={compact}
          onAnswer={(reply) => onAnswer(reason, reply)}
        />
      )}
    </article>
  )
}

/** 분석 뒤 변경 사유: 사유가 없으면 고르기를 펼치고, 있으면 '변경 사유 … · 바꾸기'로 접어 둔다. */
function ReasonCard({
  question,
  recorded,
  busy,
  compact,
  onAnswer,
}: {
  question: Question
  recorded: boolean
  busy: boolean
  compact: boolean
  onAnswer: (reply: Reply) => void
}) {
  const [open, setOpen] = useState(!recorded)
  if (!open) {
    return (
      <p className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="text-foreground-secondary">변경 사유</span>
        <span className="font-medium">{question.proposal}</span>
        <Button variant="link" size="sm" className="h-7 px-1" disabled={busy} onClick={() => setOpen(true)}>
          바꾸기
        </Button>
      </p>
    )
  }
  return (
    <QuestionCard
      question={question}
      remaining={0}
      busy={busy}
      compact={compact}
      text=""
      onText={() => undefined}
      onAnswer={onAnswer}
    />
  )
}
