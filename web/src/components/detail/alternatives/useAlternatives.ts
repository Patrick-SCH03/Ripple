// 대안 탭의 계산: 상세에 보이는 분석을 대안 포함으로 한 번 더 계산한다(분석 ID + 변경 사유로 기억해 다시 열면 그대로).
// 권고 대안 띠·검토 요청 창·대안 탭이 같은 기억을 쓴다 — 진행 중인 요청도 나눠 써서 같은 계산을 두 번 보내지 않는다.
import { useEffect, useState } from 'react'
import { ApiError, api, type AnalysisRequest, type AnalysisResult } from '@/api/client'
import { alternativesKey } from '@/lib/alternatives'

/** 대안 키(분석 ID + 변경 사유) → 대안 포함 결과. 탭을 오가도 다시 계산하지 않는다. */
const cache = new Map<string, AnalysisResult>()
/** 진행 중인 계산(키별 하나): 기다리는 화면이 모두 사라지면 멈춘다. 실패는 기억하지 않는다(다시 열면 다시 시도). */
const pending = new Map<string, { promise: Promise<AnalysisResult>; controller: AbortController; users: number }>()

type Loaded = { key: string; data: AnalysisResult } | { key: string; error: ApiError }

function start(key: string, request: AnalysisRequest) {
  const running = pending.get(key)
  if (running) {
    running.users += 1
    return running
  }
  const controller = new AbortController()
  const promise = api.analyses({ ...request, include_alternatives: true }, controller.signal).then((data) => {
    cache.set(key, data)
    return data
  })
  // 성공·실패 모두 끝나면 진행 중 목록에서 뺀다
  const entry = { promise, controller, users: 1 }
  promise.then(
    () => pending.get(key) === entry && pending.delete(key),
    () => pending.get(key) === entry && pending.delete(key),
  )
  pending.set(key, entry)
  return entry
}

function release(key: string) {
  const running = pending.get(key)
  if (!running) return
  running.users -= 1
  if (running.users <= 0) {
    running.controller.abort()
    pending.delete(key)
  }
}

/** enabled = false면 계산을 보내지 않고 null(대안이 생길 수 없는 요청 등). */
export function useAlternatives(result: AnalysisResult, enabled = true): Loaded | null {
  const key = alternativesKey(result)
  const request = result.request
  const [loaded, setLoaded] = useState<Loaded | null>(() => {
    const hit = cache.get(key)
    return hit ? { key, data: hit } : null
  })
  useEffect(() => {
    if (!enabled || cache.has(key)) return
    let live = true
    const running = start(key, request)
    running.promise.then(
      (data) => live && setLoaded({ key, data }),
      (caught: unknown) => {
        if (!live) return // 화면이 이미 다른 분석·사유로 바뀜
        setLoaded({ key, error: caught instanceof ApiError ? caught : new ApiError(String(caught), 0) })
      },
    )
    return () => {
      live = false
      release(key)
    }
  }, [key, enabled, request])
  if (!enabled) return null
  const hit = cache.get(key)
  if (hit) return { key, data: hit }
  return loaded?.key === key ? loaded : null
}
