// ECN 목록(DESIGN.md 6절): 줄마다 제목 · 결정 기한(D-n, D-3 이하는 위험 색) · 총변경비용을 크게, 판정 칩 · 결재 상태 · ECN 번호 ·
// 블록(호선이 여럿이면 호선도)은 작게. 값은 기준일에 확정·보류 없음으로 분석한 요약이라 그 조건은 거르기 칸의 ⓘ에 둔다. 기본 정렬 = 마감일 임박 → 판정,
// 판정으로 거르기. 키보드: 목록 안에서 J/K(↓/↑)로 이동, Enter로 열기. 아무것도 초점이 없을 때 J/K는 고른 줄로 초점.
// 결재 상태(docs/records.md): 기록이 있는 줄에만 상태 글자(분석·검토·승인 …), 기록이 없는 줄은 '요청'이라 생략한다.
// 샘플에 없는 기록된 설계변경(비서 요청·다른 지도)은 아래 '기록된 다른 설계변경'(RecordedOthers.tsx). 결재자의 '결재 대기'와
// 담당자의 '내 건'은 거르기 칸이다(따로 묶으면 같은 건이 두 번 나옴 — 내 건 줄에는 '내 건'과 반려·보류 사유 한 줄).
// 샘플이 없는 지도만 결재 대기를 위 묶음으로(PendingDecisions.tsx). 줄 모양은 같다(EcnRow.tsx).
import { ArrowDownUp } from 'lucide-react'
import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import type { EcnListItem, Sample } from '@/api/client'
import { TermInfo } from '@/components/common/TermInfo'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { StateText } from '@/components/records/StateChip'
import { Button } from '@/components/ui/button'
import {
  FILTERS,
  FILTER_NAMES,
  SORT_NAMES,
  basisText,
  deadlineMark,
  filterRecorded,
  filterSamples,
  isClosed,
  manyShips,
  mineSet,
  placeText,
  sortSamples,
  verdictCounts,
  type ListFilter,
  type ListView,
} from '@/lib/ecnList'
import { MY_NEXT } from '@/lib/records'
import { cn } from '@/lib/utils'
import { EcnRow } from './EcnRow'
import { PendingDecisions } from './PendingDecisions'
import { RecordedOthers } from './RecordedOthers'
import { reasonKey, useDecisionReasons } from './useDecisionReasons'

const ITEM = 'button[data-ecn-item]'
/** 줄을 누르면 기록된 분석을 여는 칸(결재·내 기록을 보러 온 칸). */
const RECORDED_VIEWS: readonly ListFilter[] = ['pending', 'mine']
const EMPTY_TEXT: Partial<Record<ListFilter, string>> = {
  closed: '종료된 설계변경 없음',
  pending: '결재 대기 설계변경 없음',
  mine: '내가 올린 설계변경 없음',
}

/** J/K·↓/↑: 한글 입력 상태에서도 잡히도록 물리 키(code)를 함께 본다. */
function step(event: KeyboardEvent | ReactKeyboardEvent): number {
  if (event.ctrlKey || event.metaKey || event.altKey) return 0
  if (event.code === 'KeyJ' || event.key === 'ArrowDown') return 1
  if (event.code === 'KeyK' || event.key === 'ArrowUp') return -1
  return 0
}

interface SortProps {
  view: ListView
  onView: (view: ListView) => void
  compact: boolean
}

/** 칸 머리의 정렬 단추: 마감일 순 ↔ 비용 큰 순. */
export function ListSortButton({ view, onView, compact }: SortProps) {
  const next = view.sort === 'deadline' ? 'cost' : 'deadline'
  return (
    <Button
      variant="ghost"
      size="sm"
      // 좁은 목록 칸(1024px · 큰 글자)에서는 칸 밖으로 밀려나지 않고 글자가 말줄임으로 줄어든다(전체는 마우스 올림)
      className={cn('min-w-0 shrink text-foreground-secondary', compact && 'h-11 px-3')}
      aria-label={`정렬: ${SORT_NAMES[view.sort]}(누르면 ${SORT_NAMES[next]})`}
      title={`정렬: ${SORT_NAMES[view.sort]}`}
      onClick={() => onView({ ...view, sort: next })}
    >
      <ArrowDownUp aria-hidden />
      <span className="truncate">{SORT_NAMES[view.sort]}</span>
    </Button>
  )
}

interface Props {
  samples: Sample[]
  chosen: string | null
  failed: boolean
  /** 목록을 다 읽었는가(빈 목록과 읽는 중을 가른다). */
  ready: boolean
  onChoose: (sample: Sample) => void
  view: ListView
  onView: (view: ListView) => void
  /** 좁은 화면: 거르기 단추는 터치 높이. */
  compact: boolean
  /** 기록된 설계변경(상태 + 최신 개정 요약). */
  records: EcnListItem[]
  /** 샘플에 없는 기록된 설계변경을 연다(기록의 요청으로 지금 지도에서 다시 분석). */
  onOpenRecord: (item: EcnListItem) => void
  /** 지금 지도 ID(기록의 지도가 다르면 '다른 지도' 표시). */
  snapshotId: string | null
  /** 결재자: 거르기 칸 '결재 대기'(목록이 없는 지도는 위 묶음 '결재를 기다리는 설계변경'). */
  approver: boolean
  /** 담당자(기록 권한)의 아이디: 거르기 칸 '내 건'. 기록 권한이 없으면 null. */
  recorder?: string | null
}

export function EcnList({
  samples,
  chosen,
  failed,
  ready,
  onChoose,
  view,
  onView,
  compact,
  records,
  onOpenRecord,
  snapshotId,
  approver,
  recorder = null,
}: Props) {
  const listRef = useRef<HTMLUListElement>(null)

  // 아무것도 초점이 없을 때(문서 본문) J/K는 고른 줄(없으면 첫 줄)로 초점을 옮긴다. 입력창·대화상자 안에서는 동작하지 않는다
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const active = document.activeElement
      const jk = !event.ctrlKey && !event.metaKey && !event.altKey && (event.code === 'KeyJ' || event.code === 'KeyK')
      if (!jk || (active && active !== document.body) || document.querySelector('[role="dialog"]')) return
      const items = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>(ITEM) ?? [])
      const target = items.find((item) => item.getAttribute('aria-current') === 'true') ?? items[0]
      if (!target) return
      event.preventDefault()
      target.focus()
      target.scrollIntoView({ block: 'nearest' })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 고른 칸을 볼 수 없는 역할이면(결재자가 아닌데 '결재 대기', 기록 권한이 없는데 '내 건') '전체'로 되돌린다 — 보기 상태는 앱에 남는다
  const unseen = (view.filter === 'pending' && !approver) || (view.filter === 'mine' && !recorder)
  useEffect(() => {
    if (unseen) onView({ ...view, filter: 'all' })
  }, [unseen, view, onView])

  const itemOf = new Map(records.map((item) => [item.status.ecn_id, item]))
  const stateOf = (ecnId: string) => itemOf.get(ecnId)?.status.state
  const mine = mineSet(records, recorder)
  const mineOf = (ecnId: string) => mine.has(ecnId)
  const reasons = useDecisionReasons(records.filter((item) => mine.has(item.status.ecn_id)))
  // 내 건의 반려·보류 사유 한 줄(사유를 못 읽었거나 내 건이 아니면 없음)
  const reasonOf = (ecnId: string) => {
    const item = itemOf.get(ecnId)
    const reason = item && mine.has(ecnId) ? reasons[reasonKey(item)] : undefined
    return reason ? `사유: ${reason}` : undefined
  }
  const sampleIds = new Set(samples.map((sample) => sample.ecn_id))
  const others = records.filter((item) => !sampleIds.has(item.status.ecn_id))
  // 기록된 다른 설계변경도 위 거르기를 그대로 따른다(종료는 '종료' 칸에서만, 판정 칸은 최신 개정 판정으로 — 개수 = 보이는 줄).
  // 샘플이 없는 지도는 거르기 단추가 없으니 판정으로 거르지 않는다
  const closedView = view.filter === 'closed'
  const otherShown = filterRecorded(others, samples.length > 0 ? view.filter : closedView ? 'closed' : 'all', mineOf)
  const recorded = (
    <RecordedOthers
      items={otherShown}
      chosen={chosen}
      onOpen={onOpenRecord}
      snapshotId={snapshotId}
      mineOf={mineOf}
      reasonOf={reasonOf}
    />
  )
  // 샘플이 없는 지도는 거르기 칸이 없어 결재 대기를 묶음으로 둔다(샘플이 있으면 '결재 대기' 칸 — 같은 건을 두 번 싣지 않게)
  const pending = approver && samples.length === 0 && (
    <PendingDecisions items={records} chosen={chosen} onOpen={onOpenRecord} />
  )

  if (samples.length === 0) {
    return (
      <div>
        {pending}
        <p className="p-4 text-sm text-foreground-secondary">
          {failed
            ? '설계변경 목록 불러오기 실패 · 잠시 뒤 다시 시도'
            : ready
              ? '이 지도에 설계변경 목록 없음 · AI 비서에 바꿀 대상과 값을 적으면 분석'
              : '설계변경 목록 불러오는 중…'}
        </p>
        {recorded}
      </div>
    )
  }

  const counts = verdictCounts(samples, stateOf, others, mineOf)
  // '결재 대기' 칸은 결재자에게만(담당자는 '내 건'에서 상태를 본다), 0건 칸은 숨기되 지금 고른 칸은 남긴다(마지막 건을
  // 승인해 0건이 돼도 눌린 칸과 빈 안내가 맞게 — 역할이 바뀌어 볼 수 없는 칸은 위 효과가 '전체'로 되돌림)
  const visible = (filter: ListFilter) =>
    filter === 'all' || ((counts[filter] > 0 || filter === view.filter) && (filter !== 'pending' || approver))
  const shown = sortSamples(filterSamples(samples, view.filter, stateOf, mineOf), view.sort)
  const basis = basisText(samples)
  const withShip = manyShips(samples)

  const onListKey = (event: ReactKeyboardEvent<HTMLUListElement>) => {
    const delta = step(event)
    if (!delta) return
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(ITEM))
    const at = items.findIndex((item) => item === document.activeElement)
    const next = items[Math.min(items.length - 1, Math.max(0, (at < 0 ? 0 : at) + (at < 0 ? 0 : delta)))]
    if (!next) return
    event.preventDefault()
    next.focus()
    next.scrollIntoView({ block: 'nearest' })
  }

  return (
    <div>
      {pending}
      {/* 거르기 칸 + 목록 값 조건(ⓘ — 늘 떠 있는 설명 줄 대신, 마우스 올림에도 같은 글) */}
      <div className="flex items-center gap-1 border-b border-border px-4 py-2.5" title={basis ?? undefined}>
        <div role="group" aria-label="판정으로 거르기" className="flex min-w-0 flex-1 flex-wrap gap-1">
          {FILTERS.filter(visible).map((filter) => (
            <button
              key={filter}
              type="button"
              aria-pressed={view.filter === filter}
              aria-label={`${FILTER_NAMES[filter]} ${counts[filter]}건`}
              onClick={() => onView({ ...view, filter })}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm border border-border px-1.5 text-xs whitespace-nowrap text-foreground-secondary hover:bg-hover',
                'aria-pressed:border-primary aria-pressed:bg-primary/8 aria-pressed:font-semibold aria-pressed:text-foreground',
                compact ? 'h-11' : 'h-9',
              )}
            >
              {FILTER_NAMES[filter]}
              <span className="tabular-nums">{counts[filter]}</span>
            </button>
          ))}
        </div>
        {basis && <TermInfo term="listBasis" />}
      </div>
      {shown.length === 0 ? (
        otherShown.length === 0 && (
          <p className="p-4 text-sm text-foreground-secondary">
            {EMPTY_TEXT[view.filter] ?? '이 판정의 설계변경 없음'}
          </p>
        )
      ) : (
        <ul ref={listRef} aria-label="설계변경" onKeyDown={onListKey} className="divide-y divide-border">
          {shown.map((sample) => {
            const summary = sample.summary
            const place = placeText(sample, withShip)
            const state = stateOf(sample.ecn_id)
            const reason = reasonOf(sample.ecn_id)
            return (
              <EcnRow
                key={sample.ecn_id}
                title={sample.title}
                mark={summary && !isClosed(state) ? deadlineMark(summary.deadline, sample.request.as_of) : null}
                tag={summary && <VerdictBadge level={summary.verdict} size="sm" />}
                meta={
                  <>
                    {state && (
                      <>
                        <StateText state={state} />
                        {' · '}
                      </>
                    )}
                    {mineOf(sample.ecn_id) && '내 건 · '}
                    <span className="font-mono">{sample.ecn_id}</span>
                    {place && ` · ${place}`}
                  </>
                }
                hint={[
                  sample.title,
                  sample.ecn_id,
                  place,
                  mineOf(sample.ecn_id) && state && MY_NEXT[state],
                  reason,
                ]
                  .filter(Boolean)
                  .join(' · ')}
                extra={reason}
                total={summary ? summary.total.value : null}
                totalTitle="기준일에 확정할 때의 총변경비용"
                current={sample.ecn_id === chosen}
                onClick={() => {
                  // '결재 대기'·'내 건' 칸의 줄은 그 개정의 기록된 분석을 연다(결재할 조건·사유를 단 그 분석 — 기본 요청 아님)
                  const item = itemOf.get(sample.ecn_id)
                  if (item && RECORDED_VIEWS.includes(view.filter)) onOpenRecord(item)
                  else onChoose(sample)
                }}
                marks={{ 'data-ecn-item': true }}
              />
            )
          })}
        </ul>
      )}
      {recorded}
    </div>
  )
}
