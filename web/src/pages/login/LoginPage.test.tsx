import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AuthOptions } from '@/api/client'
import type { Session } from '@/state/useSession'
import { LoginPage } from './LoginPage'

const OPTIONS: AuthOptions = { required: true, demo_login: true, accounts_ready: true, quick_login: false }

function session(options: AuthOptions | null, optionsChecked = true): Session {
  const none = async () => null
  return {
    state: { status: 'anonymous', reason: null },
    options,
    optionsChecked,
    login: none,
    demo: none,
    quick: none,
    logout: async () => undefined,
    changePassword: none,
    retry: () => undefined,
  }
}

const render = (value: Session) =>
  renderToStaticMarkup(<LoginPage session={value} reason={null} onSignedIn={() => undefined} />)

describe('로그인 화면 — 빠른 로그인(시연 배포 전용)', () => {
  it('켜져 있으면 역할 단추 둘(담당자 → 파트장)만: 아이디 로그인·입력 칸·체험 단추·계정 안내 없음, 소개로 돌아가기는 그대로', () => {
    const html = render(session({ ...OPTIONS, quick_login: true }))
    const order = ['member', 'part_lead'].map((role) => html.indexOf(`data-testid="quick-${role}"`))
    expect(order.every((at) => at >= 0)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
    expect(html).toContain('담당자로 들어가기')
    expect(html).toContain('김설계 · 설계변경 영향을 분석하고 결재선에 검토를 요청합니다')
    expect(html).toContain('파트장으로 들어가기')
    expect(html).toContain('이파트장 · 같은 분석 결과를 보고 결재선 첫 단계를 결재합니다')
    expect(html).not.toContain('팀장으로 들어가기')
    expect(html).not.toContain('본부장으로 들어가기')
    expect(html).not.toContain('data-testid="login-open"')
    expect(html).not.toContain('아이디로 로그인')
    expect(html).not.toContain('또는')
    expect(html).not.toContain('data-testid="login-id"')
    expect(html).not.toContain('data-testid="login-password"')
    expect(html).not.toContain('data-testid="login-demo"')
    expect(html).not.toContain('계정은 팀장이 발급합니다')
    expect(html).toContain('소개로 돌아가기')
  })

  it('팀장 계정이 아직 없어도 빠른 로그인이면 배포 안내를 띄우지 않음(누르면 만들어짐)', () => {
    const html = render(session({ ...OPTIONS, quick_login: true, accounts_ready: false }))
    expect(html).not.toContain('아직 팀장 계정이 없습니다')
    expect(html).toContain('data-testid="quick-member"')
  })

  it('꺼져 있으면 지금 화면 그대로: 아이디·비밀번호·로그인·체험 단추, 빠른 로그인 단추 없음', () => {
    const html = render(session(OPTIONS))
    expect(html).toContain('data-testid="login-id"')
    expect(html).toContain('data-testid="login-password"')
    expect(html).toContain('data-testid="login-demo"')
    expect(html).toContain('계정은 팀장이 발급합니다')
    expect(html).not.toContain('data-testid="quick-')
    expect(html).not.toContain('data-testid="login-open"')
  })

  it('상태 확인 전에는 입력 칸도 단추도 그리지 않음(입력 칸이 단추로 바뀌어 보이지 않게), 확인 실패면 입력 칸', () => {
    const waiting = render(session(null, false))
    expect(waiting).not.toContain('data-testid="login-id"')
    expect(waiting).not.toContain('data-testid="quick-')
    expect(render(session(null, true))).toContain('data-testid="login-id"')
  })
})
