// 분석 기준(설계변경 목록이 없는 지도): 기본값(지도의 호선 전부 · 자료 기준일)에서 시작하고 비서 맥락의 유일한 출처가
// 된다. 기본 지도(샘플 목록이 있는 지도)는 고른 설계변경의 요청이 기준이다. 화면을 처음 열 때의 지도로 정한다
// (지도가 바뀌면 업무 화면이 통째로 새로 열린다).
import { useState } from 'react'
import type { TurnContext } from '@/api/client'
import { turnContext } from '@/lib/assistant'
import { basisContext, defaultBasis, todayKst, type Basis } from '@/lib/basis'
import type { RequestContext } from '@/lib/request'
import { samplesMap } from '@/lib/workspace'
import type { AnalysisSession } from './useAnalysisSession'
import type { WorkspaceState } from './useWorkspace'

export interface AnalysisBasis {
  /** 분석 기준(기본 지도면 null). */
  basis: Basis | null
  /** 비서·문서 접수의 맥락(호선·기준일·확정일). 없으면 보내지 않는다. */
  context: TurnContext | null
  /** 위 막대에 보일 요청 값: 표시 중인 결과 → 분석 기준 → 초안 순. */
  shown: RequestContext
  /** 기준을 바꾼다. */
  change: (next: Basis) => void
}

export function useBasis(workspace: WorkspaceState, session: AnalysisSession): AnalysisBasis {
  const active = workspace.active
  const [basis, setBasis] = useState<Basis | null>(() =>
    active && !samplesMap(workspace.list, active) ? defaultBasis(active, todayKst()) : null,
  )
  // 분석 기준을 바꾸면 화면 세대를 올린다: 이전 기준으로 보낸 비서 응답이 상세를 덮지 않게
  const change = (next: Basis) => {
    session.generation.bump()
    setBasis(next)
  }
  return {
    basis,
    context: basis ? basisContext(basis) : turnContext(session.draftContext),
    shown:
      session.shownContext ??
      (basis
        ? { ecnId: null, title: null, shipIds: basis.shipIds, asOf: basis.asOf, confirmOn: null, horizonDays: null }
        : session.draftContext),
    change,
  }
}
