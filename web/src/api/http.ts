// 요청 규칙: 모든 API 호출이 지나는 call과 그 오류·작업 공간 토큰·인증 세대.
//
// 작업 공간 토큰(docs/operations.md(서비스) 6절): 서버는 지도를 바꿀 때마다(같은 지도를 다시 켜거나 서버를 다시 켜도) 토큰을 바꾼다.
// 요청 종류는 셋이다.
// - 묶인 요청(분석·영향·비서·대화·샘플): 아는 토큰을 머리글에 싣는다. 서버는 다르면 409(workspace_changed). 응답이 왔을 때
//   이 화면의 기대 토큰이 그사이 바뀌었으면(다른 지도로 넘어감) 그 응답을 쓰지 않는다.
// - 동기화(지도 목록·상태): 토큰을 싣지 않는다. 목록 응답이 새 기대 토큰이 될지는 useWorkspace가 순서를 보고 정한다.
// - 전환(활성화·확정): 토큰을 싣는다(다른 곳에서 바뀌었으면 409). 성공 응답의 목록이 새 기대 토큰이 된다.
// 409 workspace_changed를 받으면 '작업 공간이 바뀜'을 알리고(useWorkspace가 목록을 다시 읽음) 오류로 끝낸다.
//
// 로그인(docs/operations.md(서비스) 3절): 세션 쿠키(HttpOnly)는 브라우저가 싣는다. '인증 세대'는 로그인·로그아웃·다른 계정·
// 비밀번호 바꿈(세션 교체)마다 오른다. 보낼 때와 받을 때의 세대가 다르면 그 응답(성공·401·409 모두)은 쓰지 않는다
// (SESSION_CHANGED) — 지난 세션의 늦은 401이 새 로그인을 지우거나, 지난 목록이 기대 토큰을 바꾸지 않게.
// 지금 세대의 401(로그인·체험·로그아웃·내 정보 경로 제외)만 '로그인이 끝남'으로 알린다.

/** 서버가 거절한 요청. problems는 사람이 읽는 이유 목록(명사형)이다.
 * code가 WORKSPACE_CHANGED면 작업 공간(지도·세대)이 바뀌어 쓰지 않은 요청이다(다시 불러온 뒤 하면 된다).
 * code가 IMPORT_CHANGED면 엑셀 가져오기의 열 확인 상태 버전이 바뀌어 거절한 요청이다(지금 상태로 다시 불러온 뒤). */
export class ApiError extends Error {
  readonly status: number
  readonly problems: string[]
  readonly code: string | null

  constructor(message: string, status: number, problems: string[] = [], code: string | null = null) {
    super(message)
    this.status = status
    this.problems = problems
    this.code = code
  }
}

export const WORKSPACE_HEADER = 'X-Ripple-Workspace'
export const WORKSPACE_CHANGED = 'workspace_changed'
export const IMPORT_CHANGED = 'import_changed'
export const SESSION_CHANGED = 'session_changed'
const SESSION_CHANGED_MESSAGE = '로그인 상태 바뀜 · 이 요청 결과 버림 — 다시 시도'
/** 401이 '로그인이 끝남'이 아닌 경로(로그인 시도·체험·빠른 로그인·로그아웃·로그인 여부 확인). */
const SESSION_PATHS = new Set(['/auth/login', '/auth/demo', '/auth/quick', '/auth/logout', '/auth/me'])
const CHANGED_MESSAGE = '지도 변경 또는 서버 재시작 · 이 요청 결과 버림 — 지금 지도로 다시 불러오는 중'

let expected: string | null = null
const listeners = new Set<() => void>()
let authGeneration = 0
let switching = 0 // 세션을 바꾸는 요청이 진행 중인 수
const unauthorizedListeners = new Set<() => void>()

/** 묶인 요청에 실을 기대 토큰. useWorkspace만 바꾼다(목록·전환 응답을 적용할 때). */
export function setExpectedWorkspace(token: string | null): void {
  expected = token
}

export function expectedWorkspace(): string | null {
  return expected
}

/** '작업 공간이 바뀜' 알림을 받는다(409 workspace_changed, 응답 토큰 불일치). 해제 함수를 돌려준다. */
export function onWorkspaceChanged(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function announce(): void {
  for (const listener of listeners) listener()
}

/** 로그인·로그아웃·다른 계정·비밀번호 바꿈(세션 교체) 때 부른다: 진행 중 응답을 버린다. 사람이 바뀔 수 있으면
 * 기대 작업 공간 토큰도 비운다. 같은 사람의 세션 교체(비밀번호 바꾸기)는 keepWorkspace로 토큰을 둔다 — 비우면 다음
 * 목록 읽기 전까지 묶인 요청이 토큰 없이 나가 지도가 바뀌어도 409로 막지 못한다. */
export function bumpAuthGeneration({ keepWorkspace = false }: { keepWorkspace?: boolean } = {}): void {
  authGeneration += 1
  if (!keepWorkspace) expected = null
}

export function currentAuthGeneration(): number {
  return authGeneration
}

/** 세션을 바꾸는 요청(로그인·체험·비밀번호 바꾸기)을 보낸다. 보내기 전과 성공한 뒤 세대를 올려, 그 사이 옛 쿠키로 나간
 * 요청의 응답(서버가 옛 세션을 지워 401이 될 수 있음)이 새 세션을 '로그인 끝남'으로 지우지 않게 한다. */
export async function switchSession<T>(
  send: () => Promise<T>,
  { keepWorkspace = false }: { keepWorkspace?: boolean } = {},
): Promise<T> {
  bumpAuthGeneration({ keepWorkspace })
  switching += 1
  try {
    const result = await send()
    bumpAuthGeneration({ keepWorkspace })
    return result
  } finally {
    switching -= 1
  }
}

/** 지금 세대의 요청이 401(로그인이 끝남)을 받으면 알린다. 해제 함수를 돌려준다. */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

/** 요청 종류: 묶인(bound) · 동기화(sync) · 전환(switch). 맨 위 설명 참고. */
type Kind = 'bound' | 'sync' | 'switch'

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

/** API 하나를 부른다(영역별 요청 파일이 쓴다). 실패는 ApiError로 던진다. */
export async function call<T>(
  path: string,
  init: RequestInit = {},
  kind: Kind = 'bound',
  type = 'application/json',
): Promise<T> {
  return send(path, init, kind, type, async (response) =>
    response.status === 204 ? (undefined as T) : ((await response.json()) as T),
  )
}

/** 내려받을 파일(엑셀 등): 본문과 서버가 정한 파일 이름(Content-Disposition, 없으면 null). */
export interface Download {
  blob: Blob
  filename: string | null
}

/** 파일을 내려받는 요청: call과 같은 규칙(오류·작업 공간 토큰·인증 세대)으로 본문을 Blob으로 읽는다. */
export async function download(path: string, init: RequestInit = {}, kind: Kind = 'bound'): Promise<Download> {
  return send(path, init, kind, 'application/json', async (response) => ({
    blob: await response.blob(),
    filename: dispositionName(response.headers.get('Content-Disposition')),
  }))
}

/** Content-Disposition의 파일 이름: 한글 이름(filename*=UTF-8'') 먼저, 없으면 filename. 없으면 null. */
export function dispositionName(header: string | null): string | null {
  if (!header) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim())
    } catch {
      // 잘못 인코딩된 이름이면 대체 이름으로
    }
  }
  const plain = /filename="([^"]+)"/i.exec(header) ?? /filename=([^;]+)/i.exec(header)
  return plain ? plain[1].trim() : null
}

async function send<T>(
  path: string,
  init: RequestInit,
  kind: Kind,
  type: string,
  read: (response: Response) => Promise<T>,
): Promise<T> {
  const token = kind === 'sync' ? null : expected
  const generation = authGeneration
  const headers: Record<string, string> = { 'Content-Type': type }
  if (token) headers[WORKSPACE_HEADER] = token
  let response: Response
  try {
    response = await fetch(`/api${path}`, { ...init, headers })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    staleCheck(generation) // 연결 실패도 그사이 로그인 상태가 바뀌었으면 지난 세대의 일
    throw new ApiError('서버 연결 실패 — 잠시 뒤 다시 시도', 0)
  }
  staleCheck(generation)
  if (response.status === 401 && !SESSION_PATHS.has(path)) {
    if (switching > 0) throw new ApiError(SESSION_CHANGED_MESSAGE, 0, [], SESSION_CHANGED)
    for (const listener of unauthorizedListeners) listener()
  }
  if (response.ok) {
    if (kind === 'bound') {
      const served = response.headers.get(WORKSPACE_HEADER)
      if (token && served && served !== token) {
        announce()
        throw new ApiError(CHANGED_MESSAGE, 409, [], WORKSPACE_CHANGED)
      }
      // 기다리는 사이 이 화면이 다른 작업 공간으로 넘어갔으면 이전 작업 공간의 응답은 쓰지 않는다
      if (token !== expected) throw new ApiError(CHANGED_MESSAGE, 409, [], WORKSPACE_CHANGED)
    }
    const data = await read(response)
    staleCheck(generation) // 머리글 뒤 본문을 읽는 사이 로그인 상태가 바뀜
    return data
  }
  const body: { detail?: unknown } = await response.json().catch(() => ({}))
  staleCheck(generation)
  return rejected(response.status, body.detail)
}

/** 거절 응답의 detail을 ApiError로 바꿔 던진다(작업 공간 바뀜은 알리고). */
function rejected(status: number, detail: unknown): never {
  if (status === 409 && isRecord(detail) && detail.code === WORKSPACE_CHANGED) {
    announce()
    throw new ApiError(CHANGED_MESSAGE, 409, [], WORKSPACE_CHANGED)
  }
  if (status === 409 && isRecord(detail) && detail.code === IMPORT_CHANGED) {
    throw new ApiError(String(detail.message ?? ''), 409, [], IMPORT_CHANGED)
  }
  if (isRecord(detail) && typeof detail.code === 'string' && typeof detail.message === 'string') {
    throw new ApiError(detail.message, status, [], detail.code) // 로그인·권한(AuthProblem)
  }
  if (isRecord(detail) && Array.isArray(detail.problems) && detail.problems.every((p) => isRecord(p) && 'entity_id' in p)) {
    // 상태 갱신 거부(UpdatePreview): 항목마다 대상과 이유
    const items = detail.problems as { entity_id: string; message: string }[]
    throw new ApiError('반영하지 못한 항목 있음', status, items.map((p) => `${p.entity_id}: ${p.message}`))
  }
  if (detail && typeof detail === 'object' && 'problems' in detail) {
    const { message, problems } = detail as { message: string; problems: string[] }
    throw new ApiError(message, status, problems)
  }
  if (Array.isArray(detail)) {
    const issues = (detail as ValidationIssue[]).map((d) => `${(d.loc ?? []).join('.')}: ${d.msg ?? ''}`)
    throw new ApiError('요청 형식이 계약과 다름', status, issues)
  }
  throw new ApiError(typeof detail === 'string' ? detail : `서버 오류(${status})`, status)
}

/** 요청을 보낼 때의 인증 세대가 지금과 다르면 그 응답(성공·실패·연결 실패 모두)은 쓰지 않는다. */
function staleCheck(generation: number): void {
  if (generation !== authGeneration) throw new ApiError(SESSION_CHANGED_MESSAGE, 0, [], SESSION_CHANGED)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
