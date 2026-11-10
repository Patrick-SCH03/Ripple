import { describe, expect, it } from 'vitest'
import type { Me } from '@/api/client'
import {
  accountState,
  can,
  deleteBlock,
  formatKstTime,
  isQuickAccount,
  loginIdProblem,
  PASSWORD_MIN,
  PASSWORD_RULE_TEXT,
  passwordProblem,
  whoLabel,
} from './account'

const member: Me = {
  login_id: 'kim',
  name: '김담당',
  role: 'member',
  permissions: ['view', 'export', 'change_password'],
  must_change_password: false,
}

describe('can', () => {
  it('권한 목록에 있는 것만', () => {
    expect(can(member, 'view')).toBe(true)
    expect(can(member, 'import')).toBe(false)
    expect(can(null, 'view')).toBe(false)
  })
})

describe('passwordProblem — 서버(ripple/auth/passwords.py)와 같은 규칙', () => {
  it('짧음·아이디 포함·같은 글자 반복·앞뒤 공백은 거절', () => {
    expect(passwordProblem('short1', 'kim')).toMatch('10자 이상')
    expect(passwordProblem('kim12345', 'kim')).toMatch('10자 이상')
    expect(passwordProblem('kimkim-01', 'kimkim')).toMatch('10자 이상')
    expect(passwordProblem('kimkimkim01', 'kimkimkim')).toMatch('아이디')
    expect(passwordProblem('aaaaaaaaaaab', 'lee')).toMatch('반복')
    expect(passwordProblem(' spaced-pass-1', 'lee')).toMatch('공백')
  })

  it('좋은 비밀번호는 통과', () => {
    expect(passwordProblem('ship-design-2026', 'kim')).toBeNull()
  })

  it('안내 문구가 실제 규칙과 같음: 아이디 그대로·아이디 + 몇 글자는 거절, 아이디 + 4자 이상은 통과', () => {
    expect(passwordProblem('qa-tmp-member1', 'qa-tmp-member')).toMatch('아이디')
    expect(passwordProblem('qa-tmp-member-pass', 'qa-tmp-member')).toBeNull()
    expect(PASSWORD_RULE_TEXT).not.toContain('아이디가 들어가지 않게')
    expect(PASSWORD_RULE_TEXT).toContain('아이디를 그대로 쓰거나 아이디에 몇 글자만 붙인')
    expect(PASSWORD_RULE_TEXT).toContain(`${PASSWORD_MIN}자 이상`)
  })
})

describe('loginIdProblem', () => {
  it('형식·예약된 아이디', () => {
    expect(loginIdProblem('kim.dh')).toBeNull()
    expect(loginIdProblem(' KIM ')).toBeNull()
    expect(loginIdProblem('')).toMatch('입력 필요')
    expect(loginIdProblem('ab')).toMatch('3~32자')
    expect(loginIdProblem('_kim')).toMatch('3~32자')
    expect(loginIdProblem('김담당')).toMatch('3~32자')
    expect(loginIdProblem('demo')).toMatch('쓸 수 없는')
    expect(loginIdProblem('Quick-Lead')).toMatch('쓸 수 없는')
    expect(loginIdProblem('quick-member')).toMatch('쓸 수 없는')
    expect(loginIdProblem('part-lead')).toMatch('쓸 수 없는')
    expect(loginIdProblem('executive')).toMatch('쓸 수 없는')
  })
})

describe('isQuickAccount — 빠른 로그인 고정 계정(서버 QUICK_IDS와 같음)', () => {
  it('네 아이디만(담당자·파트장·팀장·본부장)', () => {
    expect(isQuickAccount('quick-member')).toBe(true)
    expect(isQuickAccount('quick-lead')).toBe(true)
    expect(isQuickAccount('part-lead')).toBe(true)
    expect(isQuickAccount('executive')).toBe(true)
    expect(isQuickAccount('quick')).toBe(false)
    expect(isQuickAccount('lead')).toBe(false)
  })
})

describe('deleteBlock — 지울 수 없는 줄의 이유(서버 delete_account와 같은 규칙)', () => {
  const row = (login_id: string, role: 'admin' | 'member' = 'member', disabled = false) => ({ login_id, role, disabled })
  const lead = row('lead', 'admin')
  const park = row('park', 'admin')
  const kim = row('kim')

  it('다른 담당자·팀장이 남는 팀장·꺼진 팀장은 지울 수 있음', () => {
    const all = [lead, park, kim, row('off', 'admin', true)]
    expect(deleteBlock(kim, 'lead', all)).toBeNull()
    expect(deleteBlock(park, 'lead', all)).toBeNull()
    expect(deleteBlock(row('off', 'admin', true), 'lead', all)).toBeNull()
  })

  it('내 계정 → 고정 계정 → 마지막 팀장 차례로 이유', () => {
    expect(deleteBlock(lead, 'lead', [lead, kim])).toBe('내 계정 삭제 불가')
    expect(deleteBlock(row('quick-lead', 'admin'), 'lead', [lead, row('quick-lead', 'admin')])).toBe(
      '시연용 고정 계정 · 삭제 불가',
    )
    expect(deleteBlock(row('quick-member'), 'lead', [lead])).toBe('시연용 고정 계정 · 삭제 불가')
    // 개발 모드(내 줄이 표에 없음): 사용 중인 팀장이 하나뿐이면 그 줄은 지울 수 없음, 꺼진 팀장은 세지 않음
    expect(deleteBlock(lead, 'dev', [lead, kim, row('off', 'admin', true)])).toBe('마지막 팀장 · 삭제 불가')
    expect(deleteBlock(lead, 'dev', [lead, park])).toBeNull()
    expect(deleteBlock(kim, 'dev', [kim])).toBeNull()
  })

  it('빠른 로그인 고정 팀장(quick-lead)은 마지막 팀장 판단에서 세지 않음(아이디로 들어올 팀장이 0명이 되지 않게)', () => {
    const quickLead = row('quick-lead', 'admin')
    expect(deleteBlock(lead, 'quick-lead', [lead, quickLead, kim])).toBe('마지막 팀장 · 삭제 불가')
    expect(deleteBlock(lead, 'quick-lead', [lead, park, quickLead, kim])).toBeNull()
  })
})

describe('accountState', () => {
  it('멈춤이 먼저, 그다음 첫 로그인 전', () => {
    expect(accountState({ disabled: true, must_change_password: true })).toBe('사용 중지')
    expect(accountState({ disabled: false, must_change_password: true })).toBe('첫 로그인 전')
    expect(accountState({ disabled: false, must_change_password: false })).toBe('사용 중')
  })
})

describe('formatKstTime', () => {
  it('UTC 시각을 한국 시각으로(날짜가 넘어가도)', () => {
    expect(formatKstTime('2026-10-08T16:23:00Z')).toBe('10월 9일 01:23 KST')
    expect(formatKstTime('2026-10-09T03:05:00+00:00')).toBe('10월 9일 12:05 KST')
    expect(formatKstTime(null)).toBe('—')
    expect(formatKstTime('없음')).toBe('—')
  })
})

describe('whoLabel', () => {
  it('이름(역할), 이름이 역할 이름과 같으면 한 번만', () => {
    expect(whoLabel({ name: '김담당', role: 'member' })).toBe('김담당(담당자)')
    expect(whoLabel({ name: '팀장', role: 'admin' })).toBe('팀장')
    expect(whoLabel({ name: '관리자', role: 'admin' })).toBe('관리자') // 1.25.0 전 첫 계정 기본 이름
    expect(whoLabel({ name: '관리자', role: 'member' })).toBe('관리자(담당자)')
  })
})
