// 소개 화면 꼬리표·아이콘 타일의 색(DESIGN.md 3절 뜻 그대로: primary = 정보, success = 승인, warning = 기한,
// agent = AI가 읽는 입력). 옅은 바탕은 토큰 색을 바탕색에 섞은 것 — 그 위 글자도 대비 4.5:1 이상.
import type { Tone } from './content'

export const TONE_TEXT: Record<Tone, string> = {
  primary: 'text-primary',
  success: 'text-success',
  warning: 'text-warning',
  agent: 'text-agent',
}

export const TONE_TINT: Record<Tone, string> = {
  primary: 'bg-[color-mix(in_oklab,var(--primary)_8%,var(--surface))]',
  success: 'bg-[color-mix(in_oklab,var(--success)_8%,var(--surface))]',
  warning: 'bg-[color-mix(in_oklab,var(--warning)_8%,var(--surface))]',
  agent: 'bg-[color-mix(in_oklab,var(--agent)_8%,var(--surface))]',
}

/** 알약 꼬리표: 옅은 바탕 + 같은 색 글자. */
export function pill(tone: Tone): string {
  return `inline-flex h-9 items-center rounded-full px-4 text-md font-bold ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`
}
