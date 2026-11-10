// 결재 띠의 흐린 단추 이유 묶기.
import { ACTION_LABEL, type ActionView } from '@/lib/records'

/** 흐린 단추의 이유를 같은 이유끼리 한 줄로: '승인·반려·보류: …'. */
export function groupReasons(actions: ActionView[]): { labels: string; reason: string }[] {
  const byReason = new Map<string, string[]>()
  for (const view of actions) {
    if (view.enabled || !view.reason) continue
    byReason.set(view.reason, [...(byReason.get(view.reason) ?? []), ACTION_LABEL[view.action]])
  }
  return [...byReason].map(([reason, labels]) => ({ labels: labels.join('·'), reason }))
}
