// ' · '로 이은 글을 마디 단위로 그린다(lib/segments): 짧은 마디는 줄을 바꾸지 않고, 긴 마디는 낱말 사이에서만 접는다.
// keepAll = 마디마다 통째로(결재 올릴 기한 한 줄 — 날짜·금액 덩어리가 가운데서 끊기지 않게, 결정 기한 카드·결재함 줄).
import { Fragment } from 'react'
import { segments } from '@/lib/segments'

export function SegmentText({ text, keepAll = false }: { text: string; keepAll?: boolean }) {
  return segments(text, keepAll ? Infinity : undefined).map((part, i) => (
    <Fragment key={`${i}:${part.text}`}>
      {i > 0 && ' · '}
      <span className={part.keep ? 'whitespace-nowrap' : 'break-keep'}>{part.text}</span>
    </Fragment>
  ))
}
