// 로그인·계정 요청(docs/operations.md(서비스) 3절): 서버 상태, 로그인·체험·빠른 로그인·로그아웃·비밀번호 바꾸기, 계정 관리.
// 모두 지도와 무관한 동기화 요청이다(세션을 바꾸는 요청은 부르는 쪽이 switchSession으로 감싼다).
import { call } from './http'
import type {
  Account,
  AccountCreate,
  AccountCreated,
  AccountList,
  AccountUpdate,
  Health,
  Me,
  PasswordIssued,
  QuickLogin,
  QuickRole,
} from './types'

export const accountApi = {
  health: () => call<Health>('/health', {}, 'sync'),
  me: () => call<Me>('/auth/me', {}, 'sync'),
  login: (loginId: string, password: string) =>
    call<Me>('/auth/login', { method: 'POST', body: JSON.stringify({ login_id: loginId, password }) }, 'sync'),
  demo: () => call<Me>('/auth/demo', { method: 'POST' }, 'sync'),
  /** 1.30.0 빠른 로그인(시연 배포 전용): 고른 역할의 고정 계정으로 들어간다. */
  quick: (role: QuickRole) =>
    call<Me>('/auth/quick', { method: 'POST', body: JSON.stringify({ role } satisfies QuickLogin) }, 'sync'),
  logout: () => call<undefined>('/auth/logout', { method: 'POST' }, 'sync'),
  changePassword: (current: string, next: string) =>
    call<Me>(
      '/auth/password',
      { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) },
      'sync',
    ),
  accounts: () => call<AccountList>('/accounts', {}, 'sync'),
  createAccount: (body: AccountCreate) =>
    call<AccountCreated>('/accounts', { method: 'POST', body: JSON.stringify(body) }, 'sync'),
  resetPassword: (loginId: string) =>
    call<PasswordIssued>(`/accounts/${encodeURIComponent(loginId)}/reset-password`, { method: 'POST' }, 'sync'),
  updateAccount: (loginId: string, body: AccountUpdate) =>
    call<Account>(`/accounts/${encodeURIComponent(loginId)}`, { method: 'PATCH', body: JSON.stringify(body) }, 'sync'),
  /** 계정 지우기(204): 그 계정의 세션이 모두 끊기고, 기록에 남은 이름은 그대로이며 그 아이디는 다시 쓰지 않는다. */
  deleteAccount: (loginId: string) =>
    call<undefined>(`/accounts/${encodeURIComponent(loginId)}`, { method: 'DELETE' }, 'sync'),
}
