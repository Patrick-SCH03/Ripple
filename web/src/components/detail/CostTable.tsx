// 비용 탭(DESIGN.md 6절): 계약 1.35.0 구분이 있으면 공수 · 재료비(자재 차이 · 구매) 두 묶음과 소계(엔진 구분별 합), 묶음
// 안은 금액 큰 순 — 공수 줄은 MH·작업반, 재료비 줄은 수량·단가를 줄에 바로 보인다(lib/costSplit). 구분이 없는 옛 기록은
// 금액 큰 순 한 목록. 줄마다 이름·금액(범위)·판단 불가 표시. 같은 규칙 줄이 셋 이상이면 한 줄로 묶고
// ('테이퍼 가공 8건', lib/costGroups) 누르면 그 줄들. 줄을 펼치면 실무 판단에 쓰는 것만:
// 발생 사유 · 계산 · 가정과 범위 · 늦어지면 · 일정(블록 재작업) · 보류 권고(발주) · 비중과 '영향 지도에서 근거 보기'.
// 규칙 ID·줄 ID·파라미터 키는 결과 데이터에만 두고 화면에 보이지 않는다(현업 판단에 쓰지 않는 개발용 정보).
import { ChevronRight, CircleAlert, Waypoints } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { AnalysisResult, CostLine } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  FACTOR_STATUS_NAMES,
  blockDelays,
  evidenceTarget,
  factorText,
  holdFor,
  holdSentence,
  outlookSentences,
  reworkFactorText,
  reworkFactors,
  shareText,
} from '@/lib/costDetail'
import { approvalHoldText } from '@/lib/approvalHold'
import { groupLines, type CostRow } from '@/lib/costGroups'
import { costSections, groupMeta, lineLabel, lineMeta } from '@/lib/costSplit'
import { UNRESOLVED_NAMES, nameOf } from '@/lib/labels'
import { sortedLines } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { AmountCell, SectionRows, UnknownBadge } from './CostSectionRows'
import { DelayRippleRow } from './DelayRippleRow'

/** 펼침의 한 구역: 넓으면 이름 | 내용 두 칸, 좁으면 위아래(컨테이너 폭 기준). */
function Row({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 @md:grid-cols-[6.5rem_minmax(0,1fr)] @md:gap-3">
      <dt className="font-medium text-foreground-secondary">{title}</dt>
      <dd className="min-w-0 space-y-0.5">{children}</dd>
    </div>
  )
}

function Factors({ line }: { line: CostLine }) {
  return (
    <>
      <ul className="space-y-1">
        {line.factors.map((factor) => {
          const text = factorText(factor)
          return (
            <li key={factor.keys.join(' ')} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span>{factor.label}</span>
              <span className="font-medium tabular-nums">{text.value}</span>
              {text.range && <span className="text-foreground-secondary tabular-nums">범위 {text.range}</span>}
              <span className="inline-flex h-6 items-center self-center rounded-sm border border-border px-1.5 text-xs text-foreground-secondary">
                {FACTOR_STATUS_NAMES[factor.status]}
              </span>
            </li>
          )
        })}
      </ul>
      {line.amount.low !== line.amount.high && (
        <p className="pt-0.5 text-foreground-secondary">
          {line.determinacy === 'state_unknown'
            ? '금액 범위: 가능한 단계 전체 × 가정값 최소~최대'
            : '금액 범위: 가정값 최소~최대'}
        </p>
      )}
    </>
  )
}

interface DetailProps {
  line: CostLine
  id: string
  result: AnalysisResult
  sorted: readonly CostLine[]
  compact: boolean
  onEvidence: (entityId: string) => void
}

function LineDetail({ line, id, result, sorted, compact, onEvidence }: DetailProps) {
  const sources = line.sources.map((s) => [s.file, s.sheet, s.row == null ? null : `${s.row}행`].filter(Boolean).join(' '))
  const outlook = outlookSentences(line)
  const delays = blockDelays(line, result.schedule.added_days_by_activity ?? {})
  const hold = holdFor(line, sorted, result.timing.holds)
  const holdApproval = hold ? approvalHoldText(hold, result.approval_plan) : null
  const share = shareText(line, result.cost_lines)
  const target = evidenceTarget(line, result)
  const rework = line.difficulty ? reworkFactors(line) : null
  return (
    <div id={id} className="@container bg-muted px-3 py-3 pl-10 text-sm">
      <dl className="space-y-2.5">
        {line.reason && <Row title="발생 사유">{line.reason}</Row>}
        <Row title="계산">
          <p className="tabular-nums">{line.formula}</p>
          {sources.length > 0 && <p className="text-foreground-secondary">원본: {sources.join(', ')}</p>}
        </Row>
        {rework && (
          <Row title="배수·난이도">
            <p className="tabular-nums" data-testid="rework-factors">
              {reworkFactorText(rework)}
            </p>
            {rework.difficulty && (
              <p className="text-foreground-secondary">
                배수 = 확정일 단계, 난이도 = 블록 형상·의장·전장 밀도(두 값의 곱 ≠ 배수)
              </p>
            )}
          </Row>
        )}
        {line.factors.length > 0 && (
          <Row title="가정과 범위">
            <Factors line={line} />
          </Row>
        )}
        {outlook.length > 0 && (
          <Row title="늦어지면">
            {outlook.map((sentence, i) => (
              <p key={sentence} className={cn(i > 0 && 'font-medium')}>
                {sentence}
              </p>
            ))}
          </Row>
        )}
        {delays.length > 0 && (
          <Row title="일정">
            <p className="tabular-nums">{delays.map((d) => `${d.name} +${d.days}일`).join(' · ')}</p>
            <p className="text-foreground-secondary">이 블록 공정의 늘어나는 예상 일수(일정 계산 추정, 설계변경 전체 기준)</p>
          </Row>
        )}
        {hold && (
          <Row title="보류 권고">
            <p>{holdSentence(hold)}</p>
            {holdApproval && <p className="text-foreground-secondary">{holdApproval}</p>}
          </Row>
        )}
      </dl>
      {(share || target) && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-border pt-2.5">
          <span className="text-foreground-secondary">{share}</span>
          {target && (
            <Button
              variant="outline"
              size="sm"
              className={cn(compact && 'h-11 px-3')}
              onClick={() => onEvidence(target)}
            >
              <Waypoints aria-hidden />
              영향 지도에서 근거 보기
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

interface Props {
  result: AnalysisResult
  /** 좁은 화면: 단추는 터치 높이. */
  compact: boolean
  /** '영향 지도에서 근거 보기': 그 엔터티를 골라 영향 지도의 근거를 연다. */
  onEvidence: (entityId: string) => void
}

interface LineItemProps extends Omit<DetailProps, 'id' | 'line'> {
  line: CostLine
  expanded: boolean
  onToggle: () => void
}

/** 비용 줄 한 줄: 누르면 펼침(발생 사유 · 계산 · 가정과 범위 …). */
function LineItem({ line, expanded, onToggle, ...detail }: LineItemProps) {
  // 펼침 ID는 줄 순서로(묶음 안 줄도 같은 번호 체계 — 표 안에서 겹치지 않게)
  const detailId = `cost-line-${detail.sorted.indexOf(line)}`
  const meta = lineMeta(line)
  return (
    <li>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={expanded ? detailId : undefined}
        onClick={onToggle}
        className="flex min-h-9 w-full items-center gap-3 px-3 py-2 text-left hover:bg-hover"
      >
        <ChevronRight
          aria-hidden
          className={cn('size-4 shrink-0 text-foreground-secondary transition-transform', expanded && 'rotate-90')}
        />
        <span className="min-w-0 flex-1">
          <span className="block">{lineLabel(line)}</span>
          {meta && <span className="block text-sm text-foreground-secondary tabular-nums">{meta}</span>}
        </span>
        {line.determinacy === 'state_unknown' && <UnknownBadge />}
        <AmountCell value={line.amount.value} low={line.amount.low} high={line.amount.high} />
      </button>
      {expanded && <LineDetail line={line} id={detailId} {...detail} />}
    </li>
  )
}

export function CostTable({ result, compact, onEvidence }: Props) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })
  const { total, unresolved } = result
  const sorted = sortedLines(result.cost_lines)
  const detail = { result, sorted, compact, onEvidence }
  const lineItem = (line: CostLine) => (
    <LineItem
      key={line.line_id}
      line={line}
      expanded={open.has(line.line_id)}
      onToggle={() => toggle(line.line_id)}
      {...detail}
    />
  )
  const sections = costSections(result, sorted)
  const groupRow = (row: CostRow) => {
    if (row.kind === 'line') return lineItem(row.line)
    const { group } = row
    const key = `group:${group.key}`
    const expanded = open.has(key)
    const listId = `cost-group-${group.key}`
    const meta = groupMeta(group.lines)
    return (
      <li key={key} data-testid="cost-group">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={expanded ? listId : undefined}
          onClick={() => toggle(key)}
          className="flex min-h-9 w-full items-center gap-3 px-3 py-2 text-left hover:bg-hover"
        >
          <ChevronRight
            aria-hidden
            className={cn('size-4 shrink-0 text-foreground-secondary transition-transform', expanded && 'rotate-90')}
          />
          <span className="min-w-0 flex-1">
            <span className="block">
              {group.label} <span className="text-foreground-secondary tabular-nums">{group.lines.length}건</span>
            </span>
            {meta && <span className="block text-sm text-foreground-secondary tabular-nums">{meta}</span>}
          </span>
          {group.lines.some((line) => line.determinacy === 'state_unknown') && <UnknownBadge />}
          <AmountCell value={group.amount.value} low={group.amount.low} high={group.amount.high} />
        </button>
        {expanded && (
          <ul id={listId} aria-label={`${group.label} ${group.lines.length}건`} className="divide-y divide-border border-t border-border pl-6">
            {group.lines.map(lineItem)}
          </ul>
        )}
      </li>
    )
  }
  return (
    <div className="space-y-3">
      {unresolved.length > 0 && (
        <div role="note" className="rounded-md border border-warning/40 bg-warning/8 px-3 py-2 text-sm">
          <p className="flex items-center gap-1.5 font-medium">
            <CircleAlert aria-hidden className="size-4 shrink-0 text-warning" />
            계산 불가 항목 있음
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-foreground-secondary">
            {unresolved.map((u, i) => (
              <li key={`${u.kind}-${u.entity_id ?? i}`}>
                {nameOf(UNRESOLVED_NAMES, u.kind)}
                {u.entity_id && <span className="font-mono"> {u.entity_id}</span>}: {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul aria-label="비용 줄" className="divide-y divide-border border-y border-border">
        {sections
          ? sections.map((section) => (
              <SectionRows key={section.kind} section={section} result={result} renderRow={groupRow} />
            ))
          : groupLines(sorted).map(groupRow)}
        <li className="flex items-center gap-3 px-3 py-2.5 text-base">
          <span className="min-w-0 flex-1 pl-7 font-semibold">합계</span>
          <AmountCell value={total.value} low={total.low} high={total.high} strong />
        </li>
      </ul>
      <DelayRippleRow result={result} />
    </div>
  )
}
