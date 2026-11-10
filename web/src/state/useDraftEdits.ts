// 초안을 고쳐 바로 다시 분석하기: 확정일·설계 승인 상태·적용 시작일·변경 원인, 그리고 가정 계산(발주 보류·후행 설치
// — 바로 전 결과와 나란히 '바뀐 점'을 보인다). 분석 세션(useAnalysisSession)의 초안 글 위에서 돈다.
import { useCallback } from 'react'
import type { AnalysisResult } from '@/api/client'
import {
  withCause,
  withConfirmOn,
  withDesignStatus,
  withEffectiveOn,
  withHold,
  withOutfitOnBoard,
  type ChangeCause,
  type DesignStatus,
  type ResultState,
} from '@/lib/request'

interface Options {
  draft: string
  /** 표시 중인 결과(없으면 null). */
  shown: { result: AnalysisResult } | null
  state: ResultState
  /** 초안 글을 바꾸고 바로 다시 분석한다. compare를 주면 가정 계산(바뀐 점을 보임). */
  rewrite: (next: string, compare?: { label: string; before: AnalysisResult } | null) => void
}

export interface DraftEdits {
  setConfirmOn: (date: string | null) => void
  setDesignStatus: (status: DesignStatus) => void
  setEffectiveOn: (date: string | null) => void
  setCause: (cause: ChangeCause | null) => void
  changeHold: (analysisId: string, poId: string, days: number | null) => void
  changeOnboard: (analysisId: string, on: boolean) => void
}

export function useDraftEdits({ draft, shown, state, rewrite }: Options): DraftEdits {
  const setConfirmOn = useCallback((date: string | null) => rewrite(withConfirmOn(draft, date)), [draft, rewrite])
  const setDesignStatus = useCallback(
    (status: DesignStatus) => rewrite(withDesignStatus(draft, status)),
    [draft, rewrite],
  )
  const setEffectiveOn = useCallback((date: string | null) => rewrite(withEffectiveOn(draft, date)), [draft, rewrite])
  const setCause = useCallback((cause: ChangeCause | null) => rewrite(withCause(draft, cause)), [draft, rewrite])

  // 이전 결과(다시 계산 중·거절·초안 수정 뒤)의 권고가 다른 초안에 섞이지 않게, 누른 순간에도 다시 확인한다
  const changeHold = useCallback(
    (analysisId: string, poId: string, days: number | null) => {
      if (!shown || state !== 'current' || shown.result.analysis_id !== analysisId) return
      const label = days === null ? `발주 ${poId} 보류 빼기` : `발주 ${poId} ${days}일 보류`
      rewrite(withHold(draft, poId, days), { label, before: shown.result })
    },
    [state, shown, draft, rewrite],
  )

  const changeOnboard = useCallback(
    (analysisId: string, on: boolean) => {
      if (!shown || state !== 'current' || shown.result.analysis_id !== analysisId) return
      const label = on ? '후행 설치로 계산' : '탑재를 기다리는 방식으로 계산'
      rewrite(withOutfitOnBoard(draft, on), { label, before: shown.result })
    },
    [state, shown, draft, rewrite],
  )

  return { setConfirmOn, setDesignStatus, setEffectiveOn, setCause, changeHold, changeOnboard }
}
