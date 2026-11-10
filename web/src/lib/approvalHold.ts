// 발주 보류 권고의 결재 기간 표시(현업 의견, docs/records.md(기록·결재) 14절): 실무에서 발주 보류는
// 내부 결재가 도는 동안 하고, 결재는 라인별 1~2일이 관례다. 엔진의 보류 권고(max_hold_days · hold_until)는 그대로 두고,
// 그 기간이 결재 기간보다 길면 '결재 중에는 보류 유지 가능 · 권고 기간까지 보류 시 공급사 협의'로 읽게 한다.
// 규칙(결재 단계 수·단계당 근무일·주말 제외 날짜 셈·문구)은 서버 ripple/records/approval.py 한 곳이고, 분석 응답·기록
// 조회의 결재 계획(approval_plan.holds)에 실려 온다. 화면은 그 값만 쓴다(엑셀 내보내기도 같은 값).
import type { ApprovalPlan, HoldAdvice } from '@/api/client'

type Plan = Pick<ApprovalPlan, 'holds'> | null | undefined

function windowOf(advice: Pick<HoldAdvice, 'po_id'>, plan: Plan) {
  return plan?.holds.find((hold) => hold.po_id === advice.po_id) ?? null
}

/**
 * 보류 권고 줄의 결재 기간 한 줄(명사형 조각, 서버 문구 그대로):
 * - 권고가 결재 기간보다 길면 '결재 중(약 6근무일 — 결재 3단계 × 1~2일)에는 보류 유지 가능 · 권고 22일까지 보류 시 공급사 협의 필요'
 * - 짧거나 같으면 '권고 4일은 결재 기간(…)보다 짧음 · 그 안에 결재를 마쳐야 보류로 손실을 피함'
 * - 무비용이면 '담당자 처리 — 결재 없음'
 * 결재 계획이 없으면(옛 응답) null — 화면이 짐작해 만들지 않는다.
 */
export function approvalHoldText(advice: Pick<HoldAdvice, 'po_id'>, plan: Plan): string | null {
  return windowOf(advice, plan)?.text ?? null
}

/** 요약 복사용 짧은 꼬리: '결재 중 보류 가능 · 22일까지는 공급사 협의' · '결재 기간보다 짧은 보류' · '담당자 처리 — 결재 없음'. */
export function approvalHoldShort(advice: Pick<HoldAdvice, 'po_id'>, plan: Plan): string | null {
  return windowOf(advice, plan)?.short ?? null
}
