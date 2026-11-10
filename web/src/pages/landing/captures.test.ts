import { describe, expect, it } from 'vitest'
import { formatDay } from '@/lib/format'
import indexHtml from '../../../index.html?raw'
import {
  APPROVAL_SHOT,
  ASSISTANT_SHOT,
  COST_SHOT,
  CURVE_SHOT,
  DEADLINE_CARD_SHOT,
  MAP_SHOT,
  OPTIONS_SHOT,
  PICTURED,
  REPORT_HEAD_SHOT,
  REPORT_SHOT,
  REPORT_SIGN_SHOT,
  SHIP_SHOT,
  SHIP_VIDEO,
  SHIP_WHOLE_SHOT,
  SHOT_VERSION,
  SUMMARY_SHOT,
  WEIGHT_SHOT,
  largestUrl,
  shotUrl,
  srcSet,
} from './captures'
import { SHOWCASE_DAY, SHOWCASE_TODAY, costText, deadlineExit, laterText, verdictText, weightText } from './example'

// 그림(public/landing)은 찍은 날의 화면이라 엔진이 바뀌어도 저절로 바뀌지 않는다. 그림 속 값(PICTURED)과 그림을 말로 옮긴 글
// (alt · 링크 미리보기 og:image:alt)의 숫자가 예시 기준일로 옮긴 example.json(지금 엔진)과 같은지 본다 — 실패하면 그림을 다시
// 찍고(docs/operations.md(서비스) 3절 '그림 다시 찍기') PICTURED·alt·SHOWCASE_DAY를 함께 고친다.

const OG_ALT = /<meta property="og:image:alt" content="([^"]+)"/.exec(indexHtml)?.[1] ?? ''
const SHOTS = [
  SHIP_WHOLE_SHOT,
  DEADLINE_CARD_SHOT,
  REPORT_HEAD_SHOT,
  REPORT_SHOT,
  REPORT_SIGN_SHOT,
  SUMMARY_SHOT,
  COST_SHOT,
  WEIGHT_SHOT,
  SHIP_SHOT,
  MAP_SHOT,
  CURVE_SHOT,
  OPTIONS_SHOT,
  APPROVAL_SHOT,
  ASSISTANT_SHOT,
]
const TEXTS: [string, string][] = [
  ...SHOTS.map((shot): [string, string] => [shot.src, shot.alt]),
  ['ship-wave', SHIP_VIDEO.label],
  ['og:image:alt', OG_ALT],
]
const noWeekday = (day: string) => day.replace(/\(.\)$/, '')
/** 그림 글에 나와도 되는 금액: 그림 속 값뿐. */
const MONEY = new Set<string>([
  PICTURED.total,
  PICTURED.later.amount,
  PICTURED.labor.money,
  PICTURED.material.value,
  ...(PICTURED.material.parts.match(/\d[\d,]*만원/g) ?? []),
])

describe('소개 화면 그림 속 값 = example.json(지금 엔진)', () => {
  it('찍은 날 = 예시 기준일(SHOWCASE_DAY) = 그림 주소 판(SHOT_VERSION — 하루 캐시된 옛 그림을 쓰지 않게)', () => {
    expect(PICTURED.day).toBe(SHOWCASE_DAY)
    expect(SHOT_VERSION).toBe(SHOWCASE_DAY)
    expect(shotUrl(SHIP_WHOLE_SHOT, 2)).toBe(`/landing/ship-whole@2x.webp?v=${SHOWCASE_DAY}`)
    expect(srcSet(SHIP_WHOLE_SHOT)).toContain(`/landing/ship-whole@4x.webp?v=${SHOWCASE_DAY} 4000w`)
    expect(largestUrl(MAP_SHOT)).toBe(`/landing/map@3x.webp?v=${SHOWCASE_DAY}`)
    expect(SHIP_VIDEO.webm).toBe(`/landing/ship-wave.webm?v=${SHOWCASE_DAY}`)
  })

  it('3D 영상은 정지 그림(SHIP_SHOT)과 같은 화면 비율 16:9', () => {
    expect(SHIP_SHOT.width / SHIP_SHOT.height).toBeCloseTo(16 / 9, 3)
  })

  it('총변경비용·범위·D-n·결정 기한·다음 날 추가손실·출구 지연·곡선 기간이 example.json 값', () => {
    const verdict = verdictText(SHOWCASE_TODAY)
    const later = laterText(SHOWCASE_TODAY)
    expect({ total: PICTURED.total, range: PICTURED.range, dDay: PICTURED.dDay, deadline: PICTURED.deadline }).toEqual({
      total: verdict.total,
      range: verdict.range,
      dDay: verdict.dDay,
      deadline: verdict.deadline,
    })
    expect(PICTURED.later).toEqual({ on: later?.on, amount: later?.amount })
    expect(PICTURED.exit).toEqual(deadlineExit(SHOWCASE_TODAY))
    expect(SHOWCASE_TODAY.horizon_end).not.toBeNull()
    expect(PICTURED.horizon).toEqual({
      from: formatDay(SHOWCASE_TODAY.as_of),
      to: formatDay(SHOWCASE_TODAY.horizon_end ?? ''),
    })
  })

  it('판단 요약 첫 줄(추가 공수·추가 재료비)과 중량 변화가 example.json 값', () => {
    const cost = costText(SHOWCASE_TODAY)
    expect(PICTURED.labor).toEqual({ hours: cost.hours, money: cost.laborMoney, works: cost.works })
    expect(PICTURED.material).toEqual({ value: cost.material, parts: cost.materialParts, ordered: cost.ordered })
    expect(PICTURED.weight).toBe(weightText(SHOWCASE_TODAY))
  })

  it('링크 미리보기 글이 있음(index.html og:image:alt)', () => {
    expect(OG_ALT).toContain(PICTURED.labor.hours)
    expect(OG_ALT).toContain(PICTURED.material.value)
  })

  it.each(TEXTS)('%s: 글 속 금액·MH·D-n·날짜·출구 지연·중량이 그림 속 값뿐', (_name, text) => {
    for (const token of text.match(/\d[\d,]*만원/g) ?? []) expect(MONEY).toContain(token)
    for (const token of text.match(/\d[\d,.]* MH/g) ?? []) expect(token).toBe(PICTURED.labor.hours)
    for (const token of text.match(/(?<![\w-])D-\d+/g) ?? []) expect(token).toBe(PICTURED.dDay)
    const days = new Set([PICTURED.deadline, PICTURED.later.on, PICTURED.horizon.from, PICTURED.horizon.to].map(noWeekday))
    for (const token of text.match(/\d+월 \d+일/g) ?? []) expect(days).toContain(token)
    const change = /(\d+)일 → (\d+)일/.exec(text)
    if (change) expect([Number(change[1]), Number(change[2])]).toEqual([PICTURED.exit.asOf, PICTURED.exit.atDeadline])
    const exit = /구역 출구 (?:예상 최대 )?지연 (\d+)일/.exec(text)
    if (exit) expect(Number(exit[1])).toBe(PICTURED.exit.asOf)
    const delta = /[+−]\d+\.\d+t/.exec(text)
    if (delta) expect(delta[0]).toBe(PICTURED.weight)
  })

  it('숫자를 말하는 그림 글은 지금 값을 담음(핵심 수치·결정 기한 카드·곡선·결재·검토서·중량)', () => {
    expect(SUMMARY_SHOT.alt).toContain(`총변경비용 ${PICTURED.total} · 추가 공수 ${PICTURED.labor.hours} ≈ ${PICTURED.labor.money} · 추가 재료비 ${PICTURED.material.value}`)
    expect(SUMMARY_SHOT.alt).toContain(PICTURED.total)
    expect(DEADLINE_CARD_SHOT.alt).toContain(PICTURED.later.amount)
    expect(CURVE_SHOT.alt).toContain(PICTURED.later.amount)
    expect(APPROVAL_SHOT.alt).toContain(`미루면 ${PICTURED.later.on}부터 +${PICTURED.later.amount}`)
    expect(REPORT_SHOT.alt).toContain(PICTURED.labor.hours)
    expect(WEIGHT_SHOT.alt).toContain(PICTURED.weight)
  })
})
