// 화면 경로(라이브러리 없이 history API, docs/operations.md(서비스) 3절): / 소개 · /login 로그인 · /app 업무 화면 ·
// /app/manage 결재·현황(관리자, docs/records.md(기록·결재) 11절) · /app/report/<ECN 번호>/<개정 번호> 판단 리포트(9절). 그 밖은 소개로.
// 로그인 뒤 돌아갈 곳(next)은 업무 화면 경로만 받는다(다른 사이트로 보내는 열린 리다이렉트를 막는다).

export type Page = 'landing' | 'login' | 'app' | 'manage' | 'report'
export type LoginReason = 'expired' | 'signed-out'

export interface Route {
  page: Page
  /** 로그인 화면: 로그인 뒤 갈 업무 화면 경로. */
  next: string
  /** 로그인 화면: 왜 로그인 화면에 왔는지(만료·로그아웃). */
  reason: LoginReason | null
  /** 판단 리포트: 어느 ECN의 몇 번째 개정인지. */
  report: { ecnId: string; revision: number } | null
}

export const APP_PATH = '/app'
export const MANAGE_PATH = '/app/manage'
const LOGIN_PATH = '/login'
/** 업무 화면을 열며 그 기록의 분석을 바로 연다(결재함 '열기' → /app?record=R-…). */
const RECORD_PARAM = 'record'
const RECORD_ID = /^R-[0-9a-f]{16}$/ // 서버의 RECORD_ID_PATTERN과 같음

/** 결재함에서 그 개정의 기록된 분석을 업무 화면으로 여는 주소. */
export function openRecordPath(recordId: string): string {
  return `${APP_PATH}?${RECORD_PARAM}=${encodeURIComponent(recordId)}`
}

/** 주소의 ?record=… 가 올바른 기록 ID면 그 값, 아니면 null. */
export function recordParam(search: string): string | null {
  const value = new URLSearchParams(search).get(RECORD_PARAM)
  return value && RECORD_ID.test(value) ? value : null
}

/**
 * 로그인 뒤·소개 화면에서 들어갈 첫 화면: 결재자(승인 권한 — 팀장·파트장·본부장)는 결재·현황(첫 탭 결재함 — 자기 결재 단계 건),
 * 그 밖은 업무 화면. 다른 곳을 고르면 그대로.
 */
export function landingPath(next: string, approver: boolean): string {
  return approver && next === APP_PATH ? MANAGE_PATH : next
}
const REPORT = /^\/app\/report\/([^/]+)\/(\d{1,6})$/
const ECN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/ // 서버의 ECN_ID_PATTERN과 같음

/** 경로 → 화면. 알 수 없는 경로면 redirect(소개). 끝의 '/'는 무시한다. */
export function parseRoute(pathname: string, search: string): Route | { redirect: string } {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  const params = new URLSearchParams(search)
  if (path === '/' || path === '') return { page: 'landing', next: APP_PATH, reason: null, report: null }
  if (path === LOGIN_PATH) {
    const reason = params.get('reason')
    return {
      page: 'login',
      next: safeNext(params.get('next')),
      reason: reason === 'expired' || reason === 'signed-out' ? reason : null,
      report: null,
    }
  }
  const report = REPORT.exec(path)
  if (report) {
    const ecnId = decodeSegment(report[1])
    const revision = Number(report[2])
    if (ecnId !== null && ECN_ID.test(ecnId) && revision >= 1) {
      return { page: 'report', next: APP_PATH, reason: null, report: { ecnId, revision } }
    }
    return { redirect: APP_PATH }
  }
  if (path === MANAGE_PATH) return { page: 'manage', next: MANAGE_PATH, reason: null, report: null }
  if (path === APP_PATH || path.startsWith(`${APP_PATH}/`)) {
    return { page: 'app', next: APP_PATH, reason: null, report: null }
  }
  return { redirect: '/' }
}

function decodeSegment(value: string): string | null {
  try {
    return decodeURIComponent(value)
  } catch {
    return null
  }
}

/** 로그인 뒤 갈 곳: '/app', '/app/…', '/app?…', '/app#…'만. 그 밖(다른 사이트·'//'·역슬래시)은 '/app'. */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith(APP_PATH)) return APP_PATH
  const rest = value.slice(APP_PATH.length)
  if (rest !== '' && !['/', '?', '#'].includes(rest[0])) return APP_PATH
  if (value.includes('//') || value.includes('\\')) return APP_PATH
  return value
}

export function loginPath(next: string = APP_PATH, reason: LoginReason | null = null): string {
  const params = new URLSearchParams()
  const target = safeNext(next)
  if (target !== APP_PATH) params.set('next', target)
  if (reason) params.set('reason', reason)
  const query = params.toString()
  return query ? `${LOGIN_PATH}?${query}` : LOGIN_PATH
}
