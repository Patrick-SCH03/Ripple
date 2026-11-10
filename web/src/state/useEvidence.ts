// 근거 요청: 엔터티를 고르면 상세의 영향 지도에서 그 근거를 연다(같은 엔터티를 다시 골라도, 좁은 화면에서 상세가 새로
// 열려도 — 요청 순번을 올린다). 영향 지도는 늘 상세에 있으므로 상세 탭은 바꾸지 않고, 근거 제목에 초점이 가며 그 자리로
// 내려간다.
import { useCallback, useState } from 'react'

export interface Evidence {
  /** 근거를 연 순번(상세가 바뀔 때마다 그 근거로 내려간다). */
  request: number
  /** 엔터티를 고르고 그 근거를 연다. */
  selectNode: (id: string) => void
}

export function useEvidence(
  select: (id: string | null) => void,
  compact: boolean,
  showTab: (tab: 'detail') => void,
): Evidence {
  const [request, setRequest] = useState(0)
  const selectNode = useCallback(
    (id: string) => {
      select(id)
      setRequest((n) => n + 1)
      if (compact) showTab('detail')
    },
    [select, compact, showTab],
  )
  return { request, selectNode }
}
