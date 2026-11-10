// 기록·승인 흐름 표시(docs/records.md, DESIGN.md 6·13절): 상태 이름·색, 지금 할 수 있는 행동과 못 하는 이유.
// 막는 것은 서버(ripple/records/flow.py)이고, 화면은 같은 규칙으로 단추를 고르고 이유를 먼저 알려 준다.
// 기록한 개정의 요약·비교는 lib/revisions(쓰는 곳이 그 모듈에서 바로 가져온다).
import type {
  ApprovalPlan,
  AuditEntry,
  EcnAction,
  EcnDetail,
  EcnListItem,
  EcnState,
  EcnStatus,
  Me,
} from '@/api/client'
import { can } from './account'
import { STEP_LABEL, currentStep, decideAs, lineText } from './approval'
import { NOTIFY_TARGETS } from './assistant'
import { daysLeft } from './ecnList'
import { noticeNote } from './notices'

export const STATE_LABEL: Record<EcnState, string> = {
  requested: '요청',
  analyzed: '분석',
  in_review: '검토',
  approved: '승인',
  rejected: '반려',
  on_hold: '보류',
  in_progress: '실행',
  closed: '종료',
}

/** 상태 칩 색(심각도 색과 같은 토큰): 결정을 기다림 = primary, 승인 = success, 반려 = danger, 보류 = warning. */
export type StateTone = 'muted' | 'primary' | 'success' | 'warning' | 'danger'
export const STATE_TONE: Record<EcnState, StateTone> = {
  requested: 'muted',
  analyzed: 'muted',
  in_review: 'primary',
  approved: 'success',
  rejected: 'danger',
  on_hold: 'warning',
  in_progress: 'primary',
  closed: 'muted',
}

export const ACTION_LABEL: Record<EcnAction, string> = {
  record: '기록만 남기기',
  request_review: '검토 요청',
  withdraw: '검토 취소',
  approve: '승인',
  reject: '반려',
  hold: '보류',
  start: '실행 시작',
  close: '종료',
  notice: '통보 기록',
  settle: '담당자 처리',
}

/** 감사 줄 한 마디(이력 탭). */
export const ENTRY_LABEL: Record<EcnAction, string> = {
  record: '기록',
  request_review: '검토 요청',
  withdraw: '검토 취소',
  approve: '승인',
  reject: '반려',
  hold: '보류',
  start: '실행 시작',
  close: '종료',
  notice: '통보 기록',
  settle: '담당자 처리(무비용)',
}

export interface ActionView {
  action: EcnAction
  /** false면 단추를 흐리게 두고 reason을 한 줄로 보인다. */
  enabled: boolean
  reason: string | null
  /** 대화상자를 거친다(결정은 사유·확인 목록, 검토 요청은 확인). */
  dialog: boolean
  /** 검토 요청이 먼저 지금 화면의 분석을 새 개정으로 기록하는가(확인 창에 알린다). */
  records?: boolean
  /** 결정을 팀장이 다른 단계(파트장·본부장) 대신 하는가(전결 — 단추에 표시). */
  proxy?: boolean
}

export interface FlowInput {
  me: Me
  /** 기록이 없으면 null(요청 상태). */
  status: EcnStatus | null
  /** 화면 결과가 지금 초안과 같고 계산이 끝났는가(이전 결과·계산 중이면 기록 못 함). */
  resultReady: boolean
  /** 지금 화면의 분석 ID = 최신 개정의 분석 ID. */
  shownMatches: boolean
  /** 최신 개정의 지도 = 지금 지도. */
  sameMap: boolean
  /** 최신 개정의 계산 판 = 지금 서버 판(EcnDetail.same_version). 다르면 검토 요청·승인 불가, 반려·보류는 됨. */
  sameVersion: boolean
  /** 로그인 모드(개발 모드면 자기 결정·개발 승인 실행이 됨). */
  loginMode: boolean
  /** 최신 개정의 결재 계획(EcnDetail.approval_plan, 서버 계산) — 무비용이면 담당자 처리 단추. */
  plan?: ApprovalPlan | null
}

const LOCKED: readonly EcnState[] = ['in_progress', 'closed']

export const REASONS = {
  locked: '실행·종료된 설계변경 · 새 개정 기록 불가',
  otherMap: '지도 바뀜 · 지금 지도로 다시 분석해 새 개정 기록 필요',
  otherVersion: '계산 판 바뀜 · 지금 판으로 다시 기록 후 검토 요청',
  selfDecision: '내가 요청한 검토 · 결재선의 다른 사람이 결정',
  devApproval: '개발 모드 승인 · 업무 계정으로 다시 검토·승인 필요',
  notReady: '계산이 끝난 결과만 기록 가능',
  waiting: '계산이 끝난 뒤 결정 가능',
  notShown: '화면의 분석이 이 개정과 다름 · 기록된 분석을 열어 확인 후 결정',
  // 반려된 개정과 같은 분석: 같은 기록은 새 개정이 되지 않고(서버 created=false) 반려 → 검토 요청 전이는 없어 단추가 없다
  // '사유'는 화면 이름인 변경 원인으로 적는다(제목·설계 승인·적용 시작일을 바꿔도 새 개정 — revisions.sameAsRecorded)
  rejectedSame:
    '반려된 개정과 같은 분석 · 그대로 다시 올리기 불가 — 변경 원인·조건을 바꿔 새 개정으로 기록 후 다시 검토 요청',
} as const

/** 결정을 기다리는 설계변경(검토·보류): 추가손실 0 마감일이 급한 것부터, 같으면 먼저 요청한 것부터. */
export function pendingDecisions(items: readonly EcnListItem[]): EcnListItem[] {
  return items
    .filter((item) => item.status.state === 'in_review' || item.status.state === 'on_hold')
    .sort(
      (a, b) =>
        daysLeft(a.latest.deadline, a.latest.as_of) - daysLeft(b.latest.deadline, b.latest.as_of) ||
        (a.status.review?.requested_at ?? '').localeCompare(b.status.review?.requested_at ?? '') ||
        a.status.ecn_id.localeCompare(b.status.ecn_id),
    )
}

/**
 * 검토 요청 단추(누르면 확인 창 → 필요하면 기록까지 한 번에). 지금 화면의 분석이 최신 개정과 다르거나
 * 지도·계산 판이 바뀌었으면 먼저 새 개정으로 기록한다(records). 새 개정은 늘 '분석' 상태가 되므로 반려·승인 뒤에도
 * 고친 분석으로 다시 올릴 수 있다. 검토·보류 중에는 진행 중 검토를 조용히 끝내지 않게 넣지 않는다('기록만 남기기'로).
 */
function reviewView(input: FlowInput): ActionView | null {
  const { status, resultReady, shownMatches, sameMap, sameVersion, loginMode } = input
  const state = status?.state ?? 'requested'
  const needsRecord = status === null || !shownMatches || !sameMap || !sameVersion
  const reopen = state === 'approved' && status?.approval_dev === true && loginMode
  const fresh = state === 'requested' || state === 'analyzed' || reopen
  if (!fresh && !(needsRecord && (state === 'rejected' || state === 'approved'))) return null
  const reason = needsRecord && !resultReady ? REASONS.notReady : null
  return { action: 'request_review', enabled: reason === null, reason, dialog: true, records: needsRecord }
}

const DECIDING: readonly EcnState[] = ['in_review', 'on_hold']
const DECIDED: readonly EcnState[] = ['approved', 'in_progress']

/**
 * 상세 머리 분석 조건(확정일·설계 승인·적용 시작일·변경 원인)과 '확정일을 결정 기한으로' 단추의 잠금(DESIGN.md 6절).
 * 결재 중(검토·보류)이거나 결정된(승인·실행) 건은 최신 개정을 기록한 사람만 조건을 바꾼다 — 결재자가 결재 중인 조건을 바꿔
 * 다른 분석을 보지 않게(기록한 담당자는 고쳐 새 개정으로 다시 올릴 수 있음). 종료된 건은 모두 잠근다. 잠그지 않으면 null,
 * 잠그면 칸 아래 한 줄.
 */
export function conditionLock(detail: Pick<EcnDetail, 'status' | 'revisions'> | null | undefined, me: Me): string | null {
  const status = detail?.status
  if (!status) return null
  if (status.state === 'closed') return '종료된 설계변경 · 조건 수정 불가'
  const deciding = DECIDING.includes(status.state)
  if (!deciding && !DECIDED.includes(status.state)) return null
  const latest = detail.revisions.find((revision) => revision.revision === status.revision)
  if (latest?.recorded_by.login_id === me.login_id) return null
  return `${deciding ? '결재 중' : '결정된 설계변경'} · 조건은 기록한 담당자만 수정`
}

/** 담당자 '내 건' 줄의 다음에 할 일 한 마디(상태별, 줄 마우스 올림). */
export const MY_NEXT: Partial<Record<EcnState, string>> = {
  rejected: '반려 — 수정 후 다시 올리기',
  on_hold: '보류 — 결재선 결정 대기',
  approved: '승인 — 실행 시작 가능',
  in_progress: '실행 중 — 끝나면 종료',
  in_review: '검토 중',
  analyzed: '기록만 — 검토 요청 전',
}

/** 지금 상태·역할에서 보일 행동(순서 = 단추 순서). 권한이 없는 행동은 아예 넣지 않는다. */
export function availableActions(input: FlowInput): ActionView[] {
  const { me, status, resultReady, shownMatches, sameMap, sameVersion, loginMode } = input
  const out: ActionView[] = []
  const recorder = can(me, 'record')
  const approver = can(me, 'approve')
  const state = status?.state ?? 'requested'
  const view = (action: EcnAction, reason: string | null, dialog = false): ActionView => ({
    action,
    enabled: reason === null,
    reason,
    dialog,
  })
  if (recorder && !(status && shownMatches)) {
    const reason = status && LOCKED.includes(state) ? REASONS.locked : !resultReady ? REASONS.notReady : null
    out.push(view('record', reason))
  }
  const review = recorder ? reviewView(input) : null
  if (review) out.push(review)
  if (!status) return out
  const requester = status.review?.requested_by.login_id ?? null
  const mine = loginMode && requester === me.login_id
  if (state === 'in_review' && (requester === me.login_id || me.role === 'admin')) {
    out.push(view('withdraw', null))
  }
  const settle = settleView(input)
  if (recorder && settle) out.push(settle)
  // 결정은 지금 결재 단계의 결재자(또는 팀장 전결)만 — 다른 단계의 결재자에게는 단추가 없다(안내 한 줄)
  const decide = decideAs(me, status, loginMode)
  if (approver && decide !== null && (state === 'in_review' || state === 'on_hold')) {
    // 결정은 그 개정의 분석을 화면에서 보고 있을 때만(같은 지도·같은 계산 판에서). 지도나 계산 판이 바뀐 개정은
    // 지금 화면에서 맞춰 볼 수 없어 반려·보류만 받는다(기록 내용은 검토서로)
    const comparable = sameMap && sameVersion
    const unseen = !resultReady ? REASONS.waiting : comparable && !shownMatches ? REASONS.notShown : null
    const approveBlock = !sameMap ? REASONS.otherMap : !sameVersion ? REASONS.otherVersion : unseen
    const proxy = decide === 'proxy'
    out.push({ ...view('approve', mine ? REASONS.selfDecision : approveBlock, true), proxy })
    out.push({ ...view('reject', mine ? REASONS.selfDecision : unseen, true), proxy })
    if (state === 'in_review') out.push({ ...view('hold', mine ? REASONS.selfDecision : unseen, true), proxy })
  }
  if (recorder && state === 'approved') {
    out.push(view('start', status.approval_dev && loginMode ? REASONS.devApproval : null))
  }
  if (recorder && state === 'in_progress') out.push(view('close', null))
  return out
}

/** 결재 띠의 안내 한 줄(행동과 별개로 알아야 할 것). 없으면 null. */
export function flowNotice(input: FlowInput): string | null {
  const { status, shownMatches, sameMap, sameVersion, me, loginMode } = input
  if (!status) return null
  if (!sameVersion) return versionNotice(status)
  if (!shownMatches) return `지금 화면의 분석은 마지막 기록(개정 ${status.revision})과 다름`
  if (!sameMap && ['approved', 'in_progress', 'closed'].includes(status.state)) {
    return '승인한 기록은 지금과 다른 지도 기준(실행은 가능)'
  }
  if (!sameMap) return '마지막 기록은 지금과 다른 지도로 계산'
  if ((status.state === 'in_review' || status.state === 'on_hold') && decideAs(me, status, loginMode) === null) {
    return waitingFor(status)
  }
  // 반려된 개정을 같은 분석으로 다시 열면 검토 요청 단추가 없다(reviewView) — 기록할 사람에게 왜 없는지와 다시 올리는 길
  if (status.state === 'rejected' && can(me, 'record')) return REASONS.rejectedSame
  return null
}

/** 다른 사람의 결재 단계를 기다릴 때: '파트장 결재를 기다리고 있어요(1/3단계)'. */
function waitingFor(status: EcnStatus): string {
  const step = currentStep(status)
  const review = status.review
  if (!step || !review) return '결재 대기 중'
  return `${STEP_LABEL[step]} 결재 대기(${review.step}/${review.steps.length}단계)`
}

/**
 * 무비용 담당자 처리 단추: 기록한 개정이 무비용(서버 결재 계획)이고 분석 상태이며 화면이 그 개정일 때만. 지도·계산 판이
 * 바뀐 개정은 흐린 단추 + 이유(검토 요청과 같은 규칙). 막는 것은 서버다.
 */
function settleView(input: FlowInput): ActionView | null {
  const { status, plan, shownMatches, sameMap, sameVersion, resultReady } = input
  if (!status || status.state !== 'analyzed' || !plan?.no_cost || !shownMatches) return null
  const reason = !sameMap ? REASONS.otherMap : !sameVersion ? REASONS.otherVersion : !resultReady ? REASONS.notReady : null
  return { action: 'settle', enabled: reason === null, reason, dialog: true }
}

/** 이전 계산 판으로 기록한 개정의 안내: 지금 화면의 분석과 맞춰 볼 수 없어 기록 내용은 검토서로 본다. */
function versionNotice(status: EcnStatus): string {
  if (status.state === 'in_review' || status.state === 'on_hold') {
    return (
      '이 개정은 이전 계산 판으로 기록 · ' +
      '검토서로 확인해 반려·보류 가능 · 승인은 지금 판으로 다시 기록해 검토 요청 후'
    )
  }
  if (['approved', 'in_progress', 'closed'].includes(status.state)) {
    return '승인한 기록은 이전 계산 판 기준(기록 내용은 검토서에서)'
  }
  return `마지막 기록(개정 ${status.revision})은 이전 계산 판으로 계산 · 검토 요청 시 지금 판으로 다시 기록해 올림`
}

/** 결정 대화상자의 필수 입력: 반려·보류는 사유, 승인은 확인 목록이 있으면 전부 체크 + 사유. */
export function decisionProblem(
  action: EcnAction,
  reason: string,
  checklistKeys: readonly string[],
  acknowledged: ReadonlySet<string>,
): string | null {
  const text = reason.trim()
  if ((action === 'approve' || action === 'settle') && checklistKeys.length > 0) {
    if (checklistKeys.some((key) => !acknowledged.has(key))) return '확인 필요 항목 모두 확인 체크 필요'
    if (!text) return '확인 필요 항목이 남은 채 승인하는 사유 입력 필요'
  }
  if ((action === 'reject' || action === 'hold') && !text) return '사유 입력 필요'
  if (text.length > 500) return '사유는 500자 이내'
  return null
}

/** 이력 탭의 세부 한 줄들(사유·확인한 항목 수·대체·다른 지도·이전 계산 판·개발 모드 자기 결정). */
export function entryNotes(entry: AuditEntry): string[] {
  const d = entry.detail
  const notes: string[] = []
  if (d.reason) notes.push(`사유: ${d.reason}`)
  if (d.acknowledged && d.acknowledged.length > 0) notes.push(`확인 필요 ${d.acknowledged.length}개를 확인하고 승인`)
  if (d.superseded_review_seq) notes.push('진행 중이던 검토는 새 개정으로 끝남')
  if (d.other_map) notes.push('승인한 기록과 다른 지도에서 실행 시작')
  if (d.other_version) notes.push('이전 계산 판으로 기록한 개정을 결정(현재 판으로 재계산·대조하지 않음)')
  if (d.self_decision) notes.push('개발 모드에서 요청자가 직접 결정(업무 승인 아님)')
  if (d.steps && d.steps.length > 0) notes.push(`결재선 ${lineText(d.steps)}`)
  if (d.step) notes.push(`${STEP_LABEL[d.step]} 단계${d.proxy ? ' · 팀장 전결' : ''}`)
  if (d.no_cost) notes.push('비용이 도면 개정뿐이라 결재 없이 담당자 처리')
  if (d.notice) notes.push(noticeNote(d.notice, NOTIFY_TARGETS[d.notice.target]))
  if (entry.actor.dev) notes.push('개발 모드 기록')
  return notes
}
