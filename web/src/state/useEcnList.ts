// 결재 상태 목록(docs/records.md(기록·결재)): 설계변경마다 마지막 상태·개정. 다시 읽기는 버전을 올려 효과가 다시 돌게 한다.
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type EcnListItem } from '@/api/client'

export interface EcnListState {
  items: EcnListItem[]
  /** 목록을 한 번이라도 읽었는가. */
  ready: boolean
  /** 목록 읽기가 실패 중이면 그 장애의 순번(성공 뒤 다시 실패할 때마다 1씩), 성공하면 null. */
  listFailure: number | null
  reloadList: () => void
}

export function useEcnList(): EcnListState {
  const [items, setItems] = useState<EcnListItem[]>([])
  const [ready, setReady] = useState(false)
  const [listFailure, setListFailure] = useState<number | null>(null)
  const failures = useRef(0)
  const failing = useRef<number | null>(null) // 지금 이어지는 장애의 순번
  const [listVersion, setListVersion] = useState(0)

  useEffect(() => {
    let live = true
    api.ecns().then(
      (list) => {
        if (!live) return
        setItems(list.ecns)
        setReady(true)
        failing.current = null
        setListFailure(null)
      },
      () => {
        // 목록 상태는 보조 정보: 실패해도 샘플 목록은 그대로 쓰되, 결재 대기가 없는 것처럼 보이지 않게 알린다
        if (!live) return
        setReady(true)
        // 성공 → 실패로 바뀔 때만 순번을 올린다: 장애가 이어지는 동안 주기 확인마다 닫은 알림이 다시 뜨지 않게
        if (failing.current === null) {
          failures.current += 1
          failing.current = failures.current
        }
        setListFailure(failing.current)
      },
    )
    return () => {
      live = false
    }
  }, [listVersion])

  const reloadList = useCallback(() => setListVersion((v) => v + 1), [])
  return { items, ready, listFailure, reloadList }
}
