// 분석 요청(docs/engine.md(전파)·docs/engine.md(비용·일정)): 1단계 영향 보고와 2단계 분석. 지금 지도에 묶인 요청이다.
import { call, download } from './http'
import type { AnalysisNotices, AnalysisResult, ImpactReport, NotificationTarget } from './types'

export const analysisApi = {
  impacts: (request: unknown, signal?: AbortSignal) =>
    call<ImpactReport>('/impacts', { method: 'POST', body: JSON.stringify(request), signal }),
  analyses: (request: unknown, signal?: AbortSignal) =>
    call<AnalysisResult>('/analyses', { method: 'POST', body: JSON.stringify(request), signal }),
  /** 보던 분석의 요청 그대로 → 분석 결과 엑셀(서버가 같은 요청을 다시 분석해 씀, 대안 비교 시트 포함). */
  exportAnalysis: (request: unknown, signal?: AbortSignal) =>
    download('/analyses/export', { method: 'POST', body: JSON.stringify(request), signal }),
  /** 1.37.0 보던 분석의 요청 그대로 → 알림 초안(AI 비서와 같은 규칙, 작업반 번역 포함). target이면 그 받는 쪽만. */
  analysisNotices: (request: unknown, target?: NotificationTarget, signal?: AbortSignal) =>
    call<AnalysisNotices>(target ? `/analyses/notices?target=${target}` : '/analyses/notices', {
      method: 'POST',
      body: JSON.stringify(request),
      signal,
    }),
}
