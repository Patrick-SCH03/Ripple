// 로그인한 사람·역할·권한 표시와 입력 검사(docs/operations.md(서비스) 2절). 막는 것은 서버이고, 화면은 단추를 보이고 숨기며
// 서버와 같은 규칙으로 먼저 알려 준다(규칙은 ripple/auth/passwords.py · ripple/contracts/auth.py와 같다).
import type { Me, Permission, Role } from '@/api/client'

export const ROLE_LABEL: Record<Role, string> = {
  admin: '팀장',
  member: '담당자',
  demo: '체험',
  part_lead: '파트장',
  executive: '본부장',
}

export const PASSWORD_MIN = 10
const PASSWORD_MAX = 128
const LOGIN_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{2,31}$/
export const NAME_MAX = 40
/** 빠른 로그인 고정 계정(ripple/auth/principal.py QUICK_IDS와 같다): 구성원 관리로 바꿀 수 없고 새로 만들 수 없다. */
const QUICK_IDS: readonly string[] = ['quick-member', 'part-lead', 'quick-lead', 'executive']
const RESERVED_IDS: readonly string[] = ['demo', 'dev', ...QUICK_IDS]

/** 빠른 로그인 고정 계정인가(구성원 관리 표에서 그 줄을 잠근다). */
export function isQuickAccount(loginId: string): boolean {
  return QUICK_IDS.includes(loginId)
}

type AccountRow = { login_id: string; role: Role; disabled: boolean }

// 빠른 로그인 고정 팀장(quick-lead)은 세지 않는다: 아이디로 로그인할 수 없고 빠른 로그인을 끄면 못 쓰는 시연 계정이라,
// 그것만 남기고 실제 팀장을 지우면 아이디로 들어올 팀장이 0명이 된다(첫 관리자·계정 준비에서 세지 않는 것과 같다)
const activeLead = (account: AccountRow) => account.role === 'admin' && !account.disabled && !isQuickAccount(account.login_id)

/**
 * 구성원 표에서 이 줄을 지울 수 없는 이유(지울 수 있으면 null). 서버(ripple/auth/members.py delete_account)와 같은 규칙:
 * 내 계정 · 빠른 로그인 고정 계정 · 지우면 사용 중인 팀장(고정 계정 제외)이 없어지는 계정. 막는 것은 서버이고 화면은 단추 대신
 * 이유를 보인다.
 */
export function deleteBlock(account: AccountRow, meId: string, accounts: readonly AccountRow[]): string | null {
  if (account.login_id === meId) return '내 계정 삭제 불가'
  if (isQuickAccount(account.login_id)) return '시연용 고정 계정 · 삭제 불가'
  const othersLead = accounts.some((other) => other.login_id !== account.login_id && activeLead(other))
  if (activeLead(account) && !othersLead) return '마지막 팀장 · 삭제 불가'
  return null
}

export function can(me: Me | null | undefined, permission: Permission): boolean {
  return !!me && me.permissions.includes(permission)
}

/**
 * 새 비밀번호 입력 칸 아래 안내(비밀번호 바꾸기 화면). 아래 passwordProblem 규칙 그대로 적는다 — 아이디가 들어가도 아이디에
 * 4자 이상 덧붙이면 쓸 수 있으므로 '아이디가 들어가지 않게'라고 적지 않는다.
 */
export const PASSWORD_RULE_TEXT = `${PASSWORD_MIN}자 이상으로 정해 주십시오. 아이디를 그대로 쓰거나 아이디에 몇 글자만 붙인 비밀번호, 같은 글자만 반복한 비밀번호는 사용할 수 없습니다.`

/** 새 비밀번호 규칙(서버가 최종 판단: 흔한 비밀번호 목록은 서버만 본다). 문제가 없으면 null. */
export function passwordProblem(password: string, loginId: string): string | null {
  if (password.length < PASSWORD_MIN) return `비밀번호는 ${PASSWORD_MIN}자 이상이어야 합니다`
  if (password.length > PASSWORD_MAX) return `비밀번호는 ${PASSWORD_MAX}자 이하여야 합니다`
  if (password.trim() !== password) return '비밀번호 앞뒤에는 공백을 넣을 수 없습니다'
  const own = loginId.trim().toLowerCase()
  const lowered = password.toLowerCase()
  if (own && lowered.includes(own) && lowered.length - own.length < 4) return '아이디가 포함된 비밀번호는 사용할 수 없습니다'
  if (new Set(password).size < 4) return '같은 글자를 반복한 비밀번호는 사용할 수 없습니다'
  return null
}

/** 구성원 아이디: 영문 소문자·숫자로 시작하는 3~32자(._- 가능). 문제가 없으면 null. */
export function loginIdProblem(value: string): string | null {
  const id = value.trim().toLowerCase()
  if (!id) return '아이디 입력 필요'
  if (!LOGIN_ID_PATTERN.test(id)) return '아이디 형식: 영문 소문자·숫자로 시작하는 3~32자(. _ - 가능)'
  if (RESERVED_IDS.includes(id)) return '쓸 수 없는 아이디'
  return null
}

// 역할 이름을 그대로 이름으로 쓴 계정(첫 계정 기본 이름 — 1.25.0 전에는 '관리자'였음)은 역할을 덧붙이지 않는다
const ROLE_NAMES: Partial<Record<Role, readonly string[]>> = { admin: ['팀장', '관리자'] }

/** 사람 표시: '김담당(담당자)'. 이름이 역할 이름이면(첫 계정 기본 이름 '팀장'·옛 '관리자') 한 번만. */
export function whoLabel(person: { name: string; role: Role }): string {
  const role = ROLE_LABEL[person.role]
  const plain = person.name === role || (ROLE_NAMES[person.role] ?? []).includes(person.name)
  return plain ? person.name : `${person.name}(${role})`
}

/** 계정 상태 한 마디(구성원 관리 표). */
export function accountState(account: { disabled: boolean; must_change_password: boolean }): string {
  if (account.disabled) return '사용 중지'
  return account.must_change_password ? '첫 로그인 전' : '사용 중'
}

const KST = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** 시각(ISO, 시간대 포함) → "10월 9일 01:23 KST"(DESIGN.md 8절: 시각을 보일 때만 KST). 없으면 '—'. */
export function formatKstTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = Object.fromEntries(KST.formatToParts(date).map((part) => [part.type, part.value]))
  return `${parts.month}월 ${parts.day}일 ${parts.hour}:${parts.minute} KST`
}
