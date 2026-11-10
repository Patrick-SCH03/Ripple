// 숫자 카드 공용 클래스(DESIGN.md 2·6절 '숫자 카드'): 판단 요약 핵심 수치 · 결정 도우미 · 대화상자 맨 위 칸 · 결재·현황 수치 카드.
// 큰 숫자 크기(text-key · text-key-lg)는 cn(tailwind-merge)으로 합치지 않는다 — cn이 표준 이름이 아닌 크기를 글자 색과 같은
// 무리로 보고 색 클래스와 합칠 때 지운다. 큰 숫자 줄은 템플릿 문자열로 잇는다.

/** 큰 숫자 글자 색. */
export const VALUE_TONE = {
  neutral: 'text-foreground',
  danger: 'text-danger',
  success: 'text-success',
} as const

export type ValueTone = keyof typeof VALUE_TONE

/** 첫 줄 카드 틀(판단 요약 첫 줄 · 결정 도우미 큰 숫자 카드): 같은 줄 카드가 가장 긴 카드 높이로 늘어나도 내용은 세로 가운데(빈 아래 칸이 생기지 않게). */
export const HEAD_CARD = 'flex min-h-28 min-w-0 flex-col justify-center rounded-md border bg-surface px-5 py-3 [&_.text-key-lg]:whitespace-nowrap'
