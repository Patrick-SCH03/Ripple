import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  SESSION_CHANGED,
  WORKSPACE_CHANGED,
  WORKSPACE_HEADER,
  api,
  bumpAuthGeneration,
  onUnauthorized,
  onWorkspaceChanged,
  setExpectedWorkspace,
  switchSession,
} from './client'

const OLD = 'G-0000000000000001.a.1'
const NEW = 'G-0000000000000002.a.2'

function respond(status: number, body: unknown, token?: string): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (token) headers.set(WORKSPACE_HEADER, token)
  return new Response(JSON.stringify(body), { status, headers })
}

function stubFetch(handler: (init: RequestInit) => Response | Promise<Response>) {
  const calls: RequestInit[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit = {}) => {
      calls.push(init)
      return handler(init)
    }),
  )
  return calls
}

const header = (init: RequestInit | undefined) => new Headers(init?.headers).get(WORKSPACE_HEADER)

afterEach(() => {
  vi.unstubAllGlobals()
  setExpectedWorkspace(null)
})

describe('작업 공간 토큰 — 요청 종류', () => {
  it('묶인 요청은 기대 토큰을 싣고, 동기화(목록·상태)는 싣지 않음', async () => {
    setExpectedWorkspace(OLD)
    const calls = stubFetch(() => respond(200, [], OLD))
    await api.samples()
    await api.snapshots()
    expect(header(calls[0])).toBe(OLD)
    expect(header(calls[1])).toBeNull()
  })

  it('서버가 409 workspace_changed면 바뀜을 알리고 그 코드의 오류로 끝냄', async () => {
    setExpectedWorkspace(OLD)
    const heard = vi.fn()
    const stop = onWorkspaceChanged(heard)
    stubFetch(() => respond(409, { detail: { code: WORKSPACE_CHANGED, message: 'x', expected: OLD, active: NEW } }))
    const error = await api.analyses({}).catch((caught: unknown) => caught)
    stop()
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe(WORKSPACE_CHANGED)
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('다른 409(대화를 이어 갈 수 없음)는 바뀜이 아님', async () => {
    setExpectedWorkspace(OLD)
    const heard = vi.fn()
    const stop = onWorkspaceChanged(heard)
    stubFetch(() => respond(409, { detail: '대화를 찾지 못했어요' }))
    const context = { ship_ids: ['S-001'], as_of: '2026-10-20', horizon_days: 60 }
    const error = (await api.assistantTurn({ context, draft_only: false }).catch(
      (caught: unknown) => caught,
    )) as ApiError
    stop()
    expect(error.code).toBeNull()
    expect(error.message).toBe('대화를 찾지 못했어요')
    expect(heard).not.toHaveBeenCalled()
  })

  it('응답 머리글의 토큰이 보낸 토큰과 다르면 그 응답을 쓰지 않고 바뀜을 알림', async () => {
    setExpectedWorkspace(OLD)
    const heard = vi.fn()
    const stop = onWorkspaceChanged(heard)
    stubFetch(() => respond(200, { analysis_id: 'A-1' }, NEW))
    const error = (await api.analyses({}).catch((caught: unknown) => caught)) as ApiError
    stop()
    expect(error.code).toBe(WORKSPACE_CHANGED)
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('기다리는 사이 이 화면이 다른 작업 공간으로 넘어갔으면 이전 작업 공간의 응답은 쓰지 않음', async () => {
    setExpectedWorkspace(OLD)
    let release: (value: Response) => void = () => {}
    stubFetch(() => new Promise<Response>((resolve) => (release = resolve)))
    const pending = api.analyses({}).catch((caught: unknown) => caught)
    setExpectedWorkspace(NEW)
    release(respond(200, { analysis_id: 'A-1' }, OLD))
    const error = (await pending) as ApiError
    expect(error.code).toBe(WORKSPACE_CHANGED)
  })

  it('전환 요청은 토큰을 싣고, 성공 응답은 그대로 돌려줌(새 기대값은 useWorkspace가 정함)', async () => {
    setExpectedWorkspace(OLD)
    const calls = stubFetch(() => respond(200, { workspace: NEW }))
    const list = await api.activate('G-0000000000000002')
    expect(header(calls[0])).toBe(OLD)
    expect(list.workspace).toBe(NEW)
  })

  it('엑셀 올리기는 파일 그대로(octet-stream), 파일 이름은 주소에', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        urls.push(url)
        expect(new Headers(init.headers).get('Content-Type')).toBe('application/octet-stream')
        return respond(200, { summary: { template_version: 'excel-v1', file: 'a b.xlsx', issues: [] } })
      }),
    )
    await api.stageImport(new Blob(['x']), 'a b.xlsx')
    expect(urls[0]).toBe('/api/imports?file_name=a%20b.xlsx')
  })
})

describe('로그인 — 인증 세대와 401', () => {
  it('보낸 뒤 인증 세대가 바뀌면 응답(성공·401 모두)을 쓰지 않고, 로그인 끝남도 알리지 않음', async () => {
    const heard = vi.fn()
    const stop = onUnauthorized(heard)
    let release: (value: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => (release = resolve))))
    const pending = api.samples().catch((caught: unknown) => caught)
    bumpAuthGeneration() // 그사이 다시 로그인
    release(respond(401, { detail: { code: 'unauthenticated', message: '로그인이 필요합니다' } }))
    const error = (await pending) as ApiError
    const success = api.samples().catch((caught: unknown) => caught)
    bumpAuthGeneration() // 비밀번호를 바꿔 세션이 바뀜
    release(respond(200, []))
    const stale = (await success) as ApiError
    stop()
    expect(error.code).toBe(SESSION_CHANGED)
    expect(stale.code).toBe(SESSION_CHANGED)
    expect(heard).not.toHaveBeenCalled()
  })

  it('지금 세대의 401은 로그인 끝남을 알리고, 로그인 시도·내 정보의 401은 알리지 않음', async () => {
    const heard = vi.fn()
    const stop = onUnauthorized(heard)
    stubFetch(() => respond(401, { detail: { code: 'unauthenticated', message: '로그인이 필요합니다' } }))
    const business = (await api.samples().catch((caught: unknown) => caught)) as ApiError
    await api.me().catch(() => null)
    await api.login('kim', 'x').catch(() => null)
    stop()
    expect(business.code).toBe('unauthenticated')
    expect(business.message).toBe('로그인이 필요합니다')
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('인증 세대를 올리면 기대 작업 공간 토큰을 비움(다음 묶인 요청은 토큰 없이)', async () => {
    setExpectedWorkspace(OLD)
    bumpAuthGeneration()
    const calls = stubFetch(() => respond(200, []))
    await api.samples()
    expect(header(calls[0])).toBeNull()
  })

  it('로그아웃(204)은 본문 없이 끝남', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(api.logout()).resolves.toBeUndefined()
  })
})

describe('로그인 — 세션을 바꾸는 동안', () => {
  it('비밀번호를 바꾸는 사이 옛 쿠키로 나간 요청의 401은 로그인 끝남으로 알리지 않고 지난 세대로', async () => {
    const heard = vi.fn()
    const stop = onUnauthorized(heard)
    const releases: ((value: Response) => void)[] = []
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => releases.push(resolve))))
    const change = switchSession(() => api.changePassword('old-pass-123', 'new-pass-456'))
    await Promise.resolve()
    const during = api.samples().catch((caught: unknown) => caught) // 바꾸는 중에 나간 요청(옛 쿠키)
    await Promise.resolve()
    releases[1](respond(401, { detail: { code: 'unauthenticated', message: '로그인이 필요합니다' } }))
    releases[0](respond(200, { login_id: 'kim', name: '김', role: 'member', permissions: [], must_change_password: false }))
    const error = (await during) as ApiError
    await change
    stop()
    expect(error.code).toBe(SESSION_CHANGED)
    expect(heard).not.toHaveBeenCalled()
  })
})

describe('로그인 — 같은 사람의 세션 교체', () => {
  it('비밀번호를 바꿔도 기대 작업 공간 토큰은 그대로(다음 묶인 요청이 토큰을 싣고 409 보호 유지)', async () => {
    setExpectedWorkspace(OLD)
    const calls = stubFetch((init) =>
      init.method === 'POST'
        ? respond(200, { login_id: 'kim', name: '김', role: 'member', permissions: [], must_change_password: false })
        : respond(200, [], OLD),
    )
    await switchSession(() => api.changePassword('old-pass-123', 'new-pass-456'), { keepWorkspace: true })
    await api.samples()
    expect(header(calls[1])).toBe(OLD)
  })

  it('다른 사람이 될 수 있는 로그인은 토큰을 비움', async () => {
    setExpectedWorkspace(OLD)
    const calls = stubFetch((init) =>
      init.method === 'POST'
        ? respond(200, { login_id: 'kim', name: '김', role: 'member', permissions: [], must_change_password: false })
        : respond(200, []),
    )
    await switchSession(() => api.login('kim', 'pass-1234567'))
    await api.samples()
    expect(header(calls[1])).toBeNull()
  })
})

describe('로그인 — 지난 세대의 늦은 본문·연결 실패', () => {
  it('머리글이 온 뒤 본문을 읽는 사이 로그인하면 그 본문(옛 사용자 정보)을 쓰지 않음', async () => {
    let finish: (text: string) => void = () => {}
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        finish = (text) => {
          controller.enqueue(new TextEncoder().encode(text))
          controller.close()
        }
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))
    const pending = api.me().catch((caught: unknown) => caught)
    await new Promise((resolve) => setTimeout(resolve, 0))
    bumpAuthGeneration() // 본문이 오기 전에 다른 계정으로 로그인
    finish(JSON.stringify({ login_id: 'old', name: '옛 사용자', role: 'admin', permissions: [] }))
    expect(((await pending) as ApiError).code).toBe(SESSION_CHANGED)
  })

  it('연결 실패도 그사이 로그인했으면 연결 안 됨이 아니라 지난 세대', async () => {
    let fail: (error: Error) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((_, reject) => (fail = reject))))
    const pending = api.me().catch((caught: unknown) => caught)
    bumpAuthGeneration()
    fail(new TypeError('Failed to fetch'))
    expect(((await pending) as ApiError).code).toBe(SESSION_CHANGED)
  })
})
