// 상태 확인 뒤 다시 분석(docs/domain.md 12절): 확인을 보내면 지도가 바뀌어 작업 공간 토큰이 새로 나오고, 화면(Workbench)이
// 그 토큰을 key로 새로 그려 분석 세션이 비워진다. 그래서 보내기 전에 지금 요청을 세션 저장소에 맡기고, 새 작업 공간의
// 분석 세션이 처음 열 때 한 번만 꺼내 같은 요청으로 다시 분석한다(첫 샘플 대신).
// - 맡길 때의 토큰과 다른(= 바뀐) 작업 공간에서만, 1분 안에만 꺼낸다. 꺼내면 지운다(두 번 돌지 않음).
// - 확인이 실패하거나 지도가 그대로면(재확인) 보낸 쪽이 지운다.
import type { AnalysisRequest } from '@/api/client'

const KEY = 'ripple.rerun'
const TTL_MS = 60_000

interface Pending {
  from: string
  request: AnalysisRequest
  at: number
}

function store(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function stashRerun(from: string, request: AnalysisRequest, now = Date.now()): void {
  try {
    store()?.setItem(KEY, JSON.stringify({ from, request, at: now } satisfies Pending))
  } catch {
    // 저장소를 못 쓰면 다시 분석은 사용자가 목록에서 고르면 된다
  }
}

export function clearRerun(): void {
  try {
    store()?.removeItem(KEY)
  } catch {
    // 무시
  }
}

/** 지금 작업 공간이 맡길 때와 다르고 1분 안이면 그 요청(한 번만). */
export function takeRerun(current: string | null, now = Date.now()): AnalysisRequest | null {
  let pending: Pending | null = null
  try {
    const raw = store()?.getItem(KEY)
    pending = raw ? (JSON.parse(raw) as Pending) : null
  } catch {
    pending = null
  }
  if (!pending) return null
  clearRerun()
  if (!current || pending.from === current || now - pending.at > TTL_MS) return null
  return pending.request
}
