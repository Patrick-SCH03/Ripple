// 문서 접수 원문 강조 조각(순수 함수, intake.test.ts가 성질을 검사한다): 원문을 항목 조각으로, 항목 조각을 칸 근거로 나눈다.
// 이어 붙이면 언제나 원문 그대로다. lib/intake가 이 경로의 이름을 함께 내보낸다.
import type { ChangeDraft, FillMethod, IntakeItem, SlotFill } from '@/api/client'

export interface DocPart {
  text: string
  itemId: string | null
}

/** 원문을 항목 조각과 그 사이 글로 나눈다(겹치거나 원문 밖 위치는 건너뜀). 이어 붙이면 원문 그대로. */
export function documentParts(document: string, items: readonly Pick<IntakeItem, 'item_id' | 'source'>[]): DocPart[] {
  const spans = items
    .map((item) => ({ id: item.item_id, start: item.source.start, end: item.source.end }))
    .filter((span) => span.start >= 0 && span.end <= document.length && span.start < span.end)
    .sort((a, b) => a.start - b.start || a.end - b.end)
  const parts: DocPart[] = []
  let at = 0
  for (const span of spans) {
    if (span.start < at) continue
    if (span.start > at) parts.push({ text: document.slice(at, span.start), itemId: null })
    parts.push({ text: document.slice(span.start, span.end), itemId: span.id })
    at = span.end
  }
  if (at < document.length) parts.push({ text: document.slice(at), itemId: null })
  return parts
}

export interface FragmentPart {
  text: string
  slot: string | null
  method: FillMethod | null
}

/** 항목 조각 안에서 칸 근거 위치(조각 기준)를 표시한다: 어느 말을 어느 칸으로 읽었는지. 겹치면 앞의 것. */
export function fragmentParts(text: string, draft: ChangeDraft | null | undefined): FragmentPart[] {
  const fills: [string, SlotFill][] = draft
    ? [...(draft.op ? ([['op', draft.op]] as [string, SlotFill][]) : []), ...Object.entries(draft.slots ?? {})]
    : []
  const spans = fills
    .flatMap(([slot, fill]) => (fill.span ? [{ slot, method: fill.method, start: fill.span.start, end: fill.span.end }] : []))
    .filter((span) => span.start >= 0 && span.end <= text.length && span.start < span.end)
    .sort((a, b) => a.start - b.start || b.end - a.end)
  const parts: FragmentPart[] = []
  let at = 0
  for (const span of spans) {
    if (span.start < at) continue
    if (span.start > at) parts.push({ text: text.slice(at, span.start), slot: null, method: null })
    parts.push({ text: text.slice(span.start, span.end), slot: span.slot, method: span.method })
    at = span.end
  }
  if (at < text.length) parts.push({ text: text.slice(at), slot: null, method: null })
  return parts
}
