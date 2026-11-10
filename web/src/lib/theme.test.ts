import { describe, expect, it } from 'vitest'
import { readChoice, resolveTheme, THEME_KEY } from './theme'

describe('resolveTheme', () => {
  it('자동은 시스템 설정을 따르고, 직접 고르면 시스템과 상관없음', () => {
    expect(resolveTheme('auto', true)).toBe('dark')
    expect(resolveTheme('auto', false)).toBe('light')
    for (const system of [true, false]) {
      expect(resolveTheme('light', system)).toBe('light')
      expect(resolveTheme('dark', system)).toBe('dark')
    }
  })
})

describe('readChoice', () => {
  const store = (value: string | null) => ({ getItem: (key: string) => (key === THEME_KEY ? value : null) })

  it('저장된 값을 읽고, 모르는 값·없음은 밝게', () => {
    expect(readChoice(store('dark'))).toBe('dark')
    expect(readChoice(store('light'))).toBe('light')
    expect(readChoice(store('sepia'))).toBe('light')
    expect(readChoice(store(null))).toBe('light')
    expect(readChoice(undefined)).toBe('light')
  })

  it('저장소가 막혀 있어도(사생활 보호 창) 밝게', () => {
    const blocked = {
      getItem: () => {
        throw new DOMException('막힘', 'SecurityError')
      },
    }
    expect(readChoice(blocked)).toBe('light')
  })
})
