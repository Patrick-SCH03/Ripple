import { describe, expect, it } from 'vitest'
import { KEEP_MAX, segments } from './segments'

describe('마디 나누기', () => {
  it('짧은 마디는 통째로, 긴 마디는 접을 수 있게', () => {
    const long = '판 두께 대신 보강재 추가(판 3장에 보강재 11개)'
    expect(segments(`D-7 · 11월 11일(수)까지 추가손실 0 · 다음 날부터 +1,867만원 · ${long}`)).toEqual([
      { text: 'D-7', keep: true },
      { text: '11월 11일(수)까지 추가손실 0', keep: true },
      { text: '다음 날부터 +1,867만원', keep: true },
      { text: long, keep: false },
    ])
  })

  it('마디를 이으면 원문 그대로(글을 바꾸지 않음)', () => {
    const text = '확인 필요 4 · 구매 1 · 생산관리 3 · 결재 중 해당 부서 확인'
    expect(segments(text).map((s) => s.text).join(' · ')).toBe(text)
  })

  it('구분자가 없으면 한 마디, 빈 글은 빈 목록', () => {
    expect(segments('경고')).toEqual([{ text: '경고', keep: true }])
    expect(segments('x'.repeat(KEEP_MAX + 1))[0]!.keep).toBe(false)
    expect(segments('')).toEqual([])
  })
})
