// 결정 도우미 불러오기: 대상(진행 중 검토 개정의 기록)이 바뀌면 다시 부르고, 이전 요청은 멈춘다.
// 받은 도우미가 지금 대상의 기록이 아니면(그사이 새 개정) 그리지 않는다. 실패해도 결재 띠·단추는 그대로다.
// 과거 사례 묶음을 서버가 아직 만드는 중(building)이면 잠시 뒤 다시 불러 사례를 채운다(보이던 세 줄은 그대로 둔 채).
// 한국 시간 날짜가 바뀌면 다시 부른다(D-n이 하루 줄어듦).
import { useEffect, useState } from 'react'
import { api, type DecisionBrief } from '@/api/client'
import { todayKst } from '@/lib/basis'
import { briefFor, type BriefTarget } from '@/lib/brief'

export type BriefView = { status: 'loading' } | { status: 'error' } | { status: 'ready'; brief: DecisionBrief }

/** 과거 사례를 만드는 중일 때 다시 부르는 간격과 횟수(묶음은 보통 6초 안에 다 만들어진다). */
export const CASES_RETRY_MS = 4000
const CASES_RETRIES = 5

interface Loaded {
  key: string
  view: BriefView
}

export function useDecisionBrief(target: BriefTarget | null): BriefView | null {
  const ecnId = target?.ecnId ?? null
  const recordId = target?.recordId ?? null
  // 한국 시간 날짜도 열쇠에 넣는다: D-n·'오늘'은 업무상 오늘로 세므로 자정이 지나면(상세를 다시 그릴 때) 다시 부른다
  const day = todayKst()
  const key = ecnId && recordId ? `${ecnId}|${recordId}|${day}` : null
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  /** 같은 대상을 몇 번째 불렀나(과거 사례를 만드는 중이면 늘려 다시 부른다). */
  const [attempt, setAttempt] = useState({ key, count: 0 })
  const count = attempt.key === key ? attempt.count : 0
  useEffect(() => {
    if (!ecnId || !recordId || !key) return
    const controller = new AbortController()
    let retry: ReturnType<typeof setTimeout> | undefined
    api.brief(ecnId, controller.signal).then(
      (brief) => {
        setLoaded({ key, view: { status: 'ready', brief } })
        if (brief.cases.status === 'building' && count < CASES_RETRIES) {
          retry = setTimeout(() => setAttempt({ key, count: count + 1 }), CASES_RETRY_MS)
        }
      },
      (error: unknown) => {
        if (controller.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) return
        // 다시 부르다 실패하면 보이던 도우미를 그대로 둔다(처음 부를 때만 실패 한 줄)
        setLoaded((prev) => (prev && prev.key === key && count > 0 ? prev : { key, view: { status: 'error' } }))
      },
    )
    return () => {
      controller.abort()
      if (retry) clearTimeout(retry)
    }
  }, [ecnId, recordId, key, count])
  if (!target || !key) return null
  if (!loaded || loaded.key !== key) return { status: 'loading' }
  if (loaded.view.status === 'ready' && !briefFor(loaded.view.brief, target)) return null
  return loaded.view
}
