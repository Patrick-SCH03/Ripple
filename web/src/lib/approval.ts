// 결재선 표시(docs/records.md(기록·결재) 14절): 파트장 → 팀장 → 본부장, 팀장 전결, 무비용 담당자 처리, 결재 올릴 기한.
// 막는 것은 서버(ripple/records/flow.py)이고 결재 계획(approval_plan)은 서버가 계산한 값 그대로 쓴다. 여기서는 역할 →
// 단계 대조와 문구만 만든다(서버 ripple/records/approval.py STEP_OF_ROLE·PROXY_OF_ROLE와 같은 표).
import type {
  AnalysisResult,
  ApprovalPlan,
  ApprovalStep,
  AuditEntry,
  EcnDetail,
  EcnStatus,
  Me,
  Role,
  StepSign,
} from '@/api/client'
import { formatDay } from './format'
import { formatMoney } from './money'
import { sameAsRecorded } from './revisions'

export const STEP_LABEL: Record<ApprovalStep, string> = { part_lead: '파트장', team_lead: '팀장', executive: '본부장' }

/** 역할 → 자기 단계(팀장 = 팀장 단계). 결재선에 없는 역할은 null. */
const STEP_OF_ROLE: Partial<Record<Role, ApprovalStep>> = {
  part_lead: 'part_lead',
  admin: 'team_lead',
  executive: 'executive',
}

/** 팀장이 대신 결정할 수 있는 단계(전결). */
const PROXY_STEPS: readonly ApprovalStep[] = ['part_lead', 'executive']

function stepOfRole(role: Role): ApprovalStep | null {
  return STEP_OF_ROLE[role] ?? null
}

/** 진행 중 검토의 지금 단계(없으면 null). */
export function currentStep(status: EcnStatus | null | undefined): ApprovalStep | null {
  const review = status?.review
  if (!review) return null
  return review.steps[review.step - 1] ?? null
}

/**
 * 이 사람이 지금 단계를 결정하는 방식: 자기 단계(own) · 팀장 전결(proxy) · 못 함(null).
 * 개발 모드(로그인 끔, loginMode = false)는 서버처럼 모든 단계를 자기 단계로 본다 — '(전결)' 표시가 붙지 않는다.
 */
export function decideAs(me: Me, status: EcnStatus | null | undefined, loginMode: boolean): 'own' | 'proxy' | null {
  const step = currentStep(status)
  if (!step || !me.permissions.includes('approve')) return null
  if (!loginMode || stepOfRole(me.role) === step) return 'own'
  if (me.role === 'admin' && PROXY_STEPS.includes(step)) return 'proxy'
  return null
}

/** 결재선 한 줄: '파트장 → 팀장 → 본부장'. */
export function lineText(steps: readonly ApprovalStep[]): string {
  return steps.map((step) => STEP_LABEL[step]).join(' → ')
}

/**
 * 검토 요청 창의 결재선 한 줄(서버 결재 계획의 결재선·단계당 근무일 그대로): '파트장 → 팀장 → 본부장 · 단계마다
 * 1~2근무일'. 결재선을 싣지 않은 계획이면 null(화면이 결재선을 짐작하지 않는다).
 */
export function lineSummary(plan: ApprovalPlan | null | undefined): string | null {
  const line = plan?.line ?? []
  if (!plan || line.length === 0) return null
  return `${lineText(line)} · 단계마다 ${plan.days_per_step_low}~${plan.days_per_step}근무일`
}

/** 결재선 단계 이름을 가운뎃점으로: '파트장·팀장·본부장'(결재선이 없으면 null). */
export function lineNames(plan: ApprovalPlan | null | undefined): string | null {
  const line = plan?.line ?? []
  return line.length > 0 ? line.map((step) => STEP_LABEL[step]).join('·') : null
}

export interface LineNode {
  step: ApprovalStep
  label: string
  /** done = 승인함 · now = 지금 단계 · next = 아직. */
  state: 'done' | 'now' | 'next'
  /** 승인한 사람(전결이면 '(전결)'). */
  by: string | null
}

/** 결재선 진행(결재함·결재 띠): 앞 단계 승인(전결 표시)·지금 단계·남은 단계. */
export function lineNodes(steps: readonly ApprovalStep[], current: number, signed: readonly StepSign[]): LineNode[] {
  return steps.map((step, index) => {
    const sign = index < current - 1 ? signed.find((s) => s.step === step) : undefined
    const state = index < current - 1 ? 'done' : index === current - 1 ? 'now' : 'next'
    // 단계 이름이 역할을 말하므로 사람은 이름만(전결이면 그 사실)
    const by = sign ? `${sign.actor.name}${sign.proxy ? ' 전결' : ''}` : null
    return { step, label: STEP_LABEL[step], state, by }
  })
}

/** 상세의 감사 줄에서 그 검토의 앞 단계 승인(결재함의 signed와 같은 값 — 승인 뒤에도 검토가 이어진 줄). */
export function signsOf(audit: readonly AuditEntry[], reviewSeq: number): StepSign[] {
  return audit
    .filter(
      (e) =>
        e.action === 'approve' &&
        e.detail.review_seq === reviewSeq &&
        (e.detail.to_state === 'in_review' || e.detail.to_state === 'on_hold'),
    )
    .map((e) => ({ step: e.detail.step ?? 'team_lead', actor: e.actor, at: e.at, proxy: e.detail.proxy }))
}

/** 결재 소요(서버 계획의 단계 수·단계당 근무일): '결재 3단계 · 근무일 3~6일'. */
function spanText(plan: ApprovalPlan): string {
  const n = plan.steps.length
  return `결재 ${n}단계 · 근무일 ${n * plan.days_per_step_low}~${n * plan.days_per_step}일`
}

export interface SubmitLine {
  /** 한 줄 글. */
  text: string
  /**
   * late = 단계당 1일로도 지남(위험 색), caution = 대표(단계당 2일) 기한은 지났지만 단계당 1일이면 아직 남음(주의 색),
   * none = 결재 없음(무비용), ok = 그 밖.
   */
  tone: 'ok' | 'caution' | 'late' | 'none'
}

/**
 * 결정 기한 카드 아래·결재함 줄의 '결재 올릴 기한' 한 줄(서버의 결재 계획 그대로 — 이 글을 만드는 곳은 여기 하나).
 * 무비용이면 '담당자 처리 — 결재 없음', 탐색 기간 안 손실이 없으면(기한 없음) 그리지 않는다(null). 검토 중이면 남은
 * 단계로 센 '남은 결재 기한'. 한 줄에 들어가게 핵심만(결재함 줄 폭 기준). 서버가 단계당 1일 기한(submit_by_low)을
 * 실으면 빠른 경우 날짜를 함께 적는다:
 * - 대표 기한 전: '결재 올릴 기한 10월 29일(목) · 단계당 1일이면 11월 3일(화) (결재 3단계 · 근무일 3~6일)'.
 * - 대표 기한은 지났고 단계당 1일 기한은 남음: '… 10월 27일(화)(단계당 2일) 지남 · 단계당 1일이면 10월 30일(금)까지'
 *   (주의 색 — 아직 기한 안에 들 길이 있다).
 * - 둘 다 지남: '… 10월 26일(월) 지남 · 결정 가능일 11월 4일(수) · 추가손실 225만원'(위험 색).
 */
export function submitLine(plan: ApprovalPlan | null | undefined, reviewing: boolean): SubmitLine | null {
  if (!plan) return null
  if (plan.steps.length === 0) {
    return plan.no_cost ? { text: '담당자 처리 — 결재 없음(비용이 도면 개정뿐 · 승인 가능)', tone: 'none' } : null
  }
  if (!plan.submit_by) return null
  const what = reviewing ? '남은 결재 기한' : '결재 올릴 기한'
  // 단계당 1일 기한: 옛 응답이면 없고, 단계당 근무일이 같으면 대표 기한과 같은 날이라 따로 적지 않는다
  const fast = plan.submit_by_low && plan.submit_by_low !== plan.submit_by ? plan.submit_by_low : null
  const low = fast ? `단계당 ${plan.days_per_step_low}일이면 ${formatDay(fast)}` : ''
  if (plan.late && fast && !plan.late_low) {
    return {
      text: `${what} ${formatDay(plan.submit_by)}(단계당 ${plan.days_per_step}일) 지남 · ${low}까지`,
      tone: 'caution',
    }
  }
  if (plan.late && plan.earliest) {
    const loss = plan.earliest_loss != null && plan.earliest_loss > 0 ? ` · 추가손실 ${formatMoney(plan.earliest_loss)}` : ''
    return {
      text: `${what} ${formatDay(plan.submit_by)} 지남 · 결정 가능일 ${formatDay(plan.earliest)}${loss}`,
      tone: 'late',
    }
  }
  if (fast) {
    return { text: `${what} ${formatDay(plan.submit_by)} · ${low} (결재 ${plan.steps.length}단계)`, tone: 'ok' }
  }
  return { text: `${what} ${formatDay(plan.submit_by)}(${spanText(plan)})`, tone: 'ok' }
}

/**
 * 결정 대화상자의 결재선 안내 한 줄: 몇 단계의 누구 결재인지(전결이면 그 사실과 감사 기록), 승인하면 다음 단계로 넘어가는지.
 * 결정이 아니거나 진행 중 검토가 없으면 null.
 */
export function decisionNote(action: string, status: EcnStatus | null | undefined, how: 'own' | 'proxy' | null): string | null {
  const review = status?.review
  const step = currentStep(status)
  if (!review || !step || !['approve', 'reject', 'hold'].includes(action)) return null
  const where = `${review.step}/${review.steps.length}단계`
  const head =
    how === 'proxy'
      ? `${STEP_LABEL[step]} 단계(${where}) 팀장 전결 · 감사 기록에 전결·원래 단계 남음`
      : `${STEP_LABEL[step]} 결재(${where})`
  if (action !== 'approve') return head
  const next = review.steps[review.step]
  return next ? `${head} · 승인 시 ${STEP_LABEL[next]} 결재로` : `${head} · 마지막 단계 — 승인 시 실행 가능`
}

/**
 * 지금 화면의 분석에 맞는 서버 결재 계획: 고른 설계변경의 최신 개정이 화면의 분석과 같을 때만(같은 기록 대조 —
 * lib/revisions sameAsRecorded). 기록 전·다른 분석이면 null(서버가 계산하지 않은 값을 화면이 짐작하지 않는다).
 */
export function shownPlan(detail: EcnDetail | null | undefined, result: AnalysisResult | null): ApprovalPlan | null {
  if (!detail || !result || detail.status.ecn_id !== result.request.change.ecn_id) return null
  const recorded = { design_status: detail.latest_design_status, effectivity: detail.latest_effectivity, cause: detail.latest_cause }
  return sameAsRecorded(detail.revisions.at(-1) ?? null, result, recorded) ? (detail.approval_plan ?? null) : null
}

/** 할 일·검토 요청 창의 결재선 안내: 무비용이면 담당자 처리, 아니면 결재선과 소요. */
export function lineGuide(plan: ApprovalPlan | null | undefined): string | null {
  if (!plan) return null
  if (plan.no_cost && plan.steps.length === 0) {
    return '비용이 도면 개정뿐 · 판정 승인 가능 → 결재 없이 담당자 처리(기록 뒤 결재 띠의 담당자 처리)'
  }
  if (plan.steps.length === 0) return null
  return `결재선 ${lineText(plan.steps)} · ${spanText(plan)}`
}
