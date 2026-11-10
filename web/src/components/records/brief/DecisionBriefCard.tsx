// 결정 도우미 카드(DESIGN.md 13절): 결재자가 결재 띠에서 3초 안에 판단하게 — 맨 위 큰 숫자 카드 셋(총변경비용 · 결정 기한 ·
// 권고) · 바뀌는 것 한 줄 · 서명 전 확인할 것(제목 한 줄, 세부는 항목별 펼침) · 비슷한 과거 사례(접힘).
// 세 줄 요약 문장(범위·공수·재료비 포함)은 지우지 않고 '요약 문장 보기' 펼침에 그대로. 문장·숫자는 서버(기록 본문의 엔진 결과)가
// 만든 그대로이고 카드 숫자는 lib/brief briefHead(개정 요약·그 개정의 결과, 서버 문장과 같은 값일 때만).
// 불러오는 중은 자리만 잡은 뼈대, 실패는 조용한 한 줄이고 어느 쪽이든 결재 단추를 막지 않는다.
import { Calculator, ChevronDown, CircleAlert, ListChecks, Sparkles } from 'lucide-react'
import { useId, useState } from 'react'
import type { BriefCheck, DecisionBrief } from '@/api/client'
import { HEAD_CARD, VALUE_TONE } from '@/components/common/numberCard'
import { LINE_LABEL, casesView, checkTitle, pickedLabel, type BriefHead, type ChangeHead, type HeadCard } from '@/lib/brief'
import { cn } from '@/lib/utils'
import { PastCasesList } from './PastCasesList'
import type { BriefView } from './useDecisionBrief'

const CHIP = 'inline-flex h-6 shrink-0 items-center gap-1 rounded-sm border px-1.5 text-xs font-medium whitespace-nowrap'
const TOGGLE =
  'inline-flex min-h-8 shrink-0 items-center gap-1 text-sm font-semibold text-primary underline-offset-2 hover:underline'

/** 맨 위 카드 셋과 바뀌는 것 한 줄(개정 요약이 있을 때 — 없으면 문장만). */
export interface BriefGlance {
  head: BriefHead
  change: ChangeHead
}

export function DecisionBriefCard({ view, glance = null }: { view: BriefView; glance?: BriefGlance | null }) {
  const brief = view.status === 'ready' ? view.brief : null
  return (
    <section
      aria-label="결정 도우미"
      aria-busy={view.status === 'loading'}
      className="@container mt-3 rounded-md border border-border bg-surface px-4 py-3"
      data-testid="decision-brief"
      data-state={view.status}
    >
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 className="text-md font-semibold">결정 도우미</h3>
        {brief && <PickedChip by={brief.picked_by} />}
      </header>
      {view.status === 'loading' && <Skeleton />}
      {view.status === 'error' && (
        <p className="mt-2 text-sm text-foreground-secondary" data-testid="decision-brief-error">
          도우미 불러오기 실패 — 결재는 그대로 가능
        </p>
      )}
      {brief && <BriefBody brief={brief} glance={glance} />}
    </section>
  )
}

function PickedChip({ by }: { by: DecisionBrief['picked_by'] }) {
  const ai = by === 'ai'
  return (
    <span
      className={cn(CHIP, ai ? 'border-agent/40 text-agent' : 'border-border text-foreground-secondary')}
      data-testid="decision-brief-picked"
      data-picked={by}
    >
      {ai && <Sparkles aria-hidden className="size-3" />}
      {pickedLabel(by)}
    </span>
  )
}

function Skeleton() {
  return (
    <div className="mt-2.5 grid gap-3 @min-[44rem]:grid-cols-3" aria-hidden data-testid="decision-brief-skeleton">
      {['a', 'b', 'c'].map((key) => (
        <div key={key} className="h-24 rounded-md bg-muted motion-safe:animate-pulse" />
      ))}
    </div>
  )
}

function BriefBody({ brief, glance }: { brief: DecisionBrief; glance: BriefGlance | null }) {
  return (
    <>
      {glance && <HeadCards head={glance.head} />}
      <ChangeAndLines brief={brief} change={glance?.change ?? null} />
      {brief.checks.length > 0 && <Checks checks={brief.checks} />}
      {casesView(brief.cases) === 'building' && (
        <p className="mt-3 border-t border-border pt-2.5 text-sm text-foreground-secondary" data-testid="decision-brief-cases-building">
          과거 사례 준비 중
        </p>
      )}
      {casesView(brief.cases) === 'list' && <PastCasesList cases={brief.cases} />}
    </>
  )
}

/**
 * 큰 숫자 카드 셋(판단 요약 첫 줄과 같은 틀 HEAD_CARD · 큰 숫자 text-key-lg): 이름 · 큰 숫자 · 행동 한 줄까지.
 * 카드 칸 44rem 이상이면 한 줄 셋, 좁으면 총변경비용 한 줄 전체 + 아래 두 카드 나란히.
 */
function HeadCards({ head }: { head: BriefHead }) {
  const cards: { id: string; card: HeadCard; className: string }[] = [
    { id: 'total', card: head.total, className: 'col-span-2 border-border-strong @min-[44rem]:col-span-1' },
    { id: 'deadline', card: head.deadline, className: 'border-border' },
    { id: 'advice', card: head.advice, className: 'border-border' },
  ]
  return (
    <div className="mt-2.5 grid grid-cols-2 gap-3 @min-[44rem]:grid-cols-3" data-testid="decision-brief-head">
      {cards.map(({ id, card, className }) => (
        <div key={id} data-brief-card={id} className={cn(HEAD_CARD, className)}>
          <p className="text-base font-medium text-foreground-secondary">{card.label}</p>
          {card.value !== null ? (
            <>
              {/* text-key-lg는 cn으로 합치지 않는다(numberCard.ts) */}
              <p className={`mt-1 text-key-lg font-bold tabular-nums ${VALUE_TONE[card.tone]}`}>{card.value}</p>
              {card.line && (
                // ' · ' 마디마다 한 줄(가운뎃점 없이) — 금액이 홀로 떨어지거나 줄이 '·'로 시작하지 않게
                <p className="mt-1 text-sm font-medium tabular-nums text-foreground break-keep">
                  {card.line.split(' · ').map((part) => (
                    <span key={part} className="block">
                      {part}
                    </span>
                  ))}
                </p>
              )}
            </>
          ) : (
            card.line && <p className="mt-1 line-clamp-3 text-base font-medium break-keep" title={card.line}>{card.line}</p>
          )}
        </div>
      ))}
    </div>
  )
}

/** 바뀌는 것 한 줄(변경 · 영향 n곳 · 블록 칩) + 세 줄 요약 문장 펼침(범위·공수·재료비·권고 근거 그대로). */
function ChangeAndLines({ brief, change }: { brief: DecisionBrief; change: ChangeHead | null }) {
  const [open, setOpen] = useState(false)
  const linesId = useId()
  return (
    <div className="mt-3" data-testid="decision-brief-change">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        {change ? (
          <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-base">
            <span className="text-sm font-medium text-foreground-secondary">바뀌는 것</span>
            <span className="font-semibold break-keep">{change.title}</span>
            {change.impacts !== null && <span className="tabular-nums text-foreground-secondary">· 영향 {change.impacts}곳</span>}
            {change.blocks.map((code) => (
              <span key={code} className={cn(CHIP, 'border-border font-mono text-foreground')}>
                {code}
              </span>
            ))}
            {change.moreBlocks > 0 && <span className="text-sm text-foreground-secondary">외 {change.moreBlocks}개</span>}
          </p>
        ) : (
          <span className="text-sm font-medium text-foreground-secondary">요약 문장 3줄</span>
        )}
        <button
          type="button"
          className={TOGGLE}
          aria-expanded={open}
          aria-controls={linesId}
          onClick={() => setOpen((value) => !value)}
          data-testid="decision-brief-lines-toggle"
        >
          {open ? '요약 문장 접기' : '요약 문장 보기'}
          <ChevronDown aria-hidden className={cn('size-4 transition-transform', open && 'rotate-180')} />
        </button>
      </div>
      {open && (
        <dl id={linesId} className="mt-2 space-y-1.5 rounded-sm bg-muted px-3 py-2" data-testid="decision-brief-lines">
          {brief.lines.map((line) => (
            <div
              key={line.kind}
              className="grid gap-0.5 @md:grid-cols-[6.5rem_minmax(0,1fr)] @md:gap-3"
              data-kind={line.kind}
            >
              <dt className="text-sm font-medium text-foreground-secondary @md:pt-0.5">{LINE_LABEL[line.kind]}</dt>
              <dd className="text-base break-keep">{line.text}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

function Checks({ checks }: { checks: readonly BriefCheck[] }) {
  return (
    <div className="mt-3 border-t border-border pt-2.5" data-testid="decision-brief-checks">
      <h4 className="flex items-center gap-1.5 text-md font-semibold">
        <ListChecks aria-hidden className="size-5 text-warning" />
        서명 전 확인할 것 {checks.length}
      </h4>
      <ol className="mt-1 divide-y divide-border">
        {checks.map((check) => (
          <CheckRow key={check.key} check={check} />
        ))}
      </ol>
    </div>
  )
}

/** 확인할 것 한 줄: 아이콘 + 짧은 제목 + '다시 계산함'(늘 보임) · 펼치면 문장 전체와 '틀리면 · 이유'. */
function CheckRow({ check }: { check: BriefCheck }) {
  const [open, setOpen] = useState(false)
  const detailId = useId()
  const title = checkTitle(check)
  return (
    <li data-key={check.key} className="py-1.5">
      <div className="flex items-start gap-2">
        <CircleAlert aria-hidden className="mt-1 size-5 shrink-0 text-warning" />
        <p className="min-w-0 flex-1 text-base font-medium break-keep">{title}</p>
        {check.computed && (
          <span className={cn(CHIP, 'mt-0.5 border-primary/40 text-primary')} data-testid="decision-brief-computed">
            <Calculator aria-hidden className="size-3" />
            다시 계산함
          </span>
        )}
        <button
          type="button"
          className={cn(TOGGLE, 'min-h-7')}
          aria-expanded={open}
          aria-controls={detailId}
          aria-label={`${title} — ${open ? '세부 접기' : '틀리면 · 세부 보기'}`}
          onClick={() => setOpen((value) => !value)}
          data-testid="decision-brief-check-toggle"
        >
          {open ? '접기' : '세부'}
          <ChevronDown aria-hidden className={cn('size-4 transition-transform', open && 'rotate-180')} />
        </button>
      </div>
      {open && (
        <div id={detailId} className="mt-1 ml-7 space-y-0.5 text-sm text-foreground-secondary" data-testid="decision-brief-check-detail">
          {check.text !== title && <p className="text-foreground break-keep">{check.text}</p>}
          <p className="break-keep">
            <span className="font-medium">틀리면</span> · {check.why}
          </p>
        </div>
      )}
    </li>
  )
}
