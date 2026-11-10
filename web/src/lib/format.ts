// 화면 표기(DESIGN.md 8절). 날짜는 달력 날짜(YYYY-MM-DD) 그대로 다루고 시간대를 바꾸지 않는다.
const WEEKDAYS = '일월화수목금토'
const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/

/** 달력 날짜 → UTC 자정 시각(ms). 형식이 다르거나 없는 날짜면 null. */
function dayValue(iso: string): number | null {
  const match = ISO_DAY.exec(iso)
  if (!match) return null
  const [year, month, day] = match.slice(1).map(Number)
  const date = new Date(0)
  date.setUTCFullYear(year, month - 1, day)
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null
  return date.getTime()
}

/** "2026-10-07" → "10월 7일(수)". 형식이 다르거나 없는 날짜(2월 30일 등)면 받은 글 그대로. */
export function formatDay(iso: string): string {
  const value = dayValue(iso)
  if (value === null) return iso
  const date = new Date(value)
  return `${date.getUTCMonth() + 1}월 ${date.getUTCDate()}일(${WEEKDAYS[date.getUTCDay()]})`
}

/** 토·일인가(달력 날짜의 요일 — 날짜를 만들지 않고 받은 날의 요일만 본다). 형식이 다르거나 없는 날짜면 false. */
export function isWeekend(iso: string): boolean {
  const value = dayValue(iso)
  if (value === null) return false
  const weekday = new Date(value).getUTCDay()
  return weekday === 0 || weekday === 6
}

/** "2026-10-07" → "10/7"(그래프 축처럼 짧게). 형식이 다르면 받은 글 그대로. */
export function formatShortDay(iso: string): string {
  const value = dayValue(iso)
  if (value === null) return iso
  const date = new Date(value)
  return `${date.getUTCMonth() + 1}/${date.getUTCDate()}`
}

/** 두 달력 날짜 사이의 일수(to − from). 하나라도 형식이 다르면 null. */
export function daysBetween(from: string, to: string): number | null {
  const start = dayValue(from)
  const end = dayValue(to)
  return start === null || end === null ? null : Math.round((end - start) / 86_400_000)
}

/** 달력 날짜에 일수를 더한 날짜("2026-10-31" + 1 → "2026-11-01"). 형식이 다르면 받은 글 그대로. */
export function addDays(iso: string, days: number): string {
  const value = dayValue(iso)
  return value === null ? iso : new Date(value + days * 86_400_000).toISOString().slice(0, 10)
}

/** 단축키 표기: 맥은 ⌘, 그 밖은 Ctrl. */
export function shortcutLabel(key: string, platform: string): string {
  return /Mac|iPhone|iPad/i.test(platform) ? `⌘${key}` : `Ctrl ${key}`
}
