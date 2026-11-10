// ' · '로 이은 한 줄 글을 마디로 나눈다(DESIGN.md 4절 — 줄이 접혀도 금액·날짜가 홀로 떨어지지 않게).
// 짧은 마디(금액 · 날짜 · 'D-7' · '다음 날부터 +1,867만원')는 통째로 붙이고, 긴 마디(대안 이름처럼 칸보다 길 수 있는 글)는
// 낱말 사이에서만 접어 칸 밖으로 넘치지 않게 한다.

/** 통째로 붙일 마디의 최대 글자 수(큰 글자 기본 대화상자 칸 약 25자 — 넘으면 낱말 사이에서 접음). */
export const KEEP_MAX = 22

export interface Segment {
  text: string
  /** true = 마디 안에서 줄을 바꾸지 않음. */
  keep: boolean
}

export function segments(text: string, keepMax: number = KEEP_MAX): Segment[] {
  return text
    .split(' · ')
    .filter((part) => part.length > 0)
    .map((part) => ({ text: part, keep: part.length <= keepMax }))
}
