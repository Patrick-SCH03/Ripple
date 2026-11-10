import { describe, expect, it } from 'vitest'
import type { IntakeIssue, IntakeItem, SlotSpec } from '@/api/client'
import {
  EMPTY_ROW,
  acceptClean,
  canConfirm,
  documentParts,
  fillText,
  fragmentParts,
  itemTone,
  numberSlots,
  parsePositive,
  problemsByItem,
  proposalSummary,
  readiness,
  isUnsupported,
  rowProblem,
  seedFor,
  staleOnRetarget,
  targetSlot,
  toDecision,
  type RowState,
} from './intake'

const THICKNESS: SlotSpec[] = [
  { name: 'part_ids', kind: 'parts', label: '두께를 바꿀 부재', calibrated: true, from_map: false, part_kinds: [], required: true },
  { name: 'from_mm', kind: 'millimeter', label: '지금 두께', calibrated: false, from_map: true, part_kinds: [], required: true },
  { name: 'to_mm', kind: 'millimeter', label: '바꿀 두께', calibrated: false, from_map: false, part_kinds: [], required: true },
]
const TEXT = 'B31P 판 PL-002 두께를 17mm에서 20mm로 변경'
const at = (word: string) => ({ start: TEXT.indexOf(word), end: TEXT.indexOf(word) + word.length, text: word })

function item(overrides: Partial<IntakeItem> = {}): IntakeItem {
  return {
    item_id: 'I1',
    source: { start: 0, end: TEXT.length, text: TEXT },
    extractor: 'rule',
    draft: {
      text: TEXT,
      ship_ids: ['S-001'],
      op: { value: 'thickness', method: 'rule', span: at('두께') },
      slots: {
        part_ids: { value: ['S-001:B31P-PL-002'], method: 'decision', span: at('B31P 판 PL-002') },
        from_mm: { value: 17, method: 'map' },
        to_mm: { value: 20, method: 'rule', span: at('20mm') },
      },
    },
    slots: THICKNESS,
    candidates: [],
    issues: [],
    ...overrides,
  }
}

const issue = (code: IntakeIssue['code'], slot: string | null = null, message = `${code} 문제`): IntakeIssue => ({
  code,
  slot,
  message,
})
const row = (patch: Partial<RowState>): RowState => ({ ...EMPTY_ROW, ...patch })

describe('항목 상태', () => {
  it('막는 문제·초안 없음은 확인 필요, AI·추정 값이나 가벼운 문제는 살펴보기, 나머지는 깨끗함', () => {
    expect(itemTone(item())).toBe('clean')
    expect(itemTone(item({ draft: null }))).toBe('blocked')
    expect(itemTone(item({ issues: [issue('target_ambiguous', 'part_ids')] }))).toBe('blocked')
    expect(itemTone(item({ issues: [issue('from_mismatch', 'from_mm')] }))).toBe('look')
    const ai = item()
    ai.draft!.slots!.to_mm = { value: 20, method: 'llm' }
    expect(itemTone(ai)).toBe('look')
  })

  it('대상 칸은 보정 부재 묶음, 수치 칸은 지도 값이 아닌 mm·수량', () => {
    expect(targetSlot(item())?.name).toBe('part_ids')
    expect(numberSlots(item()).map((slot) => slot.name)).toEqual(['to_mm'])
    expect(targetSlot(item({ slots: [] }))).toBeNull()
  })

  it('칸 값 글: 목록은 쉼표, 수는 둘째 자리까지, 없으면 null', () => {
    expect(fillText({ value: ['a', 'b'], method: 'rule' })).toBe('a, b')
    expect(fillText({ value: 20, method: 'rule' })).toBe('20')
    expect(fillText({ value: 17.456, method: 'rule' })).toBe('17.46')
    expect(fillText(null)).toBeNull()
  })

  it('수치 입력: 양수만, 단위·쉼표·음수·0은 거부', () => {
    expect(parsePositive(' 20 ')).toBe(20)
    expect(parsePositive('20.5')).toBe(20.5)
    for (const bad of ['', '0', '-1', '20mm', '1,000', 'abc', '1e3']) expect(parsePositive(bad)).toBeNull()
  })
})

describe('사람 결정 → 확정 요청', () => {
  it('정하지 않은 줄은 막고, 뺌은 언제나 보낼 수 있음', () => {
    expect(rowProblem(item(), EMPTY_ROW)).toMatch(/선택 필요/)
    expect(toDecision(item({ draft: null, issues: [issue('unreadable')] }), row({ action: 'drop' }))).toEqual({
      item_id: 'I1',
      action: 'drop',
      values: {},
    })
  })

  it('맞음: 막는 문제가 남으면 그 문제 글, 없으면 accept', () => {
    expect(rowProblem(item({ issues: [issue('value_missing', 'to_mm', '바꿀 두께를 정하지 못했어요')] }), row({ action: 'accept' }))).toBe(
      '바꿀 두께를 정하지 못했어요',
    )
    expect(toDecision(item(), row({ action: 'accept' }))).toEqual({ item_id: 'I1', action: 'accept', values: {} })
    expect(rowProblem(item({ draft: null, slots: [] }), row({ action: 'accept' }))).toMatch(/비서로/)
  })

  it('항목 사이 문제(같은 변경·겹침)는 화면에서 막지 않음(서버가 남은 항목끼리 본다)', () => {
    expect(rowProblem(item({ issues: [issue('duplicate')] }), row({ action: 'accept' }))).toBeNull()
  })

  it('고침: 대상을 고르면 대상·지금 값 문제가 풀림, 다른 칸 문제는 남음', () => {
    const ambiguous = item({
      issues: [issue('target_ambiguous', 'part_ids'), issue('value_missing', 'from_mm')],
      candidates: [
        { part_id: 'S-001:B31P-PL-002', label: 'PL-002', probability: 0.5 },
        { part_id: 'S-001:B31P-PL-005', label: 'PL-005', probability: 0.4 },
      ],
    })
    ambiguous.draft!.slots = { to_mm: { value: 20, method: 'rule' } }
    const chosen = row({ action: 'edit', partIds: ['S-001:B31P-PL-005'] })
    expect(rowProblem(ambiguous, chosen)).toBeNull()
    expect(toDecision(ambiguous, chosen)).toEqual({
      item_id: 'I1',
      action: 'edit',
      part_ids: ['S-001:B31P-PL-005'],
      values: {},
    })
    const stillMissing = item({ issues: [issue('target_ambiguous', 'part_ids'), issue('value_missing', 'to_mm', '바꿀 두께가 없어요')] })
    expect(rowProblem(stillMissing, row({ action: 'edit', partIds: ['S-001:B31P-PL-005'] }))).toBe('바꿀 두께가 없어요')
    const disagree = item({ issues: [issue('llm_rule_disagree', 'to_mm', 'AI와 규칙이 달라요')] })
    expect(rowProblem(disagree, row({ action: 'edit', partIds: ['S-001:B31P-PL-005'] }))).toBe('AI와 규칙이 달라요')
  })

  it('고침: 수치를 바꾸면 그 칸의 값 문제만 풀림', () => {
    const disagree = item({ issues: [issue('llm_rule_disagree', 'to_mm', 'AI와 규칙이 달라요')] })
    const edited = row({ action: 'edit', values: { to_mm: '22' } })
    expect(rowProblem(disagree, edited)).toBeNull()
    expect(toDecision(disagree, edited)).toEqual({ item_id: 'I1', action: 'edit', part_ids: null, values: { to_mm: 22 } })
    const other = item({ issues: [issue('value_missing', 'from_mm', '지금 두께가 없어요')] })
    expect(rowProblem(other, edited)).toBe('지금 두께가 없어요')
  })

  it('고침: 바뀐 게 없거나 읽지 못하는 수치는 막음', () => {
    expect(rowProblem(item(), row({ action: 'edit', values: { to_mm: '20' } }))).toMatch(/맞음 선택/)
    expect(rowProblem(item(), row({ action: 'edit', partIds: ['S-001:B31P-PL-002'] }))).toMatch(/맞음 선택/)
    expect(rowProblem(item(), row({ action: 'edit', values: { to_mm: '20mm' } }))).toMatch(/0보다 큰 숫자/)
  })

  it('비서로: 초안을 마치기 전엔 막고, 마치면 그 초안으로 고침', () => {
    expect(rowProblem(item(), row({ action: 'handoff' }))).toMatch(/비서에서/)
    const draft = item().draft!
    expect(toDecision(item({ draft: null, slots: [] }), row({ action: 'handoff', draft }))).toEqual({
      item_id: 'I1',
      action: 'edit',
      draft,
      values: {},
    })
  })
})

describe('확정 가능 여부', () => {
  const clean = item()
  const blocked = item({ item_id: 'I2', issues: [issue('target_unresolved', 'part_ids', '대상을 못 찾았어요')] })

  it('모든 줄을 정하고 남길 항목이 있어야 확정', () => {
    const none = readiness([clean, blocked], {})
    expect(canConfirm(none)).toBe(false)
    expect(none.reasons).toHaveLength(2)
    const decided = readiness([clean, blocked], { I1: row({ action: 'accept' }), I2: row({ action: 'drop' }) })
    expect(canConfirm(decided)).toBe(true)
    expect([decided.kept, decided.dropped]).toEqual([1, 1])
    const allDropped = readiness([clean], { I1: row({ action: 'drop' }) })
    expect(canConfirm(allDropped)).toBe(false)
    expect(allDropped.reasons[0]).toMatch(/분석할 항목 없음/)
  })

  it('막힌 줄을 그대로 맞음으로 두면 그 줄 이유가 항목 ID와 함께', () => {
    const state = readiness([clean, blocked], { I1: row({ action: 'accept' }), I2: row({ action: 'accept' }) })
    expect(state.reasons).toEqual(['I2: 대상을 못 찾았어요'])
  })

  it('깨끗한 줄 모두 맞음: 막힌 줄과 이미 정한 줄은 그대로', () => {
    const rows = acceptClean([clean, blocked, item({ item_id: 'I3' })], { I3: row({ action: 'drop' }) })
    expect(rows.I1.action).toBe('accept')
    expect(rows.I2).toBeUndefined()
    expect(rows.I3.action).toBe('drop')
  })

  it('요약 글', () => {
    expect(proposalSummary({ items: [clean, blocked] })).toBe('항목 2개 · 확인 필요 1')
    expect(proposalSummary({ items: [] })).toBe('항목 0개')
  })
})

describe('원문 강조', () => {
  it('항목 조각과 사이 글로 나누고, 이어 붙이면 원문 그대로(겹침·밖 위치는 건너뜀)', () => {
    const doc = '머리말\n가. 첫 변경\n나. 둘째 변경\n끝'
    const first = { item_id: 'I1', source: { start: 4, end: 11, text: doc.slice(4, 11) } }
    const second = { item_id: 'I2', source: { start: 12, end: 20, text: doc.slice(12, 20) } }
    const overlap = { item_id: 'I3', source: { start: 5, end: 13, text: doc.slice(5, 13) } }
    const outside = { item_id: 'I4', source: { start: 30, end: 40, text: '' } }
    const parts = documentParts(doc, [second, overlap, first, outside])
    expect(parts.map((part) => part.text).join('')).toBe(doc)
    expect(parts.filter((part) => part.itemId).map((part) => part.itemId)).toEqual(['I1', 'I2'])
  })

  it('조각 안 칸 근거: 어느 말을 어느 칸으로 읽었는지, 이어 붙이면 조각 그대로', () => {
    const parts = fragmentParts(TEXT, item().draft)
    expect(parts.map((part) => part.text).join('')).toBe(TEXT)
    expect(parts.filter((part) => part.slot).map((part) => [part.slot, part.text])).toEqual([
      ['part_ids', 'B31P 판 PL-002'],
      ['op', '두께'],
      ['to_mm', '20mm'],
    ])
    expect(fragmentParts('글', null)).toEqual([{ text: '글', slot: null, method: null }])
  })

  it('서버 이유를 항목별로 모음(모르는 항목·문서 전체는 빈 키)', () => {
    expect(problemsByItem(['I1: 대상이 없어요', 'I9: 모름', '분석할 항목이 없어요'], [{ item_id: 'I1' }])).toEqual({
      I1: ['대상이 없어요'],
      '': ['I9: 모름', '분석할 항목이 없어요'],
    })
  })
})

describe('비서로 넘길 씨앗', () => {
  it('규칙으로 읽은 연산과 고른 대상만 넘김', () => {
    expect(seedFor(item(), ['S-001:B31P-PL-005'])).toEqual({
      fixed_op: 'thickness',
      overrides: { part_ids: { value: ['S-001:B31P-PL-005'], method: 'user' } },
    })
    expect(seedFor(item(), null)).toEqual({ fixed_op: 'thickness', overrides: {} })
  })

  it('AI·추정 연산이나 초안이 없으면 씨앗 없음(비서가 처음부터 묻는다)', () => {
    const ai = item()
    ai.draft!.op = { value: 'thickness', method: 'llm' }
    expect(seedFor(ai, ['S-001:B31P-PL-005'])).toBeNull()
    expect(seedFor(item({ draft: null, slots: [] }), null)).toBeNull()
  })
})

describe('반례 회귀', () => {
  it('지원하지 않는 변경은 빼기만(맞음·고침·비서로는 막음)', () => {
    const unsupported = item({ draft: null, slots: [], issues: [issue('unsupported_op')] })
    expect(isUnsupported(unsupported)).toBe(true)
    expect(rowProblem(unsupported, row({ action: 'drop' }))).toBeNull()
    expect(rowProblem(unsupported, row({ action: 'handoff', draft: item().draft }))).toMatch(/빼기 필요/)
  })

  it('대상을 바꾸면 증감으로 계산한 바꿀 값은 직접 넣어야 함', () => {
    const text = 'B31P 판 7번 두께 3mm 증가'
    const relative = item({ source: { start: 0, end: text.length, text } })
    relative.draft = {
      ...relative.draft!,
      text,
      slots: {
        part_ids: { value: ['S-001:B31P-PL-007'], method: 'decision' },
        from_mm: { value: 17, method: 'map' },
        to_mm: { value: 20, method: 'rule', span: { start: 13, end: 16, text: '3mm' } },
      },
    }
    expect(staleOnRetarget(relative).map((slot) => slot.name)).toEqual(['to_mm'])
    expect(staleOnRetarget(item())).toEqual([])
    expect(rowProblem(relative, row({ action: 'edit', partIds: ['S-001:T31C-PL-009'] }))).toBe(
      '바꿀 두께는 원래 대상의 지금 값 기준 증감 — 대상을 바꾸면 바꿀 두께를 직접 입력',
    )
    expect(rowProblem(relative, row({ action: 'edit', partIds: ['S-001:T31C-PL-009'], values: { to_mm: '18.5' } }))).toBeNull()
  })

  it('문제 없는 항목만 한 번에 맞음(AI·추정 값이 있으면 사람이 하나씩)', () => {
    const ai = item({ item_id: 'I2' })
    ai.draft!.slots!.to_mm = { value: 20, method: 'llm' }
    const rows = acceptClean([item(), ai], {})
    expect(rows.I1.action).toBe('accept')
    expect(rows.I2).toBeUndefined()
  })

  it('판단으로 고른 연산은 씨앗으로 넘기지 않음(비서가 다시 확인)', () => {
    const decided = item()
    decided.draft!.op = { value: 'thickness', method: 'decision' }
    expect(seedFor(decided, ['S-001:B31P-PL-005'])).toBeNull()
  })
})

