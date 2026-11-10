// 현장 통보문 번역 보기(계약 1.36.0, docs/records.md(통보) 6절): 작업반 메일을 한국어 또는 번역 하나로(번역에 한국어 원문을 덧붙이지 않음 — 11-04 사용자 결정).
// 번역은 서버가 고정 문장·용어집으로 만든 것(외부 AI 없음)을 그대로 이어 붙이기만 한다 — 화면은 번역하지 않는다.
// 복사·Gmail 열기는 고른 보기의 제목·본문을 쓴다(mail.ts MailText).
import type { EmailDraft, MailTranslation } from '@/api/client'
import { type MailText, bodyText } from './mail'

/** 한국어 원문 보기(기본). */
export const KOREAN = 'ko'

/** 고른 언어. */
export interface MailView {
  language: string
}

export const DEFAULT_VIEW: MailView = { language: KOREAN }

export interface LanguageOption {
  code: string
  label: string
}

/** 언어 단추: 번역이 있으면 한국어 + 번역 언어(서버 순서·그 언어로 쓴 이름), 없으면 빈 목록(단추 없음). */
export function languageOptions(email: Pick<EmailDraft, 'translations'>): LanguageOption[] {
  const translations = email.translations ?? []
  if (!translations.length) return []
  return [{ code: KOREAN, label: '한국어' }, ...translations.map((t) => ({ code: t.language, label: t.language_name }))]
}

export function translationOf(email: Pick<EmailDraft, 'translations'>, language: string): MailTranslation | null {
  if (language === KOREAN) return null
  return (email.translations ?? []).find((t) => t.language === language) ?? null
}

/** 번역 본문: 표기(그 언어 · 한국어) · 인사말 · 관련 건 · 문단(블록마다 한 줄) · 맺음 · 서명. */
export function translatedBody(translation: MailTranslation, signer: string): string {
  const paragraphs = translation.paragraphs
    .map((paragraph) => paragraph.blocks.map((block) => block.text).join('\n'))
    .join('\n\n')
  const signature = [
    translation.sign_off,
    signer.trim() || '담당자',
    ...(translation.sender ? [translation.sender] : []),
  ].join('\n')
  return [
    translation.notice,
    translation.notice_ko,
    '',
    translation.salutation,
    '',
    `${translation.reference_label}: ${translation.reference}`,
    '',
    paragraphs,
    '',
    signature,
  ].join('\n')
}

/** 고른 보기의 제목·본문. 한국어(또는 없는 언어)면 원문 그대로, 번역이면 번역만. */
export function viewText(email: EmailDraft, signer: string, view: MailView): MailText {
  const translation = translationOf(email, view.language)
  if (!translation) return { subject: email.subject, body: bodyText(email, signer) }
  return { subject: translation.subject, body: translatedBody(translation, signer) }
}

/** 용어집에 없어 한국어로 둔 말 한 줄(없으면 null) — 보내기 전에 현장 통역이 볼 곳. */
export function untranslatedLine(translation: MailTranslation | null): string | null {
  if (!translation?.untranslated.length) return null
  return `용어집 미등록 · 원문 유지: ${translation.untranslated.join(', ')}`
}
