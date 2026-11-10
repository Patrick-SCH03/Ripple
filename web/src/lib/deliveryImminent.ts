// 인도 임박 띠(현업 의견 '인도 시점이 촉박하면 일정 최우선'): 띠만 보이고
// 대안 순위·최적 조합·날짜별 최저 비용 대안·금액 계산은 그대로다(관문 영향 없음).
// 켜는 조건: ① 요청안이 인도를 늦춤(늘어난 인도 지연 > 0) ② 확정일 → 계획 인도일 남은 날 ≤ 60일(가정).
// 분석 결과(계약 1.32.0)에는 계획 인도일이 없어(인도는 늘어난 지연·예상 지연 일수만, DeliveryImpact) 지금은 ①만 쓴다 —
// 결과에 계획 인도일이 생기면 그때 ②(확정일 → 계획 인도일 ≤ 60일, 가정)를 조건에 더한다(쓰지 않는 상수는 두지 않는다).
import type { AnalysisResult } from '@/api/client'

export const DELIVERY_IMMINENT_TEXT = '인도 임박 — 일정(인도·구역 출구 지연) 먼저 확인'

/** 띠 글: 켜지지 않으면 null. 세부는 왜 켜졌는지와 계산은 그대로라는 것. */
export function deliveryImminent(
  result: Pick<AnalysisResult, 'schedule'>,
): { title: string; detail: string } | null {
  const added = result.schedule.delivery?.added_delay_days ?? 0
  if (added <= 0) return null
  return {
    title: DELIVERY_IMMINENT_TEXT,
    detail: `이 변경으로 인도 ${added}일 지연 · 대안 순위·금액 계산은 그대로`,
  }
}
