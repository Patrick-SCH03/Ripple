// 로그인 전 기다림 화면: 소개·로그인과 같은 합니다체(DESIGN.md 12절 — 로그인 전에도 보이는 화면).
import { describe, expect, it } from 'vitest'
import { SESSION_CHECK_TEXT } from './Splash'

describe('로그인 상태 확인 문구', () => {
  it('합니다체', () => {
    expect(SESSION_CHECK_TEXT).toBe('로그인 상태를 확인하고 있습니다…')
    expect(SESSION_CHECK_TEXT).not.toMatch(/에요|해요/)
  })
})
