// 되묻기 카드(DESIGN.md 6절): 확인·고르기는 선택지 단추('해당 없음'·'고치기'는 뒤로), 다시 설명은 글 입력,
// 값 확인은 제안 값 단추 + 직접 입력. 왜 묻는지와 문장의 어느 조각인지 함께 보인다.
import { useId, type FormEvent } from 'react'
import type { Question } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { YES, cardMode, isSubmitKey, splitOptions } from '@/lib/assistant'
import { cn } from '@/lib/utils'
import type { Reply } from '@/state/useAssistant'

interface Props {
  question: Question
  /** 이 질문 다음에 남은 질문 수. */
  remaining: number
  busy: boolean
  /** 현장 태블릿: 터치 높이 44px. */
  compact: boolean
  /** 쓰던 답(칸이 닫혀도 남도록 비서 상태에 둔다). */
  text: string
  onText: (text: string) => void
  onAnswer: (reply: Reply) => void
}

const PLACEHOLDER = { text: '다시 입력', value: '직접 입력(예: 17mm)', choose: '' } as const

export function QuestionCard({ question, remaining, busy, compact, text, onText, onAnswer }: Props) {
  const inputId = useId()
  const mode = cardMode(question)
  const { main, none } = splitOptions(question)
  const height = compact ? 'h-11' : 'h-9'
  // 확인 두 갈래(제안 하나 + 해당 없음)는 단추를 나란히, 고르기 목록은 위아래로
  const stacked = mode === 'choose' && main.length > 1

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (text.trim()) onAnswer({ text })
  }

  return (
    <div className="relative space-y-2.5 rounded-md border border-agent/40 bg-agent/5 p-3">
      <p className="font-medium">{question.prompt}</p>
      {question.mention && (
        <p className="text-sm text-foreground-secondary">
          문장에서 <span className="text-foreground">“{question.mention.text}”</span>
        </p>
      )}
      {question.proposal && mode !== 'value' && <p className="font-semibold">{question.proposal}</p>}
      {question.reason && <p className="text-sm text-foreground-secondary">{question.reason}</p>}

      {main.length > 0 && (
        <div className={cn('flex gap-2', stacked ? 'flex-col' : 'flex-wrap')}>
          {main.map((option) => (
            <Button
              key={option.option_id}
              variant={option.option_id === YES || (!stacked && main.length === 1) ? 'default' : 'outline'}
              disabled={busy}
              onClick={() => onAnswer({ optionId: option.option_id })}
              className={cn(
                height,
                stacked && 'h-auto justify-start py-1.5 text-left whitespace-normal',
                stacked && (compact ? 'min-h-11' : 'min-h-9'),
              )}
            >
              <span className="min-w-0">
                {option.label}
                {option.detail && (
                  <span className="ml-2 text-xs font-normal text-foreground-secondary">{option.detail}</span>
                )}
              </span>
            </Button>
          ))}
        </div>
      )}

      {mode !== 'choose' && (
        <form onSubmit={submit} className="flex gap-2">
          <label htmlFor={inputId} className="sr-only">
            {question.prompt}
          </label>
          <Input
            id={inputId}
            value={text}
            maxLength={300}
            placeholder={PLACEHOLDER[mode]}
            disabled={busy}
            onChange={(event) => onText(event.target.value)}
            onKeyDown={(event) => {
              if (isSubmitKey({ key: event.key, shiftKey: event.shiftKey, isComposing: event.nativeEvent.isComposing })) {
                submit(event)
              }
            }}
            className={cn('min-w-0 flex-1 rounded-sm', height)}
          />
          <Button type="submit" variant="outline" disabled={busy || !text.trim()} className={height}>
            보내기
          </Button>
        </form>
      )}

      {none && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => onAnswer({ optionId: none.option_id })}
          className={cn('text-foreground-secondary', compact && 'h-11')}
        >
          {none.label}
        </Button>
      )}
      {remaining > 0 && <p className="text-xs text-foreground-secondary">이 다음에 확인할 것 {remaining}개</p>}
    </div>
  )
}
