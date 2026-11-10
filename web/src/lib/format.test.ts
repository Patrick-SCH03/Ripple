import { describe, expect, it } from 'vitest'
import { addDays, daysBetween, formatDay, formatShortDay, isWeekend, shortcutLabel } from './format'

const WEEKDAY = new Intl.DateTimeFormat('ko-KR', { weekday: 'short', timeZone: 'UTC' })

describe('formatDay', () => {
  it('알려진 날짜', () => {
    expect(formatDay('2026-10-07')).toBe('10월 7일(수)')
    expect(formatDay('2026-01-01')).toBe('1월 1일(목)')
    expect(formatDay('2024-02-29')).toBe('2월 29일(목)')
    expect(formatDay('2026-12-31')).toBe('12월 31일(목)')
  })

  it('3년 동안 매일: 요일이 Intl과 같고 하루마다 한 칸씩 넘어감', () => {
    const start = Date.UTC(2025, 0, 1)
    let previous = ''
    for (let i = 0; i < 3 * 366; i += 1) {
      const date = new Date(start + i * 86_400_000)
      const iso = date.toISOString().slice(0, 10)
      const text = formatDay(iso)
      const weekday = text.slice(-2, -1)
      expect(text).toBe(`${date.getUTCMonth() + 1}월 ${date.getUTCDate()}일(${WEEKDAY.format(date)})`)
      if (previous) expect('일월화수목금토'.indexOf(weekday)).toBe(('일월화수목금토'.indexOf(previous) + 1) % 7)
      previous = weekday
    }
  })

  it('형식이 다르거나 없는 날짜는 받은 글 그대로', () => {
    for (const value of ['', '2026-2-3', '2026-02-30', '2026-13-01', '2026-10-07T00:00:00', '오늘']) {
      expect(formatDay(value)).toBe(value)
    }
  })
})

describe('daysBetween · formatShortDay', () => {
  it('달력 일수(해·달 넘김, 윤년 포함)', () => {
    expect(daysBetween('2026-10-20', '2026-10-31')).toBe(11)
    expect(daysBetween('2026-10-20', '2026-10-20')).toBe(0)
    expect(daysBetween('2026-12-25', '2027-01-02')).toBe(8)
    expect(daysBetween('2024-02-28', '2024-03-01')).toBe(2)
    expect(daysBetween('2026-10-31', '2026-10-20')).toBe(-11)
  })

  it('형식이 다르면 null, 짧은 날짜는 월/일', () => {
    expect(daysBetween('2026-02-30', '2026-03-01')).toBeNull()
    expect(daysBetween('오늘', '2026-03-01')).toBeNull()
    expect(formatShortDay('2026-10-07')).toBe('10/7')
    expect(formatShortDay('2026-13-01')).toBe('2026-13-01')
  })
})

describe('isWeekend', () => {
  it('토·일만 참(요일 글자와 같음), 형식이 다르면 거짓', () => {
    for (let i = 0; i < 14; i += 1) {
      const day = addDays('2026-10-19', i)
      expect(isWeekend(day)).toBe(/\((토|일)\)$/.test(formatDay(day)))
    }
    expect(isWeekend('2026-10-24')).toBe(true)
    expect(isWeekend('2026-10-23')).toBe(false)
    expect(isWeekend('2026-02-30')).toBe(false)
  })
})

describe('shortcutLabel', () => {
  it('맥은 ⌘, 그 밖은 Ctrl', () => {
    expect(shortcutLabel('K', 'MacIntel')).toBe('⌘K')
    expect(shortcutLabel('K', 'iPhone')).toBe('⌘K')
    expect(shortcutLabel('K', 'Win32')).toBe('Ctrl K')
    expect(shortcutLabel('K', 'Linux x86_64')).toBe('Ctrl K')
  })
})
