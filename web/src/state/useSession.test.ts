import { describe, expect, it } from 'vitest'
import { ApiError, SESSION_CHANGED, type Me } from '@/api/client'
import { stateFromMe } from './useSession'

const me: Me = { login_id: 'kim', name: '김담당', role: 'member', permissions: ['view'], must_change_password: false }

describe('stateFromMe — 시작 때 내 정보 응답', () => {
  it('성공 = 로그인함, 401 = 로그인 전, 그 밖의 실패 = 연결 안 됨', () => {
    expect(stateFromMe({ me })).toEqual({ status: 'signed-in', me })
    expect(stateFromMe({ error: new ApiError('로그인이 필요합니다', 401, [], 'unauthenticated') })).toEqual({
      status: 'anonymous',
      reason: null,
    })
    expect(stateFromMe({ error: new ApiError('서버에 연결하지 못했어요', 0) })).toMatchObject({ status: 'offline' })
  })

  it('그사이 로그인 상태가 바뀌어 버린 응답은 상태를 바꾸지 않음(방금 한 로그인을 덮지 않게)', () => {
    expect(stateFromMe({ error: new ApiError('로그인 상태가 바뀌어…', 0, [], SESSION_CHANGED) })).toBeNull()
  })
})
