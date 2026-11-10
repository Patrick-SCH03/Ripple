// 로그인 화면 오류 문구: 서버 오류 코드별 합니다체(로그인 화면은 코드별 문구, 로그인 뒤 화면은 서버 문구 그대로).
import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { OFFLINE_TEXT, loginErrorText } from './loginErrors'

describe('로그인 오류 문구(합니다체)', () => {
  it('코드별: 어느 쪽이 틀렸는지 말하지 않음 · 사용 중지 · 요청 몰림 · 체험·빠른 로그인 꺼짐', () => {
    const text = (code: string, status = 400) => loginErrorText(new ApiError('서버 해요체 문구예요', status, [], code))
    expect(text('invalid_credentials', 401)).toBe('아이디 또는 비밀번호가 일치하지 않습니다.')
    expect(text('account_disabled', 403)).toBe('사용이 중지된 계정입니다. 팀장에게 문의해 주십시오.')
    expect(text('busy', 503)).toBe('로그인 요청이 많습니다. 잠시 뒤 다시 시도해 주십시오.')
    expect(text('demo_unavailable', 404)).toBe('체험 로그인이 꺼져 있습니다.')
    expect(text('quick_unavailable', 404)).toBe('빠른 로그인이 꺼져 있습니다.')
  })

  it('여러 번 틀려 막히면 서버가 알려 준 분을 옮기고, 없으면 잠시 뒤', () => {
    const locked = new ApiError('로그인을 여러 번 틀렸어요. 5분 뒤 다시 시도해 주세요', 429, [], 'too_many_attempts')
    expect(loginErrorText(locked)).toBe('로그인을 여러 번 잘못 시도했습니다. 5분 뒤 다시 시도해 주십시오.')
    expect(loginErrorText(new ApiError('막혔어요', 429, [], 'too_many_attempts'))).toBe(
      '로그인을 여러 번 잘못 시도했습니다. 잠시 뒤 다시 시도해 주십시오.',
    )
  })

  it('연결 실패는 연결 문구, 모르는 오류는 일반 문구(서버 문구를 그대로 내지 않음)', () => {
    expect(loginErrorText(new ApiError('서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.', 0))).toBe(OFFLINE_TEXT)
    for (const error of [new ApiError('서버 오류가 발생했어요(500)', 500), new Error('알 수 없어요')]) {
      const text = loginErrorText(error)
      expect(text).toMatch(/(니다|십시오)\.$/)
      expect(text).not.toContain('어요')
    }
  })
})