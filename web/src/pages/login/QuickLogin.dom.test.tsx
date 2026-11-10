// @vitest-environment jsdom
// 빠른 로그인 단추를 실제로 눌러 본다(DOM): 누른 역할로 session.quick, 누르는 동안 두 단추 비활성, 실패하면 서버 문구.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type QuickRole } from '@/api/client'
import type { Session } from '@/state/useSession'
import { LoginPage } from './LoginPage'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const mounted: Root[] = []
afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  document.body.innerHTML = ''
})

const OFF = { required: true, demo_login: false, accounts_ready: true, quick_login: false }

function session(quick: Session['quick'], login: Session['login'] = async () => null): Session {
  const none = async () => null
  return {
    state: { status: 'anonymous', reason: null },
    options: { required: true, demo_login: true, accounts_ready: true, quick_login: true },
    optionsChecked: true,
    login,
    demo: none,
    quick,
    logout: async () => undefined,
    changePassword: none,
    retry: () => undefined,
  }
}

/** quick을 부르면 그 역할을 적고, 돌려줄 때까지 기다리는 약속(돌려주기 함수는 settle). */
function pending() {
  const calls: QuickRole[] = []
  let settle: (failure: ApiError | null) => void = () => undefined
  const quick = (role: QuickRole) => {
    calls.push(role)
    return new Promise<ApiError | null>((resolve) => {
      settle = resolve
    })
  }
  return { calls, quick, settle: (failure: ApiError | null) => settle(failure) }
}

async function mount(value: Session, onSignedIn: () => void) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  mounted.push(root)
  await act(async () => root.render(<LoginPage session={value} reason={null} onSignedIn={onSignedIn} />))
  const button = (role: QuickRole) => container.querySelector<HTMLButtonElement>(`[data-testid="quick-${role}"]`)
  return {
    container,
    member: button('member')!,
    part: button('part_lead')!,
    lead: button('admin'),
    boss: button('executive'),
  }
}

describe('빠른 로그인 단추 누르기', () => {
  it('누른 역할로 session.quick, 누르는 동안 두 단추 비활성·들어가는 중, 실패하면 오류 코드별 합니다체 문구 · 다시 누를 수 있음', async () => {
    const fake = pending()
    const signedIn = vi.fn()
    const { container, member, part } = await mount(session(fake.quick), signedIn)

    await act(async () => part.click())
    expect(fake.calls).toEqual(['part_lead'])
    expect([member, part].every((button) => button.disabled)).toBe(true)
    expect(part.getAttribute('aria-busy')).toBe('true')
    expect(part.textContent).toContain('들어가는 중입니다…')
    expect(member.textContent).not.toContain('들어가는 중입니다…')

    await act(async () => member.click()) // 비활성이라 두 번째 요청은 나가지 않음
    expect(fake.calls).toEqual(['part_lead'])

    await act(async () => fake.settle(new ApiError('사용이 중지된 계정입니다. 팀장에게 문의해 주십시오', 403, [], 'account_disabled')))
    expect(container.querySelector('[data-testid="login-error"]')?.textContent).toBe(
      '사용이 중지된 계정입니다. 팀장에게 문의해 주십시오.',
    )
    expect([member, part].some((button) => button.disabled)).toBe(false)
    expect(signedIn).not.toHaveBeenCalled()
  })

  it('빠른 로그인이면 아이디 로그인이 없고 단추는 담당자·파트장 둘(팀장·본부장 없음 — 결재선은 화면의 진행 표시로만)', async () => {
    const { container, lead, boss } = await mount(session(pending().quick), vi.fn())
    expect(container.querySelector('[data-testid="login-open"]')).toBeNull()
    expect(container.querySelector('[data-testid="login-id"]')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
    expect(
      Array.from(container.querySelectorAll('[data-testid^="quick-"]')).map((button) => button.getAttribute('aria-label')),
    ).toEqual(['담당자로 들어가기', '파트장으로 들어가기'])
    expect([lead, boss]).toEqual([null, null])
  })

  it('빠른 로그인이 꺼지면 입력 칸 그대로: 빈 칸이면 입력 칸 아래 문구, 적으면 session.login', async () => {
    const calls: [string, string][] = []
    const login = async (id: string, password: string) => {
      calls.push([id, password])
      return new ApiError('아이디 또는 비밀번호가 일치하지 않습니다', 401, [], 'invalid_credentials')
    }
    const signedIn = vi.fn()
    const off = { ...session(pending().quick, login), options: { ...OFF } }
    const { container } = await mount(off, signedIn)
    expect(container.querySelector('[data-testid^="quick-"]')).toBeNull()
    const id = container.querySelector<HTMLInputElement>('[data-testid="login-id"]')!
    const password = container.querySelector<HTMLInputElement>('[data-testid="login-password"]')!

    const form = id.closest('form')!
    await act(async () => form.requestSubmit())
    expect(calls).toEqual([])
    expect(form.querySelector('[data-testid="login-error"]')?.textContent).toBe('아이디와 비밀번호를 입력해 주십시오')

    const type = (input: HTMLInputElement, value: string) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    await act(async () => {
      type(id, ' lead ')
      type(password, 'secret-pass-1')
    })
    await act(async () => form.requestSubmit())
    expect(calls).toEqual([['lead', 'secret-pass-1']])
    expect(container.querySelectorAll('[data-testid="login-error"]')).toHaveLength(1)
    expect(form.querySelector('[data-testid="login-error"]')?.textContent).toBe('아이디 또는 비밀번호가 일치하지 않습니다.')
    expect(password.value).toBe('')
    expect(signedIn).not.toHaveBeenCalled()
  })

  it('성공하면 onSignedIn, 단추마다 그 역할로(담당자 member · 파트장 part_lead)', async () => {
    const fake = pending()
    const signedIn = vi.fn()
    const { container, member, part } = await mount(session(fake.quick), signedIn)
    for (const button of [member, part]) {
      await act(async () => button.click())
      await act(async () => fake.settle(null))
    }
    expect(fake.calls).toEqual(['member', 'part_lead'])
    expect(signedIn).toHaveBeenCalledTimes(2)
    expect(container.querySelector('[data-testid="login-error"]')).toBeNull()
  })
})
