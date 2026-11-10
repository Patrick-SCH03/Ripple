// 사전 점검(계약 1.32.0, docs/engine.md(사전 점검)): 결재 전에 현장에서 자주 터지는 누락을 연결 지도에서 짚은 확인 항목.
// 할 일 아래 한 칸: 머리(요약, 무엇을 검사하는지는 ⓘ) · 항목(수준 순) · 맨 아래 '현장 통보' 묶음.
// 처음에는 항목마다 무엇 한 줄로 접어 두고(상세가 길어지지 않게) '근거·이유 보기'로 편다. 편 항목마다 무엇(finding) · 규칙
// 이름 · 수준 · 이 건의 한 줄 · 대상(누르면 영향 지도에서 그 카드) · 근거 경로 · 위험 이유 · '같은 유형 합성 NCR n건'(합성
// 묶음 — 실데이터 모드는 건수가 없어 칩 없음). 표시 계산은 lib/precheck.
import { ChevronDown, CircleCheck, CircleHelp, Info, TriangleAlert, Users, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { AnalysisResult, PrecheckItem, PrecheckLevel } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { TermInfo } from '@/components/common/TermInfo'
import { Button } from '@/components/ui/button'
import {
  PRECHECK_LEVEL_NAMES,
  evidenceText,
  ncrText,
  notifyLine,
  precheckView,
  targetsOf,
  type NotifyGroup,
} from '@/lib/precheck'
import { cn } from '@/lib/utils'
import { CrewNoticeDialog, NoticeOpenButton } from './CrewNoticeDialog'
import { SubSection } from './DetailSection'

interface Props {
  result: AnalysisResult
  compact: boolean
  /** 대상을 누르면: 그 엔터티를 골라 영향 지도의 근거를 연다. */
  onEvidence: (entityId: string) => void
  /** 할 일 카드의 첫 소구역이면(조치 묶음 없음) 위 구분선을 뺀다. */
  first?: boolean
  /** 1.37.0 '통보문 보기' 대화상자의 메일 카드가 Gmail로 열 수 있는가(합성 데이터 지도만). */
  webMail?: boolean
  /** '통보문 보기'(현장 통보 묶음 옆): 작업반 통보문 대화상자를 연다. */
  onNotice?: () => void
}

const LEVEL_ICON: Record<PrecheckLevel, LucideIcon> = { check: TriangleAlert, caution: Info, unchecked: CircleHelp }
const LEVEL_TONE: Record<PrecheckLevel, string> = {
  check: 'text-warning',
  caution: 'text-primary',
  unchecked: 'text-foreground-secondary',
}

function LevelChip({ level }: { level: PrecheckLevel }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center rounded-sm border px-1.5 text-xs font-medium',
        level === 'check' ? 'border-warning/40 text-warning' : 'border-border text-foreground-secondary',
      )}
    >
      {PRECHECK_LEVEL_NAMES[level]}
    </span>
  )
}

function Targets({ item, result, compact, onEvidence }: { item: Pick<PrecheckItem, 'targets'> } & Props) {
  const targets = targetsOf(item, result.graph.nodes)
  if (targets.length === 0) return null
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
      <span className="text-foreground-secondary">대상</span>
      {targets.map((target) =>
        target.node ? (
          <button
            key={target.id}
            type="button"
            onClick={() => onEvidence(target.node as string)}
            className={cn('rounded-sm text-primary underline-offset-4 hover:underline', compact && 'min-h-11')}
          >
            {target.name}
          </button>
        ) : (
          <span key={target.id}>{target.name}</span>
        ),
      )}
    </p>
  )
}

function Item({ item, ...props }: { item: PrecheckItem } & Props) {
  const Icon = LEVEL_ICON[item.level]
  const links = item.evidence.slice(0, 3)
  return (
    <li className="space-y-1 px-3 py-2.5" data-precheck={item.rule_id}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Icon aria-hidden className={cn('size-4 shrink-0', LEVEL_TONE[item.level])} />
        <span className="font-medium">{item.finding}</span>
        <LevelChip level={item.level} />
        <WhyInfo title={item.name} reason={item.reason} ncr={item.ncr_count} />
      </p>
      <p>{item.text}</p>
      <Targets item={item} {...props} />
      {links.length > 0 && (
        <p className="text-sm text-foreground-secondary">
          근거 {links.map((link) => evidenceText(link, props.result.graph.nodes)).join(' · ')}
          {item.evidence.length > links.length && ` 외 ${item.evidence.length - links.length}개`}
        </p>
      )}
    </li>
  )
}

/** 위험 이유 · 규칙 이름 · 합성 NCR 건수: 펼친 항목에서도 늘 떠 있는 회색 줄 대신 ⓘ 한 곳에(DESIGN.md 2절). */
function WhyInfo({ title, reason, extra, ncr }: { title: string; reason: string; extra?: string; ncr: number | null | undefined }) {
  const lines = [reason, extra, ncrText(ncr) ? `(시연용 합성 묶음 — 실제 이력 아님)` : null].filter(
    (line): line is string => Boolean(line),
  )
  return (
    <span data-testid={ncr != null ? 'precheck-ncr' : undefined}>
      <InfoPop title={title} lines={lines} label="이유" />
    </span>
  )
}

/** P-06 현장 공유: 블록마다 한 줄로 묶어 맨 아래에(다른 확인 항목을 묻지 않게). */
function NotifyItem({ group, ...props }: { group: NotifyGroup } & Props) {
  return (
    <li className="space-y-2 px-3 py-2.5" data-precheck="P-06" data-testid="precheck-notify">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Users aria-hidden className="size-4 shrink-0 text-warning" />
        <span className="font-medium">현장 통보 필수 · 블록 {group.items.length}곳</span>
        <LevelChip level="check" />
        <WhyInfo
          title="현장 통보"
          reason={group.reason}
          extra="결재 뒤 알림 초안에 작업반(사내 협력사) 통보 포함"
          ncr={group.ncr}
        />
        {props.onNotice && (
          <span className="ml-auto">
            <NoticeOpenButton onClick={props.onNotice} compact={props.compact} />
          </span>
        )}
      </p>
      {/* 블록마다 핵심 한 줄(누구에게 통보) + 보조 한 줄(이미 한 공정) — 서버 문장을 lib/precheck notifyLine이 나눔 */}
      <ul className="space-y-1.5">
        {group.items.map((item) => {
          const line = notifyLine(item.text)
          const target = targetsOf({ targets: item.targets.slice(0, 1) }, props.result.graph.nodes)[0]
          return (
            <li key={item.key}>
              {target?.node ? (
                <button
                  type="button"
                  onClick={() => props.onEvidence(target.node as string)}
                  className={cn('text-left font-medium underline-offset-4 hover:underline', props.compact && 'min-h-11')}
                  title="영향 지도에서 근거 보기"
                >
                  {line.head}
                </button>
              ) : (
                <p className="font-medium">{line.head}</p>
              )}
              {line.done && <p className="text-sm text-foreground-secondary">{line.done}</p>}
            </li>
          )
        })}
      </ul>
    </li>
  )
}

/** 접은 모양: 항목마다 무엇 한 줄(수준 아이콘 · 무엇 · 수준 칩)과 현장 통보 한 줄 — 자세한 근거·이유는 펼쳐서. */
function Brief({
  view,
  onNotice,
  compact,
}: {
  view: NonNullable<ReturnType<typeof precheckView>>
  onNotice?: () => void
  compact: boolean
}) {
  return (
    <ul className="divide-y divide-border rounded-md border border-border" data-testid="precheck-brief">
      {view.items.map((item) => {
        const Icon = LEVEL_ICON[item.level]
        return (
          <li key={item.key} className="flex items-center gap-2 px-3 py-2">
            <Icon aria-hidden className={cn('size-4 shrink-0', LEVEL_TONE[item.level])} />
            <span className="min-w-0 flex-1 font-medium">{item.finding}</span>
            <LevelChip level={item.level} />
          </li>
        )
      })}
      {view.notify && (
        <li className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-3 py-2">
          <Users aria-hidden className="size-4 shrink-0 text-warning" />
          {/* 좁으면 칩·단추 묶음이 다음 줄 오른쪽으로(제목이 한 글자씩 접히지 않게) */}
          <span className="min-w-0 flex-1 basis-56 font-medium break-keep">
            현장 통보 필수 · 블록 {view.notify.items.length}곳
          </span>
          <span className="ml-auto flex items-center gap-2">
            <LevelChip level="check" />
            {onNotice && <NoticeOpenButton onClick={onNotice} compact={compact} />}
          </span>
        </li>
      )}
    </ul>
  )
}

export function PrecheckSection(props: Props) {
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState(false)
  const view = precheckView(props.result)
  if (!view) return null
  const onNotice = view.notify ? () => setNotice(true) : undefined
  const empty = view.items.length === 0 && !view.notify
  return (
    <SubSection
      id="precheck-title"
      title="사전 점검"
      first={props.first}
      testId="prechecks"
      info={
        <>
          <TermInfo term="precheck" />
          {view.summary && <span className="text-base text-foreground-secondary">{view.summary}</span>}
        </>
      }
      action={
        !empty && (
          <Button
            variant="ghost"
            size="sm"
            className={cn(props.compact && 'h-11 px-3')}
            aria-expanded={open}
            aria-controls={open ? 'precheck-items' : undefined}
            onClick={() => setOpen((value) => !value)}
            data-testid="precheck-toggle"
          >
            {open ? '접기' : '근거·이유 보기'}
            <ChevronDown aria-hidden className={cn('transition-transform', open && 'rotate-180')} />
          </Button>
        )
      }
    >
      {!empty && !open ? (
        <Brief view={view} onNotice={onNotice} compact={props.compact} />
      ) : empty ? (
        <div className="flex items-start gap-1.5 rounded-md border border-border px-3 py-2.5 text-sm">
          <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
          {/* 무엇을 점검했는지는 제목 옆 ⓘ(precheck)에 */}
          <p className="font-medium">해당 항목 없음</p>
        </div>
      ) : (
        <ul id="precheck-items" className="divide-y divide-border rounded-md border border-border">
          {view.items.map((item) => (
            <Item key={item.key} item={item} {...props} />
          ))}
          {view.notify && <NotifyItem group={view.notify} {...props} onNotice={onNotice} />}
        </ul>
      )}
      {view.notify && (
        <CrewNoticeDialog open={notice} onOpenChange={setNotice} result={props.result} webMail={props.webMail ?? false} />
      )}
    </SubSection>
  )
}
