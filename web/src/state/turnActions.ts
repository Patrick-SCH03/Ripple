// 비서 차례에서 상세를 여는 동작(상세 보기·이 분석 열기·근거 칩). 훅이 아니라 렌더마다 지금 대화 기록으로 새로 만든다.
import type { AnalysisRequest, AnalysisResult, AssistantTurn } from '@/api/client'
import { latestVersion, nodeFor } from '@/lib/assistant'
import type { LayoutMode } from '@/lib/viewport'
import type { Entry } from './useAssistant'

interface Options {
  entries: Entry[]
  /** 분석을 상세에 연다(useOpenOrder.adopt). */
  adopt: (request: AnalysisRequest, result: AnalysisResult, manual: boolean) => void
  /** 비서 칸에서 상세로(useAssistantDock.showDetail). */
  showDetail: () => void
  /** 엔터티의 근거를 연다(useEvidence.selectNode). */
  selectNode: (id: string) => void
  mode: LayoutMode
  setAsideOpen: (open: boolean) => void
}

export interface TurnActions {
  openTurn: (turn: AssistantTurn) => void
  /** 차례의 엔터티 칩을 눌렀을 때 할 일(지도에 없는 엔터티면 undefined). */
  entityAction: (turn: AssistantTurn, entityId: string) => (() => void) | undefined
}

export function turnActions({ entries, adopt, showDetail, selectNode, mode, setAsideOpen }: Options): TurnActions {
  // 사용자가 차례를 직접 열면(상세 보기·이 분석 열기·근거 칩) 상세를 그 분석으로 맞추고 화면 세대를 올린다:
  // 이미 보이는 분석이어도 기다리는 비서 응답·목록 분석이 사용자가 고른 화면을 덮지 않게
  // 같은 분석에 사유를 나중에 기록했으면 그 마지막 것을 연다(원래 차례를 눌러도 기록한 사유가 되돌아가지 않게)
  const reopen = (turn: AssistantTurn) => {
    const turns = entries.flatMap((entry) => (entry.kind === 'turn' ? [entry.turn] : []))
    const latest = latestVersion(turn, turns)
    if (latest.request && latest.result) adopt(latest.request, latest.result, true)
  }
  const openTurn = (turn: AssistantTurn) => {
    reopen(turn)
    showDetail()
  }
  const entityAction = (turn: AssistantTurn, entityId: string) => {
    const node = turn.result ? nodeFor(entityId, turn.result.graph.nodes) : null
    if (!node) return undefined
    return () => {
      reopen(turn)
      selectNode(node)
      if (mode === 'desktop') setAsideOpen(false)
    }
  }
  return { openTurn, entityAction }
}
