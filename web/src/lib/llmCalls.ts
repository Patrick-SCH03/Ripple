// 관리자 'AI 호출 기록' 표시 계산(순수 함수, llmCalls.test.ts가 성질을 검사한다): 작업 이름·결과·걸린 시간·시각(KST)·요약.
import type { LlmCall } from '@/api/client'

const TASK_LABEL: Record<string, string> = {
  rewrite: '해석 보조',
  explain: '설명 고르기',
  extract: '문서 항목 추출',
  brief: '결정 도우미 고르기',
}

export function taskLabel(task: string): string {
  return TASK_LABEL[task] ?? task
}

/** 결과 한 마디: 성공 또는 '실패 · 종류'. */
export function outcomeLabel(call: Pick<LlmCall, 'ok' | 'error'>): string {
  return call.ok ? '성공' : call.error ? `실패 · ${call.error}` : '실패'
}

/** 걸린 시간: 1초 미만은 ms, 그 위는 소수 한 자리 초. */
export function latencyLabel(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}초`
}

const KST_SECONDS = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

/** 시각(ISO) → "10월 10일 01:31:59"(표 머리에 KST를 한 번 적는다). 읽지 못하면 '—'. */
export function callTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = Object.fromEntries(KST_SECONDS.formatToParts(date).map((part) => [part.type, part.value]))
  return `${parts.month}월 ${parts.day}일 ${parts.hour}:${parts.minute}:${parts.second}`
}

/** 요약 한 줄: '최근 3건 · 성공 2 · 실패 1'. 없으면 null. */
export function callSummary(calls: readonly Pick<LlmCall, 'ok'>[]): string | null {
  if (calls.length === 0) return null
  const ok = calls.filter((call) => call.ok).length
  return `최근 ${calls.length}건 · 성공 ${ok} · 실패 ${calls.length - ok}`
}
