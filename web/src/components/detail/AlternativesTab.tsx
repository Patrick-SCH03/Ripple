// 대안 탭(docs/engine.md(대안), DESIGN.md 6절): 권고 → 확정을 미루면(날짜별 최저 비용 대안) → 대안 표(판정·총액·
// 구역 출구 지연·추가손실 0 마감일) → 펼치면 판정 근거. 상세에 보이는 분석을 대안 포함으로 한 번 더 계산해 그린다.
// 계산·기억은 alternatives/useAlternatives, 표 한 줄은 alternatives/AlternativeRow.
import { LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import type { AnalysisRequest, AnalysisResult } from '@/api/client'
import {
  REQUEST_ALT,
  earliestText,
  hasAlternatives,
  recommendationHeadline,
  recommendationKeepText,
  shortName,
  sortedAlternatives,
  spanSentences,
  spanTitle,
} from '@/lib/alternatives'
import { InfoPop } from '@/components/common/InfoPop'
import { AlternativeRow, OpenAlternative } from './alternatives/AlternativeRow'
import { DeliveryBand } from './DeliveryBand'
import { useAlternatives } from './alternatives/useAlternatives'

interface Props {
  /** 상세에 보이는 분석(대안을 끈 결과). */
  result: AnalysisResult
  /** 좁은 화면: 단추는 터치 높이. */
  compact: boolean
  /** '이 대안으로 분석 보기': 요청의 연산을 대안 연산으로 바꿔 상세에서 분석한다. */
  /** label: 바뀐 점 띠의 제목(예: '대안: 보강재 추가'). */
  onOpen: (request: AnalysisRequest, label: string) => void
}

export function AlternativesTab({ result, compact, onOpen }: Props) {
  const loaded = useAlternatives(result)
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  if (!loaded) {
    return (
      <p role="status" className="flex items-center gap-2 px-1 py-4 text-sm text-foreground-secondary">
        <LoaderCircle aria-hidden className="size-4 animate-spin" />
        대안을 비교하는 중…
      </p>
    )
  }
  if ('error' in loaded) {
    return (
      <div role="alert" className="rounded-md border border-danger/40 bg-danger/8 px-3 py-2 text-sm">
        <p className="font-semibold">대안 계산 실패</p>
        <p className="text-foreground-secondary">{loaded.error.message}</p>
      </div>
    )
  }
  const data = loaded.data
  const baseNotes = new Set(result.notes)
  const notes = data.notes.filter((note) => !baseNotes.has(note))
  if (!hasAlternatives(data)) {
    return (
      <div className="space-y-1 px-1 py-2 text-sm">
        <p>비교할 대안 없음</p>
        {notes.map((note) => (
          <p key={note} className="text-foreground-secondary">
            {note}
          </p>
        ))}
      </div>
    )
  }
  const rows = sortedAlternatives(data.alternatives)
  const names = new Map(data.alternatives.map((a) => [a.alt_id, shortName(a)]))
  const headline = recommendationHeadline(data)
  const keepText = recommendationKeepText(data)
  const chosen = data.alternatives.find((a) => a.alt_id === data.recommendation?.alt_id)
  const spans = spanSentences(data.cheapest_by_date, (id) => names.get(id) ?? id)
  const asOf = data.request.as_of
  const toggle = (altId: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(altId)) next.add(altId)
      return next
    })
  const opening = { request: result.request, compact, onOpen }
  return (
    <div className="@container space-y-3">
      <DeliveryBand result={result} />
      {headline && chosen && (
        <section aria-label="권고" className="rounded-md border border-border px-4 py-3">
          <p className="text-sm text-foreground-secondary">최저 비용 조합</p>
          <p className="mt-0.5 text-md font-semibold">{headline.title}</p>
          <p className="mt-1">{headline.detail}</p>
          {/* 보조 한 줄: 그 금액을 언제까지 지키는지 — 확정 가능일 안내는 ⓘ */}
          {(keepText || earliestText(data.request)) && (
            <p className="text-sm text-foreground-secondary">
              {keepText}
              {earliestText(data.request) && (
                <span className="ml-1.5 inline-block">
                  <InfoPop title="확정 가능일" lines={[earliestText(data.request) as string]} label={keepText ? undefined : '확정 가능일'} />
                </span>
              )}
            </p>
          )}
          {chosen.alt_id !== REQUEST_ALT && (
            <div className="mt-2.5">
              <OpenAlternative alternative={chosen} {...opening} />
            </div>
          )}
        </section>
      )}
      {spans && (
        <section data-spans aria-label={spanTitle(data.request)} className="rounded-md border border-border px-4 py-3">
          <p className="text-sm text-foreground-secondary">{spanTitle(data.request)}</p>
          <ul className="mt-1 space-y-0.5">
            {spans.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
        </section>
      )}
      <ul aria-label="대안" className="divide-y divide-border border-y border-border">
        <li
          aria-hidden
          className="hidden items-center gap-3 px-3 py-1.5 text-sm text-foreground-secondary @min-[52rem]:flex"
        >
          <span className="w-4 shrink-0" />
          <span className="min-w-0 flex-1">대안</span>
          <span className="w-28 shrink-0">판정</span>
          <span className="w-36 shrink-0 text-right">출구 예상 지연</span>
          <span className="w-24 shrink-0 text-right">결정 기한</span>
          <span className="w-48 shrink-0 text-right">총변경비용</span>
        </li>
        {rows.map((alternative, index) => (
          <AlternativeRow
            key={alternative.alt_id}
            alternative={alternative}
            index={index}
            expanded={open.has(alternative.alt_id)}
            onToggle={() => toggle(alternative.alt_id)}
            recommended={alternative.alt_id === data.recommendation?.alt_id}
            asOf={asOf}
            {...opening}
          />
        ))}
      </ul>
      {/* 서버 안내(계산 한계·제외한 대안)는 표 아래 회색 줄 묶음 대신 접힌 '대안 안내 n'(펴면 원문 그대로) */}
      {notes.length > 0 && (
        <details className="px-1 text-sm">
          <summary className="cursor-pointer text-foreground-secondary hover:text-foreground">대안 안내 {notes.length}</summary>
          <ul aria-label="대안 안내" className="mt-1.5 space-y-0.5 text-foreground-secondary">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
