// 관리 요청: 관리자 결재·현황(결재함·현황·성과)과 AI 호출 기록. 지도와 무관한 동기화 요청이다.
import { call, download } from './http'
import type { LlmCalls, ManageOverview, NcrSummary } from './types'

const daysQuery = (days: number | null) => (days === null ? '' : `?days=${days}`)

export const manageApi = {
  llmCalls: () => call<LlmCalls>('/llm/calls', {}, 'sync'),
  /** 관리자 결재·현황(결재함·현황·성과). days = 성과 기간(null = 전체). */
  manageOverview: (days: number | null, signal?: AbortSignal) =>
    call<ManageOverview>(`/manage/overview${daysQuery(days)}`, { signal }, 'sync'),
  /** 결재 대장 엑셀(결재함 줄 · 현황 · 상태별 · 블록별). days는 결재·현황 화면과 같은 기간. */
  exportManage: (days: number | null) => download(`/manage/export${daysQuery(days)}`, {}, 'sync'),
  /** 합성 NCR 요약(유형별 건수, 합성 묶음(시연)). 실데이터 모드면 available = false와 이유. */
  ncrSummary: (signal?: AbortSignal) => call<NcrSummary>('/ncrs/summary', { signal }, 'sync'),
}
