// 공식 메일 초안을 Gmail 쓰기 창으로 여는 계산(순수 함수, mail.test.ts가 성질을 검사한다, docs/records.md(통보)).
// 앱은 메일을 보내지 않는다: 새 탭의 Gmail 쓰기 창에 받는 사람·참조·제목·본문을 채워 열고, 보내기는 사람이 누른다.
// 메일 앱(mailto)은 쓰지 않는다. Gmail은 초안이 주소로 Google에 가므로 합성 데이터일 때만 —
// 실데이터 지도는 복사만. 주소가 너무 길면(한글은 퍼센트 인코딩으로 9배) 본문 없이 열고 본문은 클립보드로 넘긴다.
import type { Contact, EmailDraft, Notification } from '@/api/client'

/** Gmail 쓰기 창 주소 길이 한도. 넘으면 본문을 클립보드로. */
export const URL_LIMIT = 7000

/** 초안 열쇠(카드·창·붙여 넣기 잠금이 같은 초안을 가리키게). */
export function draftKey(notification: Pick<Notification, 'target' | 'recipient_id'>): string {
  return `${notification.target}-${notification.recipient_id}`
}

function addressOf(contact: Contact): string {
  return contact.email
}

/** 받는 사람 표시: '최유진 과장 <yujin.choi@hangyeol-valve.example>'. */
export function personLabel(contact: Contact): string {
  const who = contact.title ? `${contact.name} ${contact.title}` : contact.name
  return `${who} <${contact.email}>`
}

/** 접힌 카드의 받는 사람 한 줄: 이름·직함만(주소는 펼친 보기·복사), 회사가 머리와 같으면 빼고 다르면 덧붙인다. */
export function recipientLine(email: Pick<EmailDraft, 'to'>, company: string): string {
  if (!email.to.length) return '연락처 없음 · 메일 창에서 직접 입력'
  return email.to
    .map((contact) => {
      const who = contact.title ? `${contact.name} ${contact.title}` : contact.name
      return contact.organization && contact.organization !== company ? `${who} · ${contact.organization}` : who
    })
    .join(', ')
}

/** 본문 문단: 블록마다 한 줄, 문단 사이는 빈 줄. */
function paragraphsText(email: EmailDraft): string {
  return email.paragraphs.map((paragraph) => paragraph.blocks.map((block) => block.text).join('\n')).join('\n\n')
}

/** 메일 본문 전체: 인사말 · 관련 건 · 문단 · 서명(보내는 사람 이름 + 조직). */
export function bodyText(email: EmailDraft, signer: string): string {
  const signature = [`${signer.trim() || '담당자'} 드림`, ...(email.sender ? [email.sender] : [])].join('\n')
  return [email.salutation, '', `관련 건: ${email.reference}`, '', paragraphsText(email), '', signature].join('\n')
}

/** 보낼 제목·본문(1.36.0 번역 보기면 lib/mailView가 만든다). 없으면 한국어 원문. */
export interface MailText {
  subject: string
  body: string
}

/** 복사용: 받는 사람·참조·제목 머리 + 본문. 받는 사람이 없으면 '(직접 적어 주세요)'. */
export function fullText(email: EmailDraft, signer: string, text?: MailText): string {
  const to = email.to.length ? email.to.map(personLabel).join(', ') : '(직접 입력)'
  const head = [`받는 사람: ${to}`, ...(email.cc.length ? [`참조: ${email.cc.map(personLabel).join(', ')}`] : [])]
  const body = text?.body ?? bodyText(email, signer)
  return [...head, `제목: ${text?.subject ?? email.subject}`, '', body].join('\n')
}

/** Gmail 쓰기 창 주소. body가 null이면 본문 없이(받는 사람·참조·제목만). */
export function composeUrl(email: EmailDraft, body: string | null, subject: string = email.subject): string {
  const pairs: [string, string][] = [
    ['view', 'cm'],
    ['fs', '1'],
    ['to', email.to.map(addressOf).join(',')],
    ['cc', email.cc.map(addressOf).join(',')],
    ['su', subject],
    ['body', body ?? ''],
  ]
  const query = pairs
    .filter(([, value]) => value !== '')
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join('&')
  return `https://mail.google.com/mail/?${query}`
}

export interface ComposePlan {
  url: string
  /** 본문을 주소에 넣었는가(아니면 클립보드로 넘겨 사용자가 붙여 넣는다). */
  bodyIncluded: boolean
  body: string
}

/** 열 주소와 본문 전달 방식. 본문을 넣으면 한도를 넘을 때만 본문 없이 연다. text는 번역 보기의 제목·본문. */
export function planCompose(email: EmailDraft, signer: string, text?: MailText): ComposePlan {
  const body = text?.body ?? bodyText(email, signer)
  const subject = text?.subject ?? email.subject
  const full = composeUrl(email, body, subject)
  if (full.length <= URL_LIMIT) return { url: full, bodyIncluded: true, body }
  return { url: composeUrl(email, null, subject), bodyIncluded: false, body }
}

/** 차례로 열기에서 다음 차례: 고른 것 중 아직 열지 않은 첫 초안(붙여 넣기 기다리는 초안이 있으면 null). */
export function nextToOpen(
  order: readonly string[],
  selected: ReadonlySet<string>,
  states: Readonly<Record<string, DraftState | undefined>>,
): string | null {
  if (order.some((id) => states[id] === 'paste')) return null
  return order.find((id) => selected.has(id) && !states[id]) ?? null
}

/** 초안 상태: 열었음 · 붙여 넣기 기다림(본문을 클립보드로) · 붙여 넣음. */
export type DraftState = 'opened' | 'paste' | 'done'
