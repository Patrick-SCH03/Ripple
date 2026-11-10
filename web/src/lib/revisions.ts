// 기록한 개정 다루기(docs/records.md(기록·결재)): 개정에 넣은 가정과 결정 창의 개정 요약, 지금 화면의 분석이 그 개정과
// 같은지 가리는 비교·열쇠. 결재 흐름(lib/records)과 저장 재시도 키(state/useRecords)가 쓴다.
import type { AnalysisResult, RevisionSummary } from '@/api/client'
import { deadlineMark } from './ecnList'
import { daysBetween, formatDay } from './format'
import { VERDICT_NAMES } from './labels'
import { formatMoney, formatRange } from './money'
import { causeName } from './request'
import { URGENT_DAYS } from './summary'

/**
 * 분석에 넣은 가정(발주 보류 · 1.29.0 후행 설치) 한 줄. 보류·후행 설치는 아직 실제로 정한 일이 아니라서,
 * 결재 띠·검토 요청 창에서 이 개정이 가정을 담았다는 것을 보이게 한다(없으면 null).
 */
export function assumedPlan(result: Pick<AnalysisResult, 'request'>): string | null {
  const { holds, outfit_on_board: onBoard } = result.request
  const parts = [
    ...(holds.length > 0 ? [`발주 보류 ${holds.length}건(${holds.map((h) => `${h.po_id} ${h.hold_days}일`).join('·')})`] : []),
    ...(onBoard ? ['후행 설치'] : []),
  ]
  return parts.length > 0 ? parts.join(' · ') : null
}

/** 줄의 종류(글자가 아니라 이것으로 거른다 — restFacts). 'range'는 큰 숫자 칸과 함께 쓸 때의 금액 범위 줄. */
export type FactId = 'verdict' | 'cause' | 'total' | 'range' | 'deadline' | 'confirm' | 'assumed'

export interface Fact {
  id: FactId
  label: string
  value: string
  /** 결정 전에 알아야 할 빈 곳(변경 원인 미입력) — 주의 색. */
  warn?: boolean
  /** 총변경비용 줄의 범위(value 끝 ' · ' 뒤와 같은 글) — 큰 숫자 칸과 함께 쓰면 이 줄만 남긴다. */
  range?: string
}

/**
 * 결정 창에 보일 그 개정의 요약: 기록 본문의 개정 요약 그대로(지금 다시 계산한 값이 아님) — 판정 · 변경 원인 ·
 * 총변경비용(범위) · 추가손실 0 마감 · 확정일 · 넣은 가정(보류·후행 설치·대안). 변경 원인을 모르면(undefined) 줄을 뺀다.
 * 후행 설치는 개정 요약(저장 모델이라 바꾸지 않는다, docs/records.md 4절 판 호환)에 없어, 화면의 분석 = 그 개정일 때 그 요청에서
 * 받는다(onBoard, 모르면 undefined — 승인은 화면 = 그 개정일 때만 열리므로 승인 창에는 늘 있다).
 * 마감은 D-n 없이 날짜로만 적는다: D-n은 그 개정의 기준일부터 센 값이라, 오늘부터 세는 결재함과 다르게 읽힐 수 있다.
 */
export function revisionFacts(revision: RevisionSummary, cause: unknown, onBoard?: boolean): Fact[] {
  const deadline =
    revision.deadline.kind === 'confirm_now'
      ? `${formatDay(revision.deadline.last_day)}(기준일)에 확정해야 추가손실 없음`
      : deadlineMark(revision.deadline, revision.as_of).label
  const holds = revision.holds.map((h) => `${h.po_id} ${h.hold_days}일`).join('·')
  const assumed = [
    holds && `발주 보류 ${revision.holds.length}건(${holds})`,
    onBoard && '후행 설치',
    revision.alternatives && '대안 포함',
  ].filter(Boolean)
  const facts: Fact[] = [{ id: 'verdict', label: '판정', value: VERDICT_NAMES[revision.verdict] ?? revision.verdict }]
  if (cause !== undefined) {
    facts.push(
      cause
        ? { id: 'cause', label: '변경 원인', value: causeName(cause) }
        : { id: 'cause', label: '변경 원인', value: '미입력 — 비용 부담 판단 근거 없음', warn: true },
    )
  }
  const range = formatRange(revision.total.low, revision.total.high)
  facts.push(
    { id: 'total', label: '총변경비용', value: `${formatMoney(revision.total.value)} · ${range}`, range },
    { id: 'deadline', label: '결정 기한', value: deadline },
    { id: 'confirm', label: '확정일', value: formatDay(revision.confirm_on) },
  )
  if (assumed.length > 0) facts.push({ id: 'assumed', label: '가정 계산', value: assumed.join(' · ') })
  return facts
}

/** 결정 창 맨 위 큰 숫자 칸(결정 도우미와 같은 원칙): 이름 · 큰 값 · 행동 한 줄. */
export interface GlanceFact {
  id: 'total' | 'deadline'
  label: string
  value: string
  line: string | null
  tone: 'danger' | 'success' | 'neutral'
}

/**
 * 결정 창 큰 숫자 둘: 총변경비용(금액만 — 범위는 아래 표) · 결정 기한(날짜 — revisionFacts와 같은 까닭으로 D-n 없이,
 * 한 줄 = 그날까지 확정하면 추가손실이 없다는 뜻). 값은 기록 본문의 개정 요약 그대로.
 * 위험 색은 업무상 오늘(today, KST)부터 센 날수로 정한다(결정 도우미 lib/brief 결정 기한 카드·결재함과 같은 기준) —
 * 개정의 기준일부터 세면 오래된 개정은 기한이 지났는데도 보통 색으로 보인다.
 */
export function revisionGlance(revision: RevisionSummary, today: string): GlanceFact[] {
  const { deadline } = revision
  const day = formatDay(deadline.last_day)
  const urgent = (daysBetween(today, deadline.last_day) ?? 0) <= URGENT_DAYS
  const due: GlanceFact =
    deadline.kind === 'confirm_now'
      ? { id: 'deadline', label: '결정 기한', value: day, line: '기준일 · 그날 확정해야 추가손실 없음', tone: 'danger' }
      : deadline.kind === 'none_in_horizon'
        ? { id: 'deadline', label: '결정 기한', value: '기간 안 없음', line: `${day}까지 확정해도 추가손실 없음`, tone: 'success' }
        : {
            id: 'deadline',
            label: '결정 기한',
            value: day,
            line: '그날까지 확정 시 추가손실 없음',
            tone: urgent ? 'danger' : 'neutral',
          }
  return [{ id: 'total', label: '총변경비용', value: formatMoney(revision.total.value), line: null, tone: 'neutral' }, due]
}

/**
 * 큰 숫자 칸과 함께 쓰는 아래 표: 칸이 보이는 판정(제목 옆 배지) · 결정 기한은 빼고, 총변경비용은 범위만 '금액 범위'로
 * (금액은 칸에) — 글은 revisionFacts 그대로, 정보는 줄이지 않는다.
 */
export function restFacts(facts: readonly Fact[]): Fact[] {
  return facts.flatMap((fact): Fact[] => {
    if (fact.id === 'verdict' || fact.id === 'deadline') return []
    if (fact.id !== 'total') return [fact]
    return fact.range ? [{ id: 'range', label: '금액 범위', value: fact.range }] : []
  })
}

/**
 * 지금 화면의 분석 = 그 개정의 분석인가. 분석 ID는 계산을 바꾸는 입력만의 해시라(변경 사유·제목 제외),
 * 사유·제목까지 같아야 같은 기록으로 본다(사유만 바꿔도 새 개정으로 남길 수 있게).
 */
export function sameAsRecorded(
  latest: RevisionSummary | null,
  result: AnalysisResult,
  recorded: RecordedChange = {},
): boolean {
  const change = result.request.change
  return (
    latest !== null &&
    latest.analysis_id === result.analysis_id &&
    latest.title === change.title &&
    (latest.intent ?? null) === (change.intent ?? null) &&
    // 1.23.0 설계 승인 상태·적용 범위도 분석 ID에 다 들어가지 않아 함께 본다(바꾸면 새 개정으로 남길 수 있게)
    (recorded.design_status ?? 'unknown') === (change.design_status ?? 'unknown') &&
    effectivityKey(recorded.effectivity) === effectivityKey(change.effectivity) &&
    // 1.28.0 변경 원인도 함께 본다(1.29.0부터 선주 요청만 분석 ID에 들어가고 나머지 원인은 안 들어감)
    (recorded.cause ?? null) === (change.cause ?? null)
  )
}

/** 검토 요청 확인 창이 고정하는 '보여 준 분석'의 열쇠: 기록 비교(sameAsRecorded)와 같은 항목. */
export function reviewKey(result: AnalysisResult): string {
  const change = result.request.change
  return [
    change.ecn_id,
    result.analysis_id,
    change.title,
    change.intent ?? '',
    change.design_status ?? 'unknown',
    effectivityKey(change.effectivity),
    change.cause ?? '',
  ].join('|')
}

/**
 * 확인 창을 연 뒤 화면의 분석이나 결재 상태 판이 바뀌었는가. 바뀌었으면 확인을 막고 다시 열게 한다
 * (그사이 다른 사람이 연 검토를 새 기록으로 끝내거나, 보여 준 것과 다른 분석을 올리지 않게).
 */
export function reviewStale(opened: { key: string; version: number }, now: { key: string; version: number }): boolean {
  return opened.key !== now.key || opened.version !== now.version
}

/** 최신 개정 요청의 설계 승인 상태·적용 범위(계약 1.23.0)·변경 원인(1.28.0) — EcnDetail.latest_*, 옛 서버면 비어 미입력. */
export interface RecordedChange {
  design_status?: string | null
  effectivity?: { effective_on?: string | null; note?: string | null } | null
  cause?: string | null
}

/** 적용 범위 비교·저장 재시도 키용 정규형(없음·빈 값은 같게). */
export function effectivityKey(effectivity: { effective_on?: string | null; note?: string | null } | null | undefined): string {
  return `${effectivity?.effective_on ?? ''}|${effectivity?.note ?? ''}`
}
