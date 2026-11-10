// 분석 요청 JSON 글 다루기(순수 함수, request.test.ts가 성질을 검사한다).
import { formatDay } from './format'

/** JSON 글을 읽어 요청 객체로. 실패하면 사람이 읽는 이유. */
export function parseRequest(text: string): { ok: true; value: unknown } | { ok: false; reason: string } {
  try {
    const value: unknown = JSON.parse(text)
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      return { ok: false, reason: 'JSON 객체가 아님' }
    }
    return { ok: true, value }
  } catch (error) {
    return { ok: false, reason: `JSON 읽기 실패: ${(error as Error).message}` }
  }
}

/** 요청 JSON 글에서 확정일만 바꾼 새 글. 읽을 수 없으면 원문 그대로. */
export function withConfirmOn(text: string, confirmOn: string | null): string {
  try {
    const body = JSON.parse(text) as Record<string, unknown>
    if (confirmOn) body.confirm_on = confirmOn
    else delete body.confirm_on
    return JSON.stringify(body, null, 2)
  } catch {
    return text
  }
}

/** 요청 JSON 글에서 발주 하나의 보류를 넣거나(days) 뺀(null) 새 글. 다른 보류는 순서 그대로 둔다. 읽을 수 없으면 원문 그대로. */
export function withHold(text: string, poId: string, days: number | null): string {
  try {
    const body = JSON.parse(text) as Record<string, unknown>
    const holds = Array.isArray(body.holds) ? body.holds.filter((hold) => !(isRecord(hold) && hold.po_id === poId)) : []
    body.holds = days === null ? holds : [...holds, { po_id: poId, hold_days: days }]
    return JSON.stringify(body, null, 2)
  } catch {
    return text
  }
}

/** 설계 승인 상태(계약 1.23.0). 화면 이름은 DESIGN_STATUS_NAMES. */
export const DESIGN_STATUSES = ['unknown', 'in_review', 'owner_pending', 'approved'] as const
export type DesignStatus = (typeof DESIGN_STATUSES)[number]
export const DESIGN_STATUS_NAMES: Record<DesignStatus, string> = {
  unknown: '미입력',
  in_review: '설계 검토 중',
  owner_pending: '선주 승인 대기',
  approved: '승인',
}

/**
 * 변경 원인(계약 1.28.0). 누가 일으킨 변경인지를 기록해 비용 부담·협력사 대금 조정의 근거로 남긴다. 1.29.0부터 선주 요청만
 * 계산에 쓴다: 늘어난 인도 지연이 인도일 조정 대상(허용 지연)이라 지체상금 대신 노출 금액으로 보인다(명세 4-6).
 * 이름은 현장 용어 확인 전 잠정 — 바꿀 때는 이 표만 고친다.
 */
export const CHANGE_CAUSES = ['owner_request', 'class_rule', 'design_error', 'production', 'equipment'] as const
export type ChangeCause = (typeof CHANGE_CAUSES)[number]
export const CHANGE_CAUSE_NAMES: Record<ChangeCause, string> = {
  owner_request: '선주 요청',
  class_rule: '선급·규정',
  design_error: '설계 오류·간섭',
  production: '현장 오작·변형',
  equipment: '기자재 사양',
}

/** 화면 이름(없거나 모르는 값이면 '미입력'). */
export function causeName(cause: unknown): string {
  return (CHANGE_CAUSES as readonly unknown[]).includes(cause) ? CHANGE_CAUSE_NAMES[cause as ChangeCause] : '미입력'
}

/** 요청 JSON 글의 변경(change)만 고친 새 글. 읽을 수 없으면 원문 그대로. */
function withChange(text: string, edit: (change: Record<string, unknown>) => void): string {
  try {
    const body = JSON.parse(text) as Record<string, unknown>
    const change = isRecord(body.change) ? { ...body.change } : null
    if (!change) return text
    edit(change)
    body.change = change
    return JSON.stringify(body, null, 2)
  } catch {
    return text
  }
}

/** 설계 승인 상태를 바꾼 새 글(미입력이면 필드를 뺀다 — 서버 기본값과 같음). */
export function withDesignStatus(text: string, status: DesignStatus): string {
  return withChange(text, (change) => {
    if (status === 'unknown') delete change.design_status
    else change.design_status = status
  })
}

/** 변경 원인을 바꾼 새 글(미입력이면 필드를 뺀다 — 서버 기본값과 같음). */
export function withCause(text: string, cause: ChangeCause | null): string {
  return withChange(text, (change) => {
    if (cause === null) delete change.cause
    else change.cause = cause
  })
}

/** 후행 설치(계약 1.29.0, 명세 6-3)를 켜거나 끈 새 글. 끄면 키를 지워 이 필드가 없던 요청과 같게 둔다. */
export function withOutfitOnBoard(text: string, on: boolean): string {
  try {
    const body = JSON.parse(text) as Record<string, unknown>
    if (on) body.outfit_on_board = true
    else delete body.outfit_on_board
    return JSON.stringify(body, null, 2)
  } catch {
    return text
  }
}

/** 적용 시작일을 바꾼 새 글(정보, 계산에 안 씀). 메모는 그대로 두고 둘 다 없으면 effectivity를 뺀다. */
export function withEffectiveOn(text: string, effectiveOn: string | null): string {
  return withChange(text, (change) => {
    const current = isRecord(change.effectivity) ? { ...change.effectivity } : {}
    if (effectiveOn) current.effective_on = effectiveOn
    else delete current.effective_on
    if (Object.keys(current).length === 0 || Object.values(current).every((v) => v == null)) delete change.effectivity
    else change.effectivity = current
  })
}

/** 화면 머리·위 막대에 쓰는 요청 값. 없거나 형식이 다르면 비운다. */
export interface RequestContext {
  ecnId: string | null
  title: string | null
  shipIds: string[]
  asOf: string | null
  confirmOn: string | null
  /** 탐색 기간(일). 비서 차례도 같은 기간으로 분석한다. */
  horizonDays: number | null
  /** 1.23.0 설계 승인 상태(없으면 미입력)·적용 시작일(정보). */
  designStatus?: DesignStatus
  effectiveOn?: string | null
  /** 1.28.0 변경 원인(없으면 미입력 null). */
  cause?: ChangeCause | null
}

/**
 * 분석 조건 한 줄(휴대폰 머리의 접힌 조건 칸): '확정일 10월 20일(화) · 설계 승인 미입력 · 변경 원인 선주 요청'.
 * 확정일이 없으면 기준일, 적용 시작일은 넣었을 때만.
 */
export function conditionSummary(context: RequestContext): string {
  const confirmOn = context.confirmOn ?? context.asOf
  return [
    confirmOn && `확정일 ${formatDay(confirmOn)}`,
    `설계 승인 ${DESIGN_STATUS_NAMES[context.designStatus ?? 'unknown']}`,
    context.effectiveOn && `적용 시작 ${formatDay(context.effectiveOn)}`,
    `변경 원인 ${causeName(context.cause)}`,
  ]
    .filter(Boolean)
    .join(' · ')
}

const text = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null)

export function contextOf(request: unknown): RequestContext {
  const body = isRecord(request) ? request : {}
  const change = isRecord(body.change) ? body.change : {}
  const ships = Array.isArray(change.ship_ids) ? change.ship_ids.filter((id): id is string => typeof id === 'string') : []
  return {
    ecnId: text(change.ecn_id),
    title: text(change.title),
    shipIds: ships,
    asOf: text(body.as_of),
    confirmOn: text(body.confirm_on),
    horizonDays: typeof body.horizon_days === 'number' && body.horizon_days > 0 ? body.horizon_days : null,
    designStatus: (DESIGN_STATUSES as readonly unknown[]).includes(change.design_status)
      ? (change.design_status as DesignStatus)
      : 'unknown',
    effectiveOn: isRecord(change.effectivity) ? text(change.effectivity.effective_on) : null,
    cause: (CHANGE_CAUSES as readonly unknown[]).includes(change.cause) ? (change.cause as ChangeCause) : null,
  }
}

/** 키 순서·공백과 상관없이 같은 요청인지(초안과 표시 중인 결과의 요청을 비교한다). */
export function sameRequest(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b)
}

/** 표시 중인 결과와 초안의 관계.
 * none: 결과 없음 · current: 결과 = 초안 · running: 다시 계산하는 중 · failed: 마지막 요청이 거절됨 ·
 * edited: 초안을 고쳤지만 아직 계산하지 않음. current가 아니면 화면이 "이전 결과"임을 알린다.
 */
export type ResultState = 'none' | 'current' | 'running' | 'failed' | 'edited'

/** 결과 상태는 마지막 요청의 오류(failed)와 초안 비교로만 정한다. */
export function resultState(
  shown: { body: unknown } | null,
  busy: boolean,
  failed: boolean,
  parsed: ReturnType<typeof parseRequest>,
): ResultState {
  if (!shown) return 'none'
  if (busy) return 'running'
  if (failed) return 'failed'
  if (!parsed.ok || !sameRequest(parsed.value, shown.body)) return 'edited'
  return 'current'
}

/**
 * 비서가 변경 사유를 기록한 요청을 상세(초안·결과)에 반영할까.
 * 분석 ID는 계산을 바꾸는 필드만 보므로(사유·ECN 번호·제목은 빠짐) 같은 계산의 다른 요청과 가려야 한다:
 * 상세가 사유를 기록하기 전의 바로 그 요청(basis)을 보이고, 사용자가 초안을 고치지 않았을 때만 반영한다.
 */
export function reflectsRecord(
  shown: { result: { analysis_id: string }; body: unknown } | null,
  draft: string,
  basis: unknown,
  analysisId: string,
): boolean {
  if (!shown || shown.result.analysis_id !== analysisId || !sameRequest(shown.body, basis)) return false
  const parsed = parseRequest(draft)
  return parsed.ok && sameRequest(parsed.value, shown.body)
}

function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    isRecord(item) ? Object.fromEntries(Object.entries(item).sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0))) : item,
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
