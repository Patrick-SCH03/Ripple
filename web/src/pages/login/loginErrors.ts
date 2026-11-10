// 로그인 화면(일반·빠른·체험 로그인)의 오류 문구: 소개·로그인 화면은 합니다체라(DESIGN.md 12절) 서버 auth 문구를
// 그대로 쓰지 않고 오류 코드별 합니다체 문구로 바꾼다(끝에 마침표). 서버 문구는 로그인 뒤 화면(비밀번호 정하기·구성원 관리)에서
// 그대로 쓰인다. 어느 쪽이 틀렸는지(아이디·비밀번호) 말하지 않는 규칙은 같다.
import { ApiError } from '@/api/client'

const BY_CODE: Record<string, string> = {
  invalid_credentials: '아이디 또는 비밀번호가 일치하지 않습니다.',
  account_disabled: '사용이 중지된 계정입니다. 팀장에게 문의해 주십시오.',
  busy: '로그인 요청이 많습니다. 잠시 뒤 다시 시도해 주십시오.',
  demo_unavailable: '체험 로그인이 꺼져 있습니다.',
  quick_unavailable: '빠른 로그인이 꺼져 있습니다.',
}

/** 서버에 닿지 못했을 때(로그인 실패·상태 확인 실패 공통). */
export const OFFLINE_TEXT = '서버에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주십시오.'

const FALLBACK = '로그인하지 못했습니다. 잠시 뒤 다시 시도해 주십시오.'

/**
 * 오류 → 합니다체 문구. 여러 번 틀려 막혔으면(too_many_attempts) 서버 문구의 'n분'을 그대로 옮긴다(없으면 '잠시 뒤').
 * 모르는 코드는 서버 문구 대신 일반 문구로.
 */
export function loginErrorText(error: Error): string {
  if (!(error instanceof ApiError)) return FALLBACK
  if (error.code === 'too_many_attempts') {
    const minutes = /(\d+)\s*분/.exec(error.message)?.[1]
    return `로그인을 여러 번 잘못 시도했습니다. ${minutes ? `${minutes}분 뒤` : '잠시 뒤'} 다시 시도해 주십시오.`
  }
  if (error.code && BY_CODE[error.code]) return BY_CODE[error.code]
  return error.status === 0 && !error.code ? OFFLINE_TEXT : FALLBACK
}
