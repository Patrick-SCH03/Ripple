// 통보 기록(계약 1.28.0, docs/records.md(기록·결재) 7절): 알림 초안마다 '보냄 → 수령 확인 → 회신'을 사람이 날짜와 함께 남긴다.
// 앱은 메일을 보내지 않으므로 보낸 사실·회신은 사람이 적고, 그 줄은 감사 사슬에 남아 고칠 수 없다(잘못 적으면 새 줄로).
// 여기서는 감사 줄에서 받는 쪽마다 단계별 마지막 날짜를 모으고 한 줄 문장으로 만든다(순수 함수, notices.test.ts).
import type { AuditEntry, NoticeStep, NotificationTarget } from '@/api/client'
import { daysBetween, formatDay } from './format'

export const NOTICE_STEPS: readonly NoticeStep[] = ['sent', 'acknowledged', 'replied']

export const NOTICE_STEP_LABEL: Record<NoticeStep, string> = {
  sent: '보냄',
  acknowledged: '수령 확인',
  replied: '회신 받음',
}

/** 받는 쪽 하나의 단계별 마지막 날짜(없으면 그 단계 기록 없음). */
export type NoticeState = Partial<Record<NoticeStep, string>>

/** 받는 쪽 열쇠(알림 초안의 draftKey와 같은 꼴). */
export function noticeKey(target: NotificationTarget, recipientId: string): string {
  return `${target}:${recipientId}`
}

/** 감사 줄 → 받는 쪽마다 단계별 마지막 날짜(같은 단계를 다시 적으면 나중 줄이 이긴다). */
export function noticeStates(audit: readonly AuditEntry[]): Map<string, NoticeState> {
  const states = new Map<string, NoticeState>()
  for (const entry of [...audit].sort((a, b) => a.seq - b.seq)) {
    const log = entry.detail.notice
    if (entry.action !== 'notice' || !log) continue
    const key = noticeKey(log.target, log.recipient_id)
    states.set(key, { ...states.get(key), [log.step]: log.on })
  }
  return states
}

/**
 * 한 줄 상태: 마지막으로 한 단계와 날짜, 보낸 뒤 확인·회신이 없으면 경과일.
 * 예: '보냄 10월 21일(수) · 3일째 수령 확인 없음', '회신 받음 10월 24일(토)'.
 */
export function noticeLine(state: NoticeState | undefined, today: string): string {
  if (!state || NOTICE_STEPS.every((step) => !state[step])) return '통보 기록 없음'
  const last = [...NOTICE_STEPS].reverse().find((step) => state[step]) as NoticeStep
  const head = `${NOTICE_STEP_LABEL[last]} ${formatDay(state[last] as string)}`
  if (last !== 'sent') return head
  const days = daysBetween(state.sent as string, today)
  return days !== null && days > 0 ? `${head} · ${days}일째 수령 확인 없음` : head
}

/** 이력 탭의 감사 줄 메모(받는 쪽 · 단계 · 날짜 · 메모). */
export function noticeNote(log: NonNullable<AuditEntry['detail']['notice']>, targetLabel: string): string {
  const memo = log.note ? ` — ${log.note}` : ''
  return `${targetLabel} ${log.recipient_id} · ${NOTICE_STEP_LABEL[log.step]} ${formatDay(log.on)}${memo}`
}
