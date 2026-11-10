// 결재함(결재자): 검토·보류 중인 설계변경 가운데 내 결재 단계 건을 결정 기한 급한 순으로(파트장 = 파트장 단계, 팀장 =
// 팀장 단계, 본부장 = 본부장 단계 — 서버가 거름, docs/records.md(기록·결재) 14절). 줄마다 '지금 결정하지 않으면 무엇을
// 잃는가'(미루면)·결재선 진행·남은 결재를 넘길 기한을 보이고, 결정은 '열기'로 업무 화면에서 그 개정의 분석을 보며 한다.
// 팀장에게는 아래에 '다른 단계에서 기다리는 건(전결 가능)' 묶음(파트장·본부장 단계 건)을 더 둔다.
import { ExternalLink, FileText, Inbox, Layers, UserCheck } from 'lucide-react'
import { useState } from 'react'
import type { InboxItem } from '@/api/client'
import { VerdictBadge } from '@/components/common/VerdictBadge'
import { SegmentText } from '@/components/common/SegmentText'
import { LineProgress } from '@/components/records/LineProgress'
import { StateText } from '@/components/records/StateChip'
import { Button } from '@/components/ui/button'
import { whoLabel } from '@/lib/account'
import { STEP_LABEL, submitLine, type SubmitLine } from '@/lib/approval'
import {
  INBOX_FILTERS,
  blockLabel,
  delayText,
  dueMark,
  filterInbox,
  stepWaitText,
  waitingText,
  type InboxFilter,
  type Tone,
} from '@/lib/manage'
import { formatMoney, formatRange } from '@/lib/money'
import { reportPath } from '@/lib/report'
import { openRecordPath } from '@/lib/route'
import { cn } from '@/lib/utils'
import { navigate } from '@/state/useRoute'

const DUE_TONE: Record<Tone, string> = {
  danger: 'border-danger/40 text-danger',
  warning: 'border-warning/40 text-warning',
  neutral: 'border-border text-foreground',
  relaxed: 'border-border text-foreground-secondary',
}
// 남은 결재를 넘길 기한 줄: 단계당 1일로도 지났으면 위험, 대표만 지났으면 주의(아직 기한 안에 들 길이 있음)
const SUBMIT_TONE: Record<SubmitLine['tone'], string> = {
  late: 'text-danger',
  caution: 'text-warning',
  ok: 'text-foreground-secondary',
  none: 'text-foreground-secondary',
}

export function InboxPanel({
  items,
  proxy = [],
  now,
}: {
  items: readonly InboxItem[]
  /** 팀장: 다른 단계(파트장·본부장)에서 기다리는 건 — 전결 가능(서버가 팀장에게만 싣는다). */
  proxy?: readonly InboxItem[]
  /** 서버 계산 시각(대기 일수 기준). */
  now: string
}) {
  const [filter, setFilter] = useState<InboxFilter>('all')
  const shown = filterInbox(items, filter)
  const others = proxy.length > 0 && <ProxyGroup items={proxy} now={now} />
  if (items.length === 0) {
    return (
      <div className="space-y-6">
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-6 py-14 text-center">
          <Inbox aria-hidden className="size-8 text-foreground-secondary" />
          <p className="text-md font-semibold">결재 대기 설계변경 없음</p>
          
        </div>
        {others}
      </div>
    )
  }
  return (
    <div className="space-y-6">
      <section aria-label="결재함" className="space-y-3" data-testid="inbox">
        <div role="group" aria-label="결재함 거르기" className="flex flex-wrap gap-2">
          {INBOX_FILTERS.map((option) => {
            const count = filterInbox(items, option.id).length
            return (
              <Button
                key={option.id}
                size="sm"
                variant={filter === option.id ? 'default' : 'outline'}
                aria-pressed={filter === option.id}
                onClick={() => setFilter(option.id)}
              >
                {option.label} <span className="tabular-nums">{count}</span>
              </Button>
            )
          })}
        </div>
        {shown.length === 0 ? (
          <p className="rounded-md border border-border px-4 py-6 text-sm text-foreground-secondary">이 조건의 결재 없음</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border bg-surface">
            {shown.map((item) => (
              <InboxRow key={item.ecn_id} item={item} />
            ))}
          </ul>
        )}
      </section>
      {others}
    </div>
  )
}

/**
 * 다른 단계에서 기다리는 건(전결 가능, 팀장): 단계 · 그 단계 대기 일수 · 결재선 진행 · '전결 열기'(업무 화면에서 그 개정의
 * 분석을 보며 전결 — 결재 띠 단추가 '승인(전결)…', 감사 기록에 전결과 원래 단계).
 */
function ProxyGroup({ items, now }: { items: readonly InboxItem[]; now: string }) {
  return (
    <section aria-labelledby="proxy-title" className="space-y-2" data-testid="proxy-inbox">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 id="proxy-title" className="text-md font-semibold">
          다른 단계에서 기다리는 건(전결 가능) <span className="tabular-nums">{items.length}</span>
        </h2>
      </div>
      <ul className="divide-y divide-border rounded-md border border-border bg-surface">
        {items.map((item) => (
          <li
            key={item.ecn_id}
            className="grid gap-2 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
            data-proxy-item={item.ecn_id}
          >
            <div className="min-w-0 space-y-1">
              <p className="truncate text-md font-semibold" title={item.title}>
                {item.title}
              </p>
              {/* 어느 단계인지는 아래 결재선 칩('본부장 차례')이 말하므로 단계 칩을 따로 두지 않는다(같은 말 두 번) */}
              <p
                className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-foreground-secondary"
                title={`${item.ecn_id} · 개정 ${item.revision} · ${whoLabel(item.requested_by)} 요청 · ${STEP_LABEL[item.step]} 단계`}
              >
                <span className="font-mono">{item.ecn_id}</span>
                <span>
                  {item.requested_by.name} · {stepWaitText(item.step_since ?? item.requested_at, now)}
                </span>
              </p>
              <LineProgress steps={item.steps} current={item.steps.indexOf(item.step) + 1} signed={item.signed} />
            </div>
            <div className="flex flex-wrap items-center gap-2 md:justify-end">
              <span className="text-lg font-semibold tabular-nums">{formatMoney(item.total.value)}</span>
              <Button size="sm" variant="outline" onClick={() => navigate(openRecordPath(item.record_id))} data-testid="proxy-open">
                <UserCheck aria-hidden />
                전결 열기
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function InboxRow({ item }: { item: InboxItem }) {
  const due = dueMark(item)
  const delay = delayText(item)
  const submit = submitLine(item.approval_plan, true)
  // 배치(1024px 이상): [결정 기한 | 제목·메타·결재선 | 금액·단추] 위 줄 + 남은 결재 기한 한 줄을 가운데~오른쪽 전체 폭으로.
  // 기한 줄이 결재선 옆 좁은 칸에서 두 줄로 접히지 않게(1024px · 큰 글자) 따로 한 줄을 준다.
  // 768~1023px는 [결정 기한 | 제목·메타·결재선 / 금액 · 단추 한 줄 / 기한 줄] — 제목 칸이 좁아지지 않게 금액을 아래로.
  return (
    <li
      className="grid gap-x-4 gap-y-2 px-4 py-3 md:grid-cols-[7rem_minmax(0,1fr)] md:items-start lg:grid-cols-[7rem_minmax(0,1fr)_auto]"
      data-inbox-item={item.ecn_id}
    >
      <div
        className={cn(
          'flex w-fit items-baseline gap-2 rounded-md border px-2.5 py-1 md:row-span-3 md:h-16 lg:row-span-2 md:w-auto md:flex-col md:items-center md:justify-center md:gap-0 md:self-center md:py-0',
          DUE_TONE[due.tone],
        )}
        title={due.detail}
      >
        <span className="text-key leading-tight font-semibold tabular-nums">{due.text}</span>
        <span className="sr-only">{due.detail}</span>
        <span aria-hidden className="text-xs whitespace-nowrap text-foreground-secondary">
          결정 기한
        </span>
      </div>
      <div className="min-w-0 space-y-1">
        <p className="truncate text-md font-semibold" title={item.title}>
          {item.title}
        </p>
        {/* 판정 칩 하나 + 작은 한 줄(상태 · ECN · 블록 · 요청한 사람 · 대기) — 개정·역할은 마우스 올림 */}
        <p
          className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-foreground-secondary"
          title={`${item.ecn_id} · 개정 ${item.revision} · ${whoLabel(item.requested_by)} 요청`}
        >
          <VerdictBadge level={item.verdict} size="sm" />
          {item.state === 'on_hold' && <StateText state={item.state} />}
          <span className="font-mono">{item.ecn_id}</span>
          {item.blocks.length > 0 && (
            <span className="inline-flex items-center gap-1">
              <Layers aria-hidden className="size-3.5" />
              {item.blocks.slice(0, 3).map(blockLabel).join(', ')}
              {item.blocks.length > 3 && ` 외 ${item.blocks.length - 3}`}
            </span>
          )}
          <span>
            {item.requested_by.name} · {waitingText(item.waiting_hours)}
            {item.checklist > 0 && <> · 확인 필요 {item.checklist}</>}
            {item.data_mode === 'real' && <> · 실제 데이터</>}
          </span>
        </p>
        <LineProgress steps={item.steps} current={item.steps.indexOf(item.step) + 1} signed={item.signed} />
      </div>
      <div className="flex flex-col gap-2 md:flex-row md:flex-wrap md:items-center md:justify-between lg:flex-nowrap lg:items-start lg:justify-end lg:gap-3">
        <div className="space-y-0.5 md:flex md:flex-wrap md:items-baseline md:gap-x-3 md:space-y-0 lg:block lg:space-y-0.5 lg:text-right">
          {/* 범위는 마우스 올림·검토서에(첫 화면은 큰 금액 하나) */}
          <p className="text-lg font-semibold tabular-nums" title={`범위 ${formatRange(item.total.low, item.total.high)}`}>
            {formatMoney(item.total.value)}
          </p>
          {delay && (
            <p
              className={cn(
                'text-sm lg:whitespace-nowrap',
                (item.delay_cost ?? 0) > 0 ? 'text-warning' : 'text-foreground-secondary',
              )}
            >
              미루면 {delay}
            </p>
          )}
          {item.cheaper_by != null && (
            <p className="text-sm text-success lg:whitespace-nowrap">더 저렴한 대안 −{formatMoney(item.cheaper_by)}</p>
          )}
        </div>
        <div className="flex gap-2 lg:flex-col">
          <Button size="sm" onClick={() => navigate(openRecordPath(item.record_id))} data-testid="inbox-open">
            <FileText aria-hidden />
            열기
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={reportPath(item.ecn_id, item.revision)} target="_blank" rel="noopener">
              <ExternalLink aria-hidden />
              검토서
            </a>
          </Button>
        </div>
      </div>
      {/* 남은 결재 기한(지남 · 결정 가능일 · 추가손실) — 가운데~오른쪽 전체 폭 한 줄 */}
      {submit && (
        <p
          className={cn('text-sm md:col-start-2 lg:col-span-2', SUBMIT_TONE[submit.tone])}
          data-testid="inbox-submit"
          data-tone={submit.tone}
        >
          <SegmentText text={submit.text} keepAll />
        </p>
      )}
    </li>
  )
}
