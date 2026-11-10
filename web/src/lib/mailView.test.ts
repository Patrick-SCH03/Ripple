// 현장 통보문 번역 보기(1.36.0): 언어 단추·고른 보기의 제목·본문·원문 유지 줄.
import { describe, expect, it } from 'vitest'
import type { EmailDraft, MailTranslation, RenderedText } from '@/api/client'
import { bodyText } from './mail'
import {
  DEFAULT_VIEW,
  KOREAN,
  languageOptions,
  translatedBody,
  translationOf,
  untranslatedLine,
  viewText,
} from './mailView'

const paragraph = (...lines: string[]): RenderedText => ({
  source: 'template',
  blocks: lines.map((text) => ({ kind: 'text', text, template_id: 'mail.x', entity_ids: [], parts: [] })),
})

const english: MailTranslation = {
  language: 'en',
  language_name: 'English',
  notice: 'This is a draft translation.',
  notice_ko: '아래 번역은 초안입니다.',
  subject: '[Design change review] S-001 ECN-D-0119 – advance notice of work change',
  salutation: 'Dear Foreman of 해송 work crew (해송 작업반),',
  reference_label: 'Reference',
  reference: 'Hull S-001 · ECN-D-0119 [Korean] B31P 판 두께 변경',
  paragraphs: [paragraph('■ Affected work stages', '- B31P pre-outfitting (B31P 선행의장)'), paragraph('- Decision deadline: 2026-11-12')],
  sign_off: 'Best regards,',
  sender: '가람조선 design team (가람조선 설계팀)',
  untranslated: ['해송', '가람조선'],
}
const vietnamese: MailTranslation = { ...english, language: 'vi', language_name: 'Tiếng Việt', untranslated: [] }

const draft = (translations: MailTranslation[] = [english, vietnamese]): EmailDraft => ({
  to: [],
  cc: [],
  subject: '[설계변경 검토] S-001 ECN-D-0119 관련 작업 변경 사전 공유',
  salutation: '해송 작업반 작업반장님께',
  reference: 'S-001 호선 · ECN-D-0119 B31P 판 두께 변경',
  paragraphs: [paragraph('■ 대상 공정', '- B31P 선행의장'), paragraph('- 결정 기한: 2026년 11월 12일')],
  sender: '가람조선 설계팀',
  fictional: false,
  translations,
})

describe('언어 단추', () => {
  it('번역이 있으면 한국어 + 서버 순서의 언어(그 언어로 쓴 이름), 없으면 단추 없음', () => {
    expect(languageOptions(draft())).toEqual([
      { code: KOREAN, label: '한국어' },
      { code: 'en', label: 'English' },
      { code: 'vi', label: 'Tiếng Việt' },
    ])
    expect(languageOptions(draft([]))).toEqual([])
  })

  it('한국어·없는 언어는 번역 없음', () => {
    expect(translationOf(draft(), KOREAN)).toBeNull()
    expect(translationOf(draft(), 'uz')).toBeNull()
    expect(translationOf(draft(), 'vi')?.language_name).toBe('Tiếng Việt')
  })
})

describe('고른 보기의 제목·본문', () => {
  it('기본(한국어)은 원문 그대로', () => {
    expect(DEFAULT_VIEW.language).toBe(KOREAN)
    expect(viewText(draft(), '김설계', DEFAULT_VIEW)).toEqual({ subject: draft().subject, body: bodyText(draft(), '김설계') })
  })

  it('번역만: 그 언어 표기 · 한국어 표기 · 인사말 · 관련 건 · 문단 · 맺음 · 서명', () => {
    const text = viewText(draft(), '김설계', { language: 'en' })
    expect(text.subject).toBe(english.subject)
    expect(text.body).toBe(translatedBody(english, '김설계'))
    expect(text.body.split('\n').slice(0, 2)).toEqual([english.notice, english.notice_ko])
    expect(text.body).toContain('Reference: Hull S-001')
    expect(text.body).toContain('■ Affected work stages\n- B31P pre-outfitting (B31P 선행의장)')
    expect(text.body.endsWith('Best regards,\n김설계\n가람조선 design team (가람조선 설계팀)')).toBe(true)
    expect(text.body).not.toContain(bodyText(draft(), '김설계'))
  })

  it('베트남어도 번역만(한국어 원문을 덧붙이지 않음), 제목도 번역', () => {
    const text = viewText(draft(), '김설계', { language: 'vi' })
    expect(text).toEqual({ subject: vietnamese.subject, body: translatedBody(vietnamese, '김설계') })
  })

  it('번역 본문의 날짜·블록 번호는 원문과 같은 숫자(서버 값을 그대로 이어 붙임)', () => {
    const digits = (s: string) => [...s.matchAll(/\d+/g)].map((m) => Number(m[0])).sort((a, b) => a - b)
    const translated = viewText(draft(), '', { language: 'en' }).body
    const original = draft().paragraphs.flatMap((p) => p.blocks.map((b) => b.text)).join(' ')
    const translatedBlocks = english.paragraphs.flatMap((p) => p.blocks.map((b) => b.text)).join(' ')
    expect(new Set(digits(translatedBlocks))).toEqual(new Set(digits(original)))
    expect(translated).toContain('2026-11-12')
  })

  it('서명 이름이 비면 담당자', () => {
    expect(translatedBody({ ...english, sender: null }, '  ').endsWith('Best regards,\n담당자')).toBe(true)
  })
})

describe('원문 유지 줄', () => {
  it('용어집 밖 원문 유지 줄은 있을 때만', () => {
    expect(untranslatedLine(english)).toBe('용어집 미등록 · 원문 유지: 해송, 가람조선')
    expect(untranslatedLine(vietnamese)).toBeNull()
    expect(untranslatedLine(null)).toBeNull()
  })
})
