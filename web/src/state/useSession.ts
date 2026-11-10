// 로그인 상태(docs/operations.md(서비스) 3절): 시작할 때 내 정보(GET /auth/me)로 정하고, 로그인·체험·빠른 로그인·로그아웃·
// 비밀번호 바꾸기를 한다.
// 인증 세대(api/client.ts)는 여기서만 올린다: 상태가 바뀌기 전에 올려 진행 중 응답이 새 상태를 덮지 않게 한다.
import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  SESSION_CHANGED,
  api,
  bumpAuthGeneration,
  currentAuthGeneration,
  onUnauthorized,
  switchSession,
  type AuthOptions,
  type Me,
  type QuickRole,
} from '@/api/client'
import type { LoginReason } from '@/lib/route'

export type SessionState =
  | { status: 'loading' }
  | { status: 'offline'; message: string }
  | { status: 'anonymous'; reason: LoginReason | null }
  | { status: 'signed-in'; me: Me }

export interface Session {
  state: SessionState
  /** 로그인 설정(체험 로그인 켬·관리자 준비·빠른 로그인). 상태 확인을 못 읽었으면(아직이거나 실패) null. */
  options: AuthOptions | null
  /** 상태 확인을 마쳤나(실패 포함). 로그인 화면이 설정을 모른 채 입력 칸을 그렸다가 빠른 로그인 단추로 바꾸지 않게. */
  optionsChecked: boolean
  /** 실패하면 그 오류(성공이면 null). */
  login: (loginId: string, password: string) => Promise<ApiError | null>
  demo: () => Promise<ApiError | null>
  /** 빠른 로그인(시연 배포 전용, options.quick_login): 고른 역할의 고정 계정으로. 실패 처리는 login과 같다. */
  quick: (role: QuickRole) => Promise<ApiError | null>
  logout: () => Promise<void>
  changePassword: (current: string, next: string) => Promise<ApiError | null>
  retry: () => void
}

const asError = (caught: unknown) => (caught instanceof ApiError ? caught : new ApiError(String(caught), 0))

/** 시작 때 내 정보 응답 → 로그인 상태. 그사이 로그인·로그아웃으로 인증 세대가 바뀌어 버린 응답(session_changed)이면
 * null — 그 사이에 정한 상태(예: 방금 한 로그인)를 '연결 안 됨'이나 '로그인 전'으로 덮지 않는다. */
export function stateFromMe(outcome: { me: Me } | { error: ApiError }): SessionState | null {
  if ('me' in outcome) return { status: 'signed-in', me: outcome.me }
  const { error } = outcome
  if (error.code === SESSION_CHANGED) return null
  if (error.status === 401) return { status: 'anonymous', reason: null }
  return { status: 'offline', message: error.message }
}

export function useSession(): Session {
  const [state, setState] = useState<SessionState>({ status: 'loading' })
  const [options, setOptions] = useState<AuthOptions | null | undefined>(undefined) // undefined = 아직 확인 전
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let alive = true
    api.health().then(
      (health) => alive && setOptions(health.auth ?? null),
      () => alive && setOptions(null),
    )
    // 시작 때의 인증 세대: 그사이 로그인·로그아웃이 있었으면 이 확인 결과로 상태를 바꾸지 않는다
    const generation = currentAuthGeneration()
    const settle = (next: SessionState | null) => {
      if (alive && next && currentAuthGeneration() === generation) setState(next)
    }
    api.me().then(
      (me) => settle(stateFromMe({ me })),
      (caught: unknown) => settle(stateFromMe({ error: asError(caught) })),
    )
    // 지금 세대의 요청이 401을 받음 = 세션이 끝남(만료·폐기·다른 곳에서 비밀번호 변경)
    const stop = onUnauthorized(() => {
      bumpAuthGeneration()
      setState({ status: 'anonymous', reason: 'expired' })
    })
    return () => {
      alive = false
      stop()
    }
  }, [attempt])

  const signIn = useCallback(async (send: () => Promise<Me>, keepWorkspace = false) => {
    try {
      const me = await switchSession(send, { keepWorkspace })
      setState({ status: 'signed-in', me })
      return null
    } catch (caught) {
      return asError(caught)
    }
  }, [])

  const login = useCallback(
    (loginId: string, password: string) => signIn(() => api.login(loginId, password)),
    [signIn],
  )
  const demo = useCallback(() => signIn(() => api.demo()), [signIn])
  const quick = useCallback((role: QuickRole) => signIn(() => api.quick(role)), [signIn])
  const changePassword = useCallback(
    // 같은 사람의 세션 교체: 작업 공간 토큰은 그대로(지도는 그대로이고 409 보호를 끊지 않게)
    (current: string, next: string) => signIn(() => api.changePassword(current, next), true),
    [signIn],
  )
  const logout = useCallback(async () => {
    bumpAuthGeneration()
    setState({ status: 'anonymous', reason: 'signed-out' })
    await api.logout().catch(() => undefined) // 서버에 닿지 못해도 화면은 로그아웃(쿠키는 12시간 뒤 만료)
  }, [])
  const retry = useCallback(() => {
    setState({ status: 'loading' })
    setAttempt((n) => n + 1)
  }, [])

  return {
    state,
    options: options ?? null,
    optionsChecked: options !== undefined,
    login,
    demo,
    quick,
    logout,
    changePassword,
    retry,
  }
}
