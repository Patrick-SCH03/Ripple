// 현장 통보문 언어 고르기(계약 1.36.0, docs/records.md(통보) 6절): 작업반 메일 카드의 본문 위 한 줄.
// 한국어(기본) · 번역 언어 단추(서버가 준 순서·그 언어 이름). 누르기만 하면 바뀌고,
// 카드의 본문·복사·Gmail 열기가 고른 보기를 쓴다. 번역을 고르면 용어집 밖 원문 유지 말을 띄운다(11-03 사용자 결정: 초안 표기 없음).
import { Languages } from 'lucide-react'
import type { EmailDraft } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  KOREAN,
  type MailView,
  languageOptions,
  translationOf,
  untranslatedLine,
} from '@/lib/mailView'

interface Props {
  email: EmailDraft
  view: MailView
  onView: (view: MailView) => void
  /** 용어집 미등록 원문 유지 줄(접힌 카드에서는 빼고 펼친 보기에서). */
  showMissing?: boolean
}

export function MailLanguageBar({ email, view, onView, showMissing = true }: Props) {
  const options = languageOptions(email)
  if (!options.length) return null
  const translation = translationOf(email, view.language)
  const missing = untranslatedLine(translation)
  return (
    <div className="space-y-1" data-testid="mail-language">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="flex items-center gap-1 text-xs text-foreground-secondary">
          <Languages aria-hidden className="size-3.5" />
          통보문 언어
        </span>
        <div role="group" aria-label="통보문 언어" className="flex flex-wrap gap-1">
          {options.map((option) => {
            const selected = option.code === (translation ? view.language : KOREAN)
            return (
              <Button
                key={option.code}
                size="xs"
                variant={selected ? 'secondary' : 'outline'}
                aria-pressed={selected}
                lang={option.code}
                onClick={() => onView({ language: option.code })}
                data-testid={`mail-lang-${option.code}`}
              >
                {option.label}
              </Button>
            )
          })}
        </div>
      </div>
      {missing && showMissing && <p className="text-xs text-foreground-secondary">{missing}</p>}
    </div>
  )
}
