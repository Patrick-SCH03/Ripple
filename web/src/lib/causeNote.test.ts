import { describe, expect, it } from 'vitest'
import { causeNote } from './causeNote'
import { CHANGE_CAUSES } from './request'

const all = (note: ReturnType<typeof causeNote>) =>
  note ? [note.title, ...note.items.map((item) => `${item.lead} ${item.text}`)].join(' ') : ''

describe('변경 원인 안내', () => {
  it('선주 요청: 계산 방식·어디를 보나·조정안 근거·하도급법 제16조 기한을 모두 남김', () => {
    const text = all(causeNote('owner_request'))
    for (const fact of [
      '지체상금 대신 인도일 조정',
      '건조계약 표준 서식',
      '가격·인도일 조정 대상',
      '인도 지연 카드',
      '조정안',
      '하도급법 제16조',
      '그 비율로',
      '15일 안 통지',
      '30일 안 조정',
      '증액 여부와 날짜',
    ]) {
      expect(text).toContain(fact)
    }
  })

  it('선급·규정: 계약 조항마다 다름 · 지체상금 그대로 · 최대 노출', () => {
    const text = all(causeNote('class_rule'))
    for (const fact of ['지체상금 그대로', '계약 조항마다', '최대 노출']) expect(text).toContain(fact)
  })

  it('그 밖의 원인·미입력은 안내 없음, 있는 안내는 제목 한 줄 + 굵은 구절 항목', () => {
    for (const cause of CHANGE_CAUSES) {
      const note = causeNote(cause)
      if (cause !== 'owner_request' && cause !== 'class_rule') {
        expect(note).toBeNull()
        continue
      }
      expect(note!.items.length).toBeGreaterThan(1)
      expect(note!.title).not.toMatch(/요\.?$|니다\.?$/)
      for (const item of note!.items) {
        expect(item.lead.length).toBeLessThan(item.lead.includes('제16조') ? 24 : 14)
        expect(item.text).not.toMatch(/요\.?$|니다\.?$|\.$/)
      }
    }
    expect(causeNote(null)).toBeNull()
  })
})
