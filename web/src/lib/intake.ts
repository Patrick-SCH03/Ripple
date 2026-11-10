// 문서 접수 확인표 계산(순수 함수, intake.test.ts가 성질을 검사한다): 항목 상태·칸 표시·사람 결정 → 확정 요청,
// 확정 가능 여부와 이유, 원문 강조 조각. 서버가 다시 검증하므로 여기서는 보내기 전에 빠진 것을 알려 주는 일만 한다
// (규칙은 ripple/intake/confirm.py와 같은 방향: 막는 문제는 고침으로 풀리거나 비서로 넘겨야 한다).
// 원문 강조 조각(lib/intakeText)도 이 경로에서 함께 내보낸다.
import type {
  AssistantSeed,
  ChangeDraft,
  FillMethod,
  IntakeIssue,
  IntakeItem,
  IntakeProposal,
  ItemDecision,
  SlotFill,
  SlotSpec,
} from '@/api/client'

export { documentParts, fragmentParts } from './intakeText'

type IssueCode = IntakeIssue['code']

/** 그대로 '맞음'으로 확정할 수 없는 문제(계약 BLOCKING과 같은 목록). */
export const BLOCKING: ReadonlySet<IssueCode> = new Set<IssueCode>([
  'unsupported_op',
  'unreadable',
  'extract_unverified',
  'target_unresolved',
  'target_ambiguous',
  'value_missing',
  'llm_rule_disagree',
  'duplicate',
  'conflict',
])
/** 항목 사이 문제: 확정할 때 서버가 남은 항목끼리 다시 본다(한쪽을 빼면 풀린다). */
const CROSS: ReadonlySet<IssueCode> = new Set<IssueCode>(['duplicate', 'conflict'])
const TARGET_FIXES: ReadonlySet<IssueCode> = new Set<IssueCode>(['target_unresolved', 'target_ambiguous'])
const VALUE_FIXES: ReadonlySet<IssueCode> = new Set<IssueCode>(['value_missing', 'llm_rule_disagree', 'value_uncertain'])
const NUMBER_KINDS: ReadonlySet<SlotSpec['kind']> = new Set<SlotSpec['kind']>(['millimeter', 'quantity'])
/** 바꿀 값이 지금 값에 더하고 뺀(증감·비율) 표현이라는 단서(서버 ripple/nl/draft.py RELATIVE_WORDS와 같음). */
const RELATIVE = /증가|감소|늘|줄|올려|올리|내려|내리|올림|내림|증후|감후|키워|키우|%|퍼센트/
const UNSUPPORTED = '지원하지 않는 변경 · 분석 불가 — 빼기 필요'

/** 조사: 마지막 글자에 받침이 있으면 앞, 없으면 뒤(한글이 아니면 '앞(뒤)'). */
function particle(word: string, withFinal: string, without: string): string {
  const code = word.trim().charCodeAt(word.trim().length - 1) - 0xac00
  if (Number.isNaN(code) || code < 0 || code > 11171) return `${word}${withFinal}(${without})`
  return `${word}${code % 28 === 0 ? without : withFinal}`
}

/** 지원하지 않는 변경(8종 밖): 빼기만 할 수 있다(비서로도 8종에 억지로 넣지 않게, 서버와 같은 규칙). */
export function isUnsupported(item: Pick<IntakeItem, 'issues'>): boolean {
  return item.issues.some((issue) => issue.code === 'unsupported_op')
}

/** 대상을 바꾸면 다시 정해야 하는 바꿀 값 칸: 지도 지금 값에 기대어 증감·비율로 계산한 수치(서버 retarget과 같음). */
export function staleOnRetarget(item: Pick<IntakeItem, 'slots' | 'draft'>): SlotSpec[] {
  const draft = item.draft
  if (!draft || !item.slots.some((slot) => slot.from_map && NUMBER_KINDS.has(slot.kind))) return []
  return item.slots.filter((slot) => {
    const fill = draft.slots?.[slot.name]
    if (slot.from_map || !NUMBER_KINDS.has(slot.kind) || !fill?.span) return false
    if (!['rule', 'guess', 'llm'].includes(fill.method)) return false
    return RELATIVE.test(draft.text.slice(fill.span.start, fill.span.end + 6))
  })
}

/** 채움 방식 이름표: 사람이 무엇을 확인해야 하는지 보이게(AI·추정은 강조). */
export const METHOD_LABEL: Record<FillMethod, string> = {
  rule: '문서',
  decision: '판단',
  map: '지도',
  context: '화면',
  user: '사람',
  guess: '추정',
  llm: 'AI',
}

/** 사람이 확인해야 하는 채움(AI·추정): 확인표에서 강조한다. */
export function needsLook(method: FillMethod): boolean {
  return method === 'llm' || method === 'guess'
}

export type RowAction = 'accept' | 'edit' | 'handoff' | 'drop'

/** 확인표 한 줄의 사람 결정. 숫자 칸은 입력 글 그대로 들고 있다가 보낼 때 읽는다. */
export interface RowState {
  action: RowAction | null
  partIds: string[] | null // 고른 대상(고침)
  values: Record<string, string> // 고친 수치(칸 이름 → 입력 글)
  draft: ChangeDraft | null // 비서가 마친 초안(비서로)
  summary: string | null // 그 초안의 한 줄 요약(비서가 준 글)
}

export const EMPTY_ROW: RowState = { action: null, partIds: null, values: {}, draft: null, summary: null }

export type ItemTone = 'blocked' | 'look' | 'clean'

/** 항목 첫 상태: 막는 문제가 있음 / 살펴볼 것(문제·AI·추정 값)이 있음 / 깨끗함. */
export function itemTone(item: Pick<IntakeItem, 'issues' | 'draft'>): ItemTone {
  if (item.draft == null || item.issues.some((issue) => BLOCKING.has(issue.code))) return 'blocked'
  const fills = [item.draft.op, ...Object.values(item.draft.slots ?? {})].filter((fill): fill is SlotFill => fill != null)
  if (item.issues.length > 0 || fills.some((fill) => needsLook(fill.method))) return 'look'
  return 'clean'
}

/** 대상 칸(판단 계층이 고르는 부재 묶음): 표에서 후보로 고칠 수 있는 유일한 대상 칸. */
export function targetSlot(item: Pick<IntakeItem, 'slots'>): SlotSpec | null {
  return item.slots.find((slot) => slot.calibrated && slot.kind === 'parts') ?? null
}

/** 표에서 고칠 수 있는 수치 칸: mm·수량이고 지도에서 다시 읽는 '지금 값'이 아닌 것. */
export function numberSlots(item: Pick<IntakeItem, 'slots'>): SlotSpec[] {
  return item.slots.filter((slot) => NUMBER_KINDS.has(slot.kind) && !slot.from_map)
}

/** 칸 값 글: 목록은 쉼표로, 수는 그대로(소수 둘째 자리까지). 비었으면 null. */
export function fillText(fill: SlotFill | null | undefined): string | null {
  if (fill == null) return null
  const { value } = fill
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100)
  return value
}

/** 입력 글 → 양수(읽지 못하거나 0 이하면 null). 쉼표 천 단위·단위 글자는 받지 않는다(서버와 같은 엄격함). */
export function parsePositive(text: string): number | null {
  const trimmed = text.trim()
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null
  const value = Number(trimmed)
  return Number.isFinite(value) && value > 0 ? value : null
}

/** 고침에서 실제로 바꾼 수치(입력이 원래 값과 같으면 바꾸지 않은 것). 읽지 못한 칸은 problems로. */
function editedValues(item: IntakeItem, row: RowState): { values: Record<string, number>; problems: string[] } {
  const values: Record<string, number> = {}
  const problems: string[] = []
  const labels = Object.fromEntries(item.slots.map((slot) => [slot.name, slot.label]))
  for (const [name, text] of Object.entries(row.values)) {
    if (text.trim() === '') continue
    const value = parsePositive(text)
    if (value === null) {
      problems.push(`${labels[name] ?? name}: 0보다 큰 숫자 필요`)
      continue
    }
    const current = item.draft?.slots?.[name]?.value
    if (typeof current === 'number' && current === value) continue
    values[name] = value
  }
  return { values, problems }
}

function sameParts(a: readonly string[] | null, b: readonly string[] | null): boolean {
  if (a === null || b === null) return a === b
  const left = [...new Set(a)].sort()
  const right = [...new Set(b)].sort()
  return left.length === right.length && left.every((id, i) => id === right[i])
}

/** 고침에서 바꾼 대상(지금 초안 대상과 같으면 바꾸지 않은 것). */
function editedParts(item: IntakeItem, row: RowState): string[] | null {
  if (row.partIds === null || row.partIds.length === 0) return null
  const slot = targetSlot(item)
  const current = slot ? item.draft?.slots?.[slot.name]?.value : undefined
  return Array.isArray(current) && sameParts(current, row.partIds) ? null : row.partIds
}

/** 이 줄을 보내기 전에 막는 이유(없으면 null). 항목 사이 문제(같은 변경·겹침)는 서버가 남은 항목끼리 본다. */
export function rowProblem(item: IntakeItem, row: RowState): string | null {
  if (row.action === null) return '맞음·고침·비서로·뺌 중 선택 필요'
  if (row.action === 'drop') return null
  if (isUnsupported(item)) return UNSUPPORTED
  if (row.action === 'handoff') return row.draft ? null : '비서에서 초안 완료 후 확정 가능'
  if (item.draft == null) return '이 항목은 비서로 넘겨 고치거나 빼기'
  const fixed = new Set<IssueCode>()
  const fixedSlots = new Set<string>()
  if (row.action === 'edit') {
    const { values, problems } = editedValues(item, row)
    if (problems.length > 0) return problems[0]
    const parts = editedParts(item, row)
    if (parts === null && Object.keys(values).length === 0) return '고친 대상·수치 없음 — 그대로면 맞음 선택'
    if (parts !== null) {
      const slot = targetSlot(item)
      if (!slot) return '이 변경의 대상은 비서로 넘겨 고치기'
      const stale = staleOnRetarget(item).find((spec) => !(spec.name in values))
      if (stale) {
        const label = stale.label
        return `${particle(label, '은', '는')} 원래 대상의 지금 값 기준 증감 — 대상을 바꾸면 ${particle(label, '을', '를')} 직접 입력`
      }
      for (const code of [...TARGET_FIXES, 'value_missing', 'from_mismatch'] as IssueCode[]) fixed.add(code)
      fixedSlots.add(slot.name)
      for (const spec of item.slots) if (spec.from_map) fixedSlots.add(spec.name)
    }
    for (const name of Object.keys(values)) {
      for (const code of VALUE_FIXES) fixed.add(code)
      fixedSlots.add(name)
    }
  }
  const remaining = item.issues.find(
    (issue) =>
      BLOCKING.has(issue.code) &&
      !CROSS.has(issue.code) &&
      !(fixed.has(issue.code) && (issue.slot == null || fixedSlots.has(issue.slot) || TARGET_FIXES.has(issue.code))),
  )
  return remaining ? remaining.message : null
}

/** 사람 결정 → 계약 ItemDecision. 아직 보낼 수 없는 줄은 null(rowProblem이 이유). */
export function toDecision(item: IntakeItem, row: RowState): ItemDecision | null {
  if (rowProblem(item, row) !== null) return null
  if (row.action === 'drop') return { item_id: item.item_id, action: 'drop', values: {} }
  if (row.action === 'handoff') return { item_id: item.item_id, action: 'edit', draft: row.draft, values: {} }
  if (row.action === 'accept') return { item_id: item.item_id, action: 'accept', values: {} }
  const { values } = editedValues(item, row)
  return { item_id: item.item_id, action: 'edit', part_ids: editedParts(item, row), values }
}

export interface Readiness {
  decisions: ItemDecision[]
  reasons: string[] // '항목 ID: 이유'
  kept: number
  dropped: number
}

/** 확정 가능 여부: 모든 항목을 정했고, 막는 이유가 없고, 분석할 항목이 하나 이상. */
export function readiness(items: readonly IntakeItem[], rows: Readonly<Record<string, RowState>>): Readiness {
  const decisions: ItemDecision[] = []
  const reasons: string[] = []
  for (const item of items) {
    const row = rows[item.item_id] ?? EMPTY_ROW
    const problem = rowProblem(item, row)
    if (problem !== null) {
      reasons.push(`${item.item_id}: ${problem}`)
      continue
    }
    const decision = toDecision(item, row)
    if (decision) decisions.push(decision)
  }
  const dropped = decisions.filter((decision) => decision.action === 'drop').length
  const kept = decisions.length - dropped
  if (reasons.length === 0 && kept === 0 && items.length > 0) reasons.push('분석할 항목 없음(모두 뺌)')
  return { decisions, reasons, kept, dropped }
}

export function canConfirm(state: Readiness): boolean {
  return state.reasons.length === 0 && state.kept > 0
}

/** 문제도 AI·추정 값도 없는 항목만 '맞음'으로(정하지 않은 줄만). 사람이 이미 정한 줄은 두고. */
export function acceptClean(
  items: readonly IntakeItem[],
  rows: Readonly<Record<string, RowState>>,
): Record<string, RowState> {
  const next = { ...rows }
  for (const item of items) {
    const row = next[item.item_id] ?? EMPTY_ROW
    if (row.action !== null || itemTone(item) !== 'clean') continue // 살펴볼 것(AI·추정 값·경고)이 있으면 사람이 하나씩
    next[item.item_id] = { ...EMPTY_ROW, action: 'accept' }
  }
  return next
}

/** 서버 422(problems = '항목 ID: 이유')를 항목별로 모은다. 항목 ID가 없는 이유는 '' 키. */
export function problemsByItem(problems: readonly string[], items: readonly Pick<IntakeItem, 'item_id'>[]): Record<string, string[]> {
  const ids = new Set(items.map((item) => item.item_id))
  const out: Record<string, string[]> = {}
  for (const problem of problems) {
    const match = /^(I\d{1,3}): (.*)$/s.exec(problem)
    const key = match && ids.has(match[1]) ? match[1] : ''
    const message = key ? match![2] : problem
    ;(out[key] ??= []).push(message)
  }
  return out
}

/** 확인표 위 요약: '항목 5개 · 확인 필요 2 · 살펴보기 1'. */
export function proposalSummary(proposal: Pick<IntakeProposal, 'items'>): string {
  const tones = proposal.items.map((item) => itemTone(item))
  const blocked = tones.filter((tone) => tone === 'blocked').length
  const look = tones.filter((tone) => tone === 'look').length
  const parts = [`항목 ${proposal.items.length}개`]
  if (blocked > 0) parts.push(`확인 필요 ${blocked}`)
  if (look > 0) parts.push(`살펴보기 ${look}`)
  return parts.join(' · ')
}

/** 표에서 정한 것만 씨앗으로: 규칙·사람이 정한 연산(판단·AI·추정 연산은 비서가 다시 확인), 고른 대상. */
export function seedFor(item: IntakeItem, partIds: string[] | null): AssistantSeed | null {
  const op = item.draft?.op
  if (!op || (op.method !== 'rule' && op.method !== 'user')) return null // 판단·AI·추정 연산은 비서가 다시 확인
  const target = targetSlot(item)
  const overrides = target && partIds && partIds.length > 0 ? { [target.name]: { value: partIds, method: 'user' as const } } : {}
  return { fixed_op: String(op.value), overrides }
}
