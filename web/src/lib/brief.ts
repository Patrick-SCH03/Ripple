// 결정 도우미 카드 표시 계산(DESIGN.md 13절, docs/records.md(기록·결재) 13절). 문장·숫자는 서버가 만든 그대로 쓰고,
// 여기서는 그릴지·이름표·칩 문구·과거 사례 한 줄(예측 → 실적 차이)만 정한다(brief.test.ts).
import type {
  AnalysisResult,
  BriefCheck,
  BriefLine,
  DecisionBrief,
  EcnDetail,
  Me,
  PastCase,
  PastCases,
  RevisionSummary,
} from '@/api/client'
import { can } from './account'
import { REQUEST_ALT, shortName } from './alternatives'
import { lossText } from './deadline'
import { addDays, daysBetween, formatDay } from './format'
import { formatMoney } from './money'
import { URGENT_DAYS } from './summary'

export const LINE_LABEL: Record<BriefLine['kind'], string> = {
  change: '바뀌는 것',
  loss: '결정 지연 시',
  advice: '권고',
}

export const DECISION_LABEL: Record<PastCase['decision'], string> = { approve: '승인', reject: '반려', hold: '보류' }

/** 머리 칩: 확인할 것을 AI가 골랐는가(세 줄·숫자는 어느 쪽이든 서버 규칙). */
export function pickedLabel(by: DecisionBrief['picked_by']): string {
  return by === 'ai' ? '확인 항목 AI 선택' : '기본 순서'
}

export interface BriefTarget {
  ecnId: string
  /** 진행 중 검토 개정의 기록 ID(받은 도우미가 이 기록의 것일 때만 그린다). */
  recordId: string
}

/** 도우미를 그릴 대상: 결재 권한(팀장)이고 진행 중 검토(검토·보류)가 있을 때 그 개정. 아니면 null(담당자·체험은 없음). */
export function briefTarget(me: Me | null | undefined, detail: EcnDetail | null | undefined): BriefTarget | null {
  if (!can(me, 'approve') || !detail) return null
  const { status } = detail
  const review = status.review
  if ((status.state !== 'in_review' && status.state !== 'on_hold') || !review) return null
  const revision = detail.revisions.find((r) => r.revision === review.revision)
  return revision ? { ecnId: status.ecn_id, recordId: revision.record_id } : null
}

/** 받은 도우미가 지금 대상의 것인가(상세를 다시 불러와 새 개정이 오면 옛 도우미를 그리지 않게). */
export function briefFor(brief: DecisionBrief, target: BriefTarget): boolean {
  return brief.ecn_id === target.ecnId && brief.record_id === target.recordId
}

/**
 * 과거 사례 절을 어떻게 그리나: 사례가 있으면 목록, 묶음을 만드는 중이면 한 줄('과거 사례 준비 중'),
 * 이 지도에 묶음이 없거나(unavailable) 0건이면 그리지 않음(null).
 */
export function casesView(cases: Pick<PastCases, 'status' | 'items'>): 'list' | 'building' | null {
  if (cases.status === 'building') return 'building'
  if (cases.status === 'unavailable' || cases.items.length === 0) return null
  return 'list'
}

/** 과거 사례 펼치기 단추: 접혀 있으면 '사례 3건 보기', 펼쳤으면 '사례 접기'. */
export function casesToggleLabel(count: number, open: boolean): string {
  return open ? '사례 접기' : `사례 ${count}건 보기`
}

/** 과거 사례 묶음이 합성인가(묶음 표시 또는 사례 하나라도 합성이면 — 늘 칩으로 알린다). */
export function syntheticCases(cases: PastCases): boolean {
  return cases.synthetic || cases.items.some((item) => item.synthetic)
}

/** 예측 → 실적(차이 %): '예측 298만원 → 실적 330만원(+11%)'. 실적이 없으면 '예측 298만원 · 실적 없음'. */
export function outcomeText(item: Pick<PastCase, 'predicted' | 'actual_krw'>): string {
  const predicted = formatMoney(item.predicted.value)
  if (item.actual_krw == null) return `예측 ${predicted} · 실적 없음`
  const actual = formatMoney(item.actual_krw)
  if (item.predicted.value <= 0) return `예측 ${predicted} → 실적 ${actual}`
  const pct = Math.round(((item.actual_krw - item.predicted.value) / item.predicted.value) * 100)
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : '±'
  return `예측 ${predicted} → 실적 ${actual}(${sign}${Math.abs(pct)}%)`
}

/** 마감과 결정 시점: '결정 기한 3일 전 결정' · '결정 기한 당일 결정' · '결정 기한 2일 뒤 결정'. 모르면 null. */
export function timingText(days: number | null | undefined): string | null {
  if (days == null) return null
  if (days > 0) return `결정 기한 ${days}일 전 결정`
  if (days === 0) return '결정 기한 당일 결정'
  return `결정 기한 ${-days}일 뒤 결정`
}

// ---------- 한눈에 보기(DESIGN.md 13절, 11-04 '글씨가 작고 많아 한눈에 안 들어옴') ----------
// 결재자가 3초 안에 볼 큰 숫자 카드 셋 · 바뀌는 것 한 줄 · 확인할 것 제목. 숫자는 기록 본문(개정 요약)과 그 개정의 분석
// 결과(화면 = 기록일 때만)에서 오고, 서버 문장에 같은 값이 있을 때만 싣는다(문장과 카드가 어긋나지 않게 — 아니면 문장으로).

/** 더 저렴한 권고 대안(서버 advice.cheaper·대안 탭 권고 카드와 같은 공식: 요청안 최적 총액 − 권고 총액). */
export interface Cheaper {
  /** 짧은 대안 이름(라벨의 괄호 앞). */
  name: string
  /** 권고 대안 총액. */
  total: number
  /** 요청안 대비 절감액(> 0). */
  saving: number
}

/** 대안 포함 결과에서 요청안보다 싼 권고. 권고가 요청안이거나 싸지 않으면 null. */
export function cheaperOf(result: Pick<AnalysisResult, 'alternatives' | 'recommendation'>): Cheaper | null {
  const rec = result.recommendation
  if (!rec || rec.alt_id === REQUEST_ALT) return null
  const chosen = result.alternatives.find((a) => a.alt_id === rec.alt_id)
  const request = result.alternatives.find((a) => a.alt_id === REQUEST_ALT)
  if (!chosen || !request) return null
  const saving = (request.best_total ?? request.total).value - rec.total.value
  return saving > 0 ? { name: shortName(chosen).trim(), total: rec.total.value, saving } : null
}

export type HeadTone = 'danger' | 'neutral' | 'success'

export interface HeadCard {
  label: string
  /** 큰 숫자(없으면 카드는 line을 본문 글로). */
  value: string | null
  /** 행동이 바뀌는 보조 한 줄(없으면 null). */
  line: string | null
  tone: HeadTone
}

export interface BriefHead {
  total: HeadCard
  deadline: HeadCard
  advice: HeadCard
}

const lineOf = (brief: Pick<DecisionBrief, 'lines'>, kind: BriefLine['kind']) => brief.lines.find((l) => l.kind === kind)

/** 늘어나는 금액 앞에 '+': '최대 '로 시작하면 '최대 +n'(작은 곡선 lib/miniCurve와 같은 모양), 아니면 '+n'. */
function plusLoss(text: string): string {
  return text.startsWith('최대 ') ? `최대 +${text.slice('최대 '.length)}` : `+${text}`
}

/**
 * 결정 기한 카드: 업무상 오늘(today)부터 센 D-n(결재함·서버 '결정 지연 시' 줄과 같은 기준) · '오늘' · '기한 지남' ·
 * '기간 안 없음'. 보조 한 줄 = 그날까지 + 다음 날 늘어나는 금액(그 개정의 곡선 — 서버 문장에 같은 금액이 있을 때만).
 */
function deadlineCard(
  deadline: RevisionSummary['deadline'],
  today: string,
  shown: Pick<AnalysisResult, 'timing'> | null,
  lossLine: string,
): HeadCard {
  const label = '결정 기한'
  const day = formatDay(deadline.last_day)
  if (deadline.kind === 'none_in_horizon') {
    return { label, value: '기간 안 없음', line: `${day}까지 추가손실 없음`, tone: 'success' }
  }
  const next = shown?.timing.curve.find((p) => p.confirm_on === addDays(deadline.last_day, 1))
  const grows = next ? lossText(next.additional_loss) : null
  const rise = grows && lossLine.includes(grows.replace(/^최대 /, '')) ? plusLoss(grows) : null
  const days = daysBetween(today, deadline.last_day) ?? 0
  if (days < 0) return { label, value: '기한 지남', line: `${day} 지남`, tone: 'danger' }
  if (days === 0) return { label, value: '오늘', line: rise ? `내일부터 ${rise}` : `${day}까지`, tone: 'danger' }
  return {
    label,
    value: `D-${days}`,
    line: rise ? `${day}까지 · 다음 날부터 ${rise}` : `${day}까지`,
    tone: days <= URGENT_DAYS ? 'danger' : 'neutral',
  }
}

/** 권고 카드: 더 저렴한 대안이면 큰 절감액 + '대안 이름 · 총액', 그 밖의 권고(보류·선상 설치·판정)는 서버 문장 그대로. */
function adviceCard(advice: BriefLine | undefined, cheaper: Cheaper | null): HeadCard {
  const text = advice?.text ?? ''
  if (advice?.template_id === 'advice.cheaper' && cheaper && text.includes(formatMoney(cheaper.saving))) {
    return {
      label: '권고 대안 절감',
      value: formatMoney(cheaper.saving),
      line: `${cheaper.name} · ${formatMoney(cheaper.total)}`,
      tone: 'success',
    }
  }
  return { label: '권고', value: null, line: text || null, tone: 'neutral' }
}

/**
 * 맨 위 큰 숫자 카드 셋: 총변경비용(개정 요약 그대로 — 범위는 펼친 문장에만) · 결정 기한 · 권고.
 * shown = 화면의 분석이 그 개정과 같을 때의 결과(아니면 null — 곡선 금액을 싣지 않음), cheaper = 대안 포함 계산의 권고.
 */
export function briefHead(
  brief: Pick<DecisionBrief, 'lines'>,
  revision: Pick<RevisionSummary, 'total' | 'deadline'>,
  today: string,
  shown: Pick<AnalysisResult, 'timing'> | null,
  cheaper: Cheaper | null,
): BriefHead {
  return {
    total: { label: '총변경비용', value: formatMoney(revision.total.value), line: null, tone: 'neutral' },
    deadline: deadlineCard(revision.deadline, today, shown, lineOf(brief, 'loss')?.text ?? ''),
    advice: adviceCard(lineOf(brief, 'advice'), cheaper),
  }
}

/** 권고 줄이 더 저렴한 대안인가(그때만 대안 포함 계산을 불러 절감액을 카드에 싣는다). */
export function wantsCheaper(brief: Pick<DecisionBrief, 'lines'>): boolean {
  return lineOf(brief, 'advice')?.template_id === 'advice.cheaper'
}

const SHOWN_BLOCKS = 3

export interface ChangeHead {
  title: string
  /** 영향 곳 수(화면 = 기록이고 서버 문장과 같을 때만). */
  impacts: number | null
  /** 영향 블록 코드(앞 SHOWN_BLOCKS개) + 나머지 수. */
  blocks: string[]
  moreBlocks: number
}

/** '바뀌는 것' 한 줄: 변경 제목 · 영향 n곳 · 블록 칩(숫자 되풀이 없이 — 금액은 카드, 범위·공수는 펼친 문장). */
export function changeHead(title: string, shown: Pick<AnalysisResult, 'impacts'> | null, changeLine: string): ChangeHead {
  if (!shown) return { title, impacts: null, blocks: [], moreBlocks: 0 }
  const count = shown.impacts.length
  const codes = [...new Set(shown.impacts.filter((i) => i.entity_type === 'block').map((i) => i.entity_id))]
    .sort()
    .map((id) => id.slice(id.lastIndexOf(':') + 1))
  return {
    title,
    impacts: changeLine.includes(`영향 ${count}곳`) ? count : null,
    blocks: codes.slice(0, SHOWN_BLOCKS),
    moreBlocks: Math.max(0, codes.length - SHOWN_BLOCKS),
  }
}

/**
 * 확인할 것 제목 한 줄: 서버 문장의 첫 조각(' · ' 앞)에서 '사전 점검 ' 머리를 빼고 ':'를 ' — '로, 괄호 속 세부를 뺀 것.
 * 글자를 새로 만들지 않고 줄이기만 한다 — 문장 전체는 펼침에 그대로.
 */
export function checkTitle(check: Pick<BriefCheck, 'text'>): string {
  let head = check.text.split(' · ')[0] ?? check.text
  if (head.startsWith('사전 점검 ')) head = head.slice('사전 점검 '.length).replace(': ', ' — ')
  let prev = ''
  while (prev !== head) {
    prev = head
    head = head.replace(/\([^()]*\)/g, '')
  }
  return head.replace(/\s{2,}/g, ' ').trim()
}