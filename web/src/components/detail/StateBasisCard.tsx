// 할 일 > 계산에 쓴 현장 상태(docs/domain.md 12절의 판단이 걸린 상태, DESIGN.md 6절): 발주 단계·공정 실적은 구매·생산관리가
// 아는 정보라 설계 담당자의 할 일로 세지 않고 처음에는 '누가 확인할지' 한 줄로 접는다(구매 1 · 생산관리 3). 펴면 확인이
// 필요한 것부터(확인된 줄은 '확인된 n개 더 보기'로 접음) 줄마다 확인할 부서와 '맞음'(지금 보이는 상태를 오늘의 사실로) ·
// '고치기'(단계·납기·실적 날짜) — 아는 사람이 지도에 남기면 같은 요청으로 한 번 다시 분석한다(Workbench). 확인은 오늘
// 날짜만 — 기준일이 오늘이 아니면 단추 대신 안내. 할 일 칸 안의 둘째 묶음이라 제목은 h4.
import { CalendarClock, ChevronDown, CircleCheck, CircleHelp, History, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { AnalysisResult, StateBasis, StatusUpdate } from '@/api/client'
import { SegmentText } from '@/components/common/SegmentText'
import { TermInfo } from '@/components/common/TermInfo'
import { Button } from '@/components/ui/button'
import {
  BASIS_TEXT,
  OWNER,
  foldedText,
  lastText,
  needOf,
  ownerSummary,
  quickConfirm,
  sortRows,
  stateText,
  viaText,
  type Need,
} from '@/lib/stateBasis'
import { SubSection } from './DetailSection'
import { StateFixDialog } from './StateFixDialog'

const SHOWN = 5

const NEED_ICON: Record<Need, LucideIcon> = {
  unknown: CircleHelp,
  plan: CalendarClock,
  stale: History,
  ok: CircleCheck,
}
const NEED_TEXT: Record<Need, string> = {
  unknown: '확인 필요',
  plan: '추정',
  stale: '오래됨',
  ok: '확인됨',
}

interface Props {
  result: AnalysisResult
  /** 오늘(KST, YYYY-MM-DD). */
  today: string
  /** 기록 권한(담당자 이상)이 있고 표시 결과가 지금 초안의 결과인가. */
  canConfirm: boolean
  /** 상태 갱신을 보낸다. 실패면 이유 문장. */
  onSubmit: (update: StatusUpdate) => Promise<string | null>
  /** 좁은 화면·태블릿: 접기 단추도 터치 높이(44px). */
  compact?: boolean
}

export function StateBasisCard({ result, today, canConfirm, onSubmit, compact = false }: Props) {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fixing, setFixing] = useState<StateBasis | null>(null)
  const rows = sortRows(result.state_basis ?? [], today)
  if (rows.length === 0) return null
  const asOf = result.request.as_of
  const onToday = asOf === today
  const needing = rows.filter((row) => needOf(row, today) !== 'ok').length
  const folded = Math.min(needing, SHOWN)
  const shown = expanded ? rows : rows.slice(0, folded)
  const more = foldedText(rows.length - shown.length, Math.max(0, needing - shown.length))
  // 접을 줄이 있을 때만 단추(펼친 뒤 다시 분석해 줄이 줄었으면 없앰), 접으면 확인 필요 줄도 숨는지에 따라 글을 고른다
  const foldable = rows.length > folded
  const foldLabel = needing > SHOWN ? '접기' : '확인된 상태 접기'

  const send = async (key: string, update: StatusUpdate): Promise<string | null> => {
    setBusy(key)
    setError(null)
    const failure = await onSubmit(update)
    setBusy(null)
    if (failure) setError(failure)
    return failure
  }

  const owners = ownerSummary(rows, today)
  return (
    <SubSection
      id="state-basis-title"
      testId="state-basis"
      title={
        <>
          계산에 쓴 현장 상태
          {owners && <span className="ml-1.5 text-base font-medium text-warning">확인 필요 {owners.count}</span>}
        </>
      }
      info={<TermInfo term="state" />}
      action={
        <Button
          variant="ghost"
          size="sm"
          className={compact ? 'h-11 px-3' : undefined}
          aria-expanded={open}
          aria-controls="state-basis-body"
          onClick={() => setOpen((value) => !value)}
          data-testid="state-open"
        >
          {open ? '접기' : '펼치기'}
          <ChevronDown aria-hidden className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
        </Button>
      }
    >
      {/* 접힘: 발주 단계·공정 실적은 구매·생산관리가 아는 정보라 담당자 할 일이 아님 — 누가 확인할지만 한 줄로
          (확인 필요 수는 제목 옆, 기준일은 머리 메타 줄에 있어 되풀이하지 않음) */}
      {!open && (
        <p className="text-sm text-foreground-secondary" data-testid="state-owners">
          {owners ? `확인할 부서 · ${owners.text}` : `발주 단계·공정 실적 ${rows.length}개 모두 확인 완료`}
        </p>
      )}
      <div id="state-basis-body" hidden={!open}>
      {canConfirm && !onToday && (
        <p className="mt-1 text-sm text-foreground-secondary">확인은 오늘 상태로만 — 기준일을 오늘로 바꾸면 가능</p>
      )}
      {shown.length === 0 && (
        <p className="mt-2 flex items-center gap-2 rounded-md border border-border px-3 py-2.5 text-sm" data-testid="state-all-ok">
          <CircleCheck aria-hidden className="size-4 shrink-0 text-success" />
          현장 상태 {rows.length}개 모두 확인 완료
        </p>
      )}
      <ul
        id="state-basis-rows"
        className={shown.length > 0 ? 'mt-2 divide-y divide-border rounded-md border border-border' : 'hidden'}
      >
        {shown.map((row) => {
          const need = needOf(row, today)
          const Icon = NEED_ICON[need]
          const quick = quickConfirm(row, today)
          const key = `${row.entity_type}-${row.entity_id}`
          const via = viaText(row)
          return (
            <li key={key} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5" data-testid="state-row">
              <Icon
                aria-label={NEED_TEXT[need]}
                className={need === 'ok' ? 'size-4 shrink-0 text-success' : 'size-4 shrink-0 text-warning'}
              />
              <div className="min-w-0 flex-1 basis-60">
                <p className="font-medium">
                  {/* ' · ' 마디 단위로 접어 '11월 12일 / (목)'처럼 날짜가 갈라지지 않게 */}
                  <SegmentText text={row.label} />{' '}
                  <span className="font-normal">
                    · <SegmentText text={stateText(row)} />
                  </span>
                  {row.hold && <span className="ml-1.5 text-sm text-foreground-secondary">보류 권고</span>}
                  <span className="ml-1.5 inline-flex h-6 items-center rounded-sm border border-border px-1.5 align-middle text-xs font-normal text-foreground-secondary">
                    {OWNER[row.entity_type]} 확인
                  </span>
                </p>
                <p className="text-sm text-foreground-secondary">
                  <SegmentText text={[BASIS_TEXT[row.basis], lastText(row, today), via].filter(Boolean).join(' · ')} />
                </p>
              </div>
              {canConfirm && onToday && (
                <div className="ml-auto flex items-center gap-2">
                  {/* '맞음'을 못 남기는 행은 이유를 단추 자리에(왜 단추가 없는지 헤매지 않게) */}
                  {quick.kind === 'blocked' && (
                    <p className="max-w-64 text-right text-sm text-foreground-secondary">{quick.reason}</p>
                  )}
                  {quick.kind === 'ok' && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy !== null}
                      onClick={() => void send(key, quick.update)}
                    >
                      {busy === key ? '저장 중…' : quick.label}
                    </Button>
                  )}
                  <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setFixing(row)}>
                    고치기
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {foldable && (expanded || more) && (
        <Button
          variant="ghost"
          size="sm"
          className={compact ? 'mt-1 h-11 px-3' : 'mt-1'}
          aria-expanded={expanded}
          aria-controls="state-basis-rows"
          onClick={() => setExpanded((open) => !open)}
          data-testid="state-more"
        >
          {expanded ? foldLabel : more}
        </Button>
      )}
      </div>
      {error && (
        <p role="alert" className="mt-2 rounded-sm border border-danger/40 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <StateFixDialog
        row={fixing}
        today={today}
        busy={busy !== null}
        onOpenChange={(open) => !open && setFixing(null)}
        onSubmit={async (update) => {
          const failure = await send(`fix-${fixing?.entity_id ?? ''}`, update)
          if (!failure) setFixing(null)
          return failure
        }}
      />
    </SubSection>
  )
}
