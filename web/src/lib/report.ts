// 판단 리포트(docs/records.md(기록·결재) 9절 · DESIGN.md 14절): 기록된 개정 하나를 결재 문서로 옮긴다. 숫자는 모두 그 기록 본문의 분석
// 결과에서 오고(지금 다시 계산하지 않음), 화면 상세와 같은 함수(keyNumbers·todos·sortedLines·curveSteps·scheduleSummary)를 써
// 화면 = 리포트가 된다. 개정은 ECN 번호 + 개정 번호로 고른다 — 기록 ID는 개정마다 유일하지 않다(옛 내용으로 되돌린 개정은 옛 기록을
// 다시 가리킴). 결재 이력은 그 개정을 가리키는 감사 줄 + 뒤 개정의 기록이 끝낸 그 개정의 검토(대체)다.
import type {
  Amount,
  AnalysisResult,
  AuditEntry,
  CostLine,
  EcnDetail,
  EcnRecord,
  EcnState,
  RevisionSummary,
  TraceChain,
  VerdictLevel,
} from '@/api/client'
import { formatKstTime, whoLabel } from './account'
import {
  ELIGIBILITY_NAMES,
  REQUEST_ALT,
  recommendationHeadline,
  shortName,
  sortedAlternatives,
  type Headline,
} from './alternatives'
import { delayRippleView, type DelayRippleView } from './delayRipple'
import { deadlineMark } from './ecnList'
import { formatDay } from './format'
import { DESIGN_STATUS_NAMES, causeName, type DesignStatus } from './request'
import { VERDICT_NAMES } from './labels'
import { costHead, costSections, formatHours, lineLabel, lineMeta, partSubtotal } from './costSplit'
import { formatMoney, formatRange } from './money'
import { ENTRY_LABEL, entryNotes } from './records'
import { scheduleSummary, type ScheduleSummary } from './schedule'
import { curveSteps, keyNumbers, sortedLines, todoText, todos, type KeyNumber, type TodoText } from './summary'

export interface ReportCost {
  /** section = 공수·재료비 묶음 소계 줄, part = 재료비 안 자재 차이·구매 소계 줄, line = 비용 줄(1.35.0 전 기록은 line만). */
  level: 'section' | 'part' | 'line'
  label: string
  /** 줄의 짧은 근거(공수 줄 MH·작업반, 재료비 줄 수량·단가, 공수 묶음의 MH). */
  meta: string | null
  value: string
  range: string | null
  unknown: boolean
}

/** 비용 내역 줄(DESIGN.md 14절): 구분이 있으면 공수 · 재료비(자재 차이 · 구매) 묶음과 소계, 없으면 금액 큰 순 줄만. */
function reportCosts(result: AnalysisResult): ReportCost[] {
  const sorted = sortedLines(result.cost_lines)
  const line = (l: CostLine): ReportCost => ({
    level: 'line',
    label: lineLabel(l),
    meta: lineMeta(l),
    value: formatMoney(l.amount.value),
    range: range(l.amount.low, l.amount.high),
    unknown: l.determinacy === 'state_unknown',
  })
  const sections = costSections(result, sorted)
  if (!sections || !result.cost_split) return sorted.map(line)
  const split = result.cost_split
  const sum = (level: ReportCost['level'], label: string, amount: Amount, meta: string | null = null): ReportCost => ({
    level,
    label,
    meta,
    value: formatMoney(amount.value),
    range: range(amount.low, amount.high),
    unknown: false,
  })
  return sections.flatMap((section) => [
    sum(
      'section',
      section.title,
      section.subtotal,
      section.hours ? `${formatHours(section.hours.value)} MH` : null,
    ),
    ...section.parts.flatMap((part) => [
      ...(section.kind === 'material' ? [sum('part', part.title, partSubtotal(split, part.key))] : []),
      ...part.lines.map(line),
    ]),
  ])
}

export interface ReportStep {
  day: string
  total: string
  added: string
  events: string
}

export interface ReportAlternative {
  name: string
  judgement: string
  exit: string
  deadline: string
  total: string
  recommended: boolean
}

export interface ReportHistory {
  seq: number
  state: EcnState
  label: string
  who: string
  when: string
  notes: string[]
}

export interface ReportModel {
  ecnId: string
  title: string
  revision: number
  /** 이 개정 뒤의 최신 개정 번호(없으면 null). */
  newer: number | null
  recordId: string
  recordedBy: string
  recordedAt: string
  synthetic: boolean
  ships: string
  /** 1.23.0 설계 승인 상태와 적용 시작일(정보). */
  design: string
  /** 1.28.0 변경 원인(옛 기록·미입력은 '미입력'). */
  cause: string
  conditions: string[]
  /** 1.23.0 연결 추적(옛 기록은 null). */
  trace: TraceChain[] | null
  verdict: { level: VerdictLevel; name: string; reasons: string[] }
  numbers: KeyNumber[]
  todos: TodoText[]
  costs: ReportCost[]
  /** sum = 1.35.0 구분이 있으면 '공수 + 재료비'(지체상금이 붙으면 + 지체상금), 없으면 null. */
  total: { value: string; range: string | null; sum: string | null }
  /** 1.32.0 총액 밖 지연 파급 비용(가정). 이 판을 계산하지 않은 옛 기록이면 null. */
  outside: DelayRippleView | null
  schedule: ScheduleSummary
  steps: ReportStep[]
  alternatives: { headline: Headline | null; rows: ReportAlternative[] } | null
  checklist: { source: string; text: string }[]
  history: ReportHistory[]
}

export type ReportProblem = 'no_revision' | 'record_mismatch'

/** 설계 승인 상태 · 적용 시작일 한 줄(계약 1.23.0 전 기록은 미입력). */
export function designText(status: string | undefined, effectiveOn: string | null): string {
  const name = DESIGN_STATUS_NAMES[(status ?? 'unknown') as DesignStatus] ?? status ?? '미입력'
  return effectiveOn ? `${name} · 적용 시작 ${formatDay(effectiveOn)}` : name
}

/** 연결 추적 고리 한 칸: 이름은 늘, 상태는 있을 때만 뒤에(리포트 표). */
export function traceLinkText(link: { label: string; status?: string | null }): string {
  return link.status ? `${link.label} · ${link.status}` : link.label
}

const range = (low: number, high: number): string | null => (low === high ? null : formatRange(low, high))

/** 그 개정의 결재 이력: 개정을 가리키는 감사 줄 + 뒤 개정의 기록이 끝낸 그 개정의 검토(순번 순). */
export function historyOf(audit: readonly AuditEntry[], revision: number): AuditEntry[] {
  const reviews = new Set(
    audit.filter((e) => e.revision === revision && e.action === 'request_review').map((e) => e.seq),
  )
  return audit
    .filter(
      (e) =>
        e.revision === revision ||
        (e.detail.superseded_review_seq != null && reviews.has(e.detail.superseded_review_seq)),
    )
    .sort((a, b) => a.seq - b.seq)
}

function historyRow(entry: AuditEntry, revision: number): ReportHistory {
  const later = entry.revision !== revision && entry.action === 'record'
  return {
    seq: entry.seq,
    state: entry.detail.to_state,
    label: later ? `개정 ${entry.revision} 기록(이 검토는 여기서 끝남)` : `${ENTRY_LABEL[entry.action]}`,
    who: whoLabel(entry.actor),
    when: formatKstTime(entry.at),
    notes: entryNotes(entry),
  }
}

/** ECN 상세 + 그 개정의 기록 본문 → 리포트. 개정이 없거나 기록이 그 개정의 것이 아니면 문제 코드. */
export function reportOf(detail: EcnDetail, record: EcnRecord, revision: number): ReportModel | ReportProblem {
  const summary: RevisionSummary | undefined = detail.revisions.find((r) => r.revision === revision)
  if (!summary) return 'no_revision'
  if (summary.record_id !== record.record_id || record.body.ecn_id !== detail.status.ecn_id) return 'record_mismatch'
  const { result, checklist } = record.body
  const { request } = result
  const latest = detail.revisions.at(-1)?.revision ?? revision
  const conditions = [
    `기준일 ${formatDay(request.as_of)}`,
    `확정일 ${formatDay(summary.confirm_on)}`,
    request.holds.length > 0
      ? `발주 보류 ${request.holds.map((h) => `${h.po_id} ${h.hold_days}일`).join('·')}`
      : '발주 보류 없음',
    ...(request.outfit_on_board ? ['후행 설치'] : []),
    ...(request.include_alternatives ? ['대안 포함'] : []),
  ]
  const ranked = sortedAlternatives(result.alternatives)
  return {
    ecnId: detail.status.ecn_id,
    title: request.change.title,
    revision,
    newer: latest > revision ? latest : null,
    recordId: record.record_id,
    recordedBy: whoLabel(summary.recorded_by),
    recordedAt: formatKstTime(summary.recorded_at),
    synthetic: record.body.data_mode === 'synthetic',
    ships: request.change.ship_ids.join(', '),
    design: designText(request.change.design_status, request.change.effectivity?.effective_on ?? null),
    cause: causeName(request.change.cause),
    conditions,
    trace: result.trace ? [...result.trace] : null,
    verdict: {
      level: result.verdict.level,
      name: VERDICT_NAMES[result.verdict.level] ?? result.verdict.level,
      reasons: [...result.verdict.reasons],
    },
    numbers: keyNumbers(result),
    // 보류 권고의 결재 기간은 기록 조회가 실어 준 결재 계획 그대로(서버 한 곳 규칙)
    todos: todos(result).map((todo) => todoText(todo, result.timing.deadline, record.approval_plan)),
    costs: reportCosts(result),
    total: {
      value: formatMoney(result.total.value),
      range: range(result.total.low, result.total.high),
      sum: costHead(result)?.total.sum ?? null,
    },
    outside: delayRippleView(result),
    schedule: scheduleSummary(result),
    steps: curveSteps(result.timing.curve).map((step) => ({
      day: formatDay(step.day),
      total: formatMoney(step.total),
      added: formatMoney(step.added),
      events: step.events.join(' · '),
    })),
    alternatives:
      result.alternatives.length > 1
        ? {
            headline: recommendationHeadline(result),
            rows: ranked.map((alt) => ({
              name: shortName(alt),
              judgement: alt.alt_id === REQUEST_ALT ? '비교 기준' : ELIGIBILITY_NAMES[alt.eligibility.status],
              exit: alt.max_exit_delay_days > 0 ? `${alt.max_exit_delay_days}일` : '없음',
              deadline: alt.deadline ? deadlineMark(alt.deadline, request.as_of).text : '-',
              total: formatMoney(alt.total.value),
              recommended: result.recommendation?.alt_id === alt.alt_id,
            })),
          }
        : null,
    checklist: checklist.map((item) => ({ source: item.source === 'import' ? '엑셀' : '분석', text: item.text })),
    history: historyOf(detail.audit, revision).map((entry) => historyRow(entry, revision)),
  }
}

/** 리포트 주소: /app/report/<ECN 번호>/<개정 번호>. */
export function reportPath(ecnId: string, revision: number): string {
  return `/app/report/${encodeURIComponent(ecnId)}/${revision}`
}
