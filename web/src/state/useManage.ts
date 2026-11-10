// 결재·현황 데이터(관리자, docs/records.md(기록·결재) 11절): 성과 기간을 바꾸면 다시 읽고, 다른 사람의 결재가 보이게 창을 다시 보거나
// 초점을 받을 때와 보이는 동안 일정 간격으로 다시 읽는다. 늦게 온 이전 기간의 응답은 버린다.
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, type ManageOverview } from '@/api/client'

const MANAGE_POLL_MS = 60_000

export interface ManageState {
  data: ManageOverview | null
  days: number | null
  setDays: (days: number | null) => void
  loading: boolean
  error: string | null
  reload: () => void
}

export function useManage(initialDays: number | null = 30): ManageState {
  const [days, setDays] = useState<number | null>(initialDays)
  const [data, setData] = useState<ManageOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  // 마지막으로 끝난 읽기의 열쇠(기간·판): 지금 열쇠와 다르면 읽는 중
  const [settled, setSettled] = useState<string | null>(null)
  const key = `${days ?? 'all'}:${version}`
  const latest = useRef(0)

  useEffect(() => {
    const ticket = ++latest.current
    const controller = new AbortController()
    api.manageOverview(days, controller.signal).then(
      (found) => {
        if (ticket !== latest.current) return
        setData(found)
        setError(null)
        setSettled(key)
      },
      (caught: unknown) => {
        if (ticket !== latest.current || controller.signal.aborted) return
        setError(caught instanceof ApiError ? caught.message : '결재·현황 불러오기 실패')
        setSettled(key)
      },
    )
    return () => controller.abort()
  }, [days, version, key])
  const loading = settled !== key

  const reload = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    const check = () => {
      if (document.visibilityState === 'visible') reload()
    }
    const timer = window.setInterval(check, MANAGE_POLL_MS)
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
    }
  }, [reload])

  return { data, days, setDays, loading, error, reload }
}
