import { describe, expect, it } from 'vitest'
import { MEASURED } from './content'
import { countFrame, zeroed } from './motion'

describe('countFrame', () => {
  it('끝(t = 1)은 원래 글과 같다 — 소수 자리·천 단위 쉼표·단위 그대로', () => {
    for (const text of ['0.1초', '98.3%', '135/135', '1,500열', '12,345.6만원', ...MEASURED.map((m) => m.value)]) {
      expect(countFrame(text, 1)).toBe(text)
    }
  })

  it('처음(t = 0)은 0, 도중은 끝 값보다 작고 끝으로 갈수록 커진다', () => {
    expect(countFrame('135/135', 0)).toBe('0/135')
    expect(countFrame('98.3%', 0)).toBe('0.0%')
    const values = [0.2, 0.5, 0.8].map((t) => Number.parseFloat(countFrame('98.3%', t)))
    expect(values.every((v, i) => v < 98.3 && (i === 0 || v > values[i - 1]))).toBe(true)
  })

  it('숫자가 없으면 그대로', () => {
    expect(countFrame('빠짐없이', 0.5)).toBe('빠짐없이')
  })
})

describe('zeroed', () => {
  it('첫 숫자의 자리만 0으로 바꾸고 단위·뒤 숫자는 그대로 둔다', () => {
    expect(zeroed('0.1초')).toBe('0.0초')
    expect(zeroed('98.3%')).toBe('00.0%')
    expect(zeroed('135/135')).toBe('000/135')
    expect(zeroed('1,500열')).toBe('0,000열')
  })

  it('숫자가 없으면 그대로', () => {
    expect(zeroed('빠짐없이')).toBe('빠짐없이')
  })

  it('잰 값은 모두 숫자로 시작해 0부터 올릴 수 있다(글자 수는 같다)', () => {
    for (const item of MEASURED) {
      expect(item.value).toMatch(/^\d/)
      expect(zeroed(item.value)).toHaveLength(item.value.length)
    }
  })
})
