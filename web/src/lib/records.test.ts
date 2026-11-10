import { describe, expect, it } from 'vitest'
import type { AnalysisResult, AuditEntry, EcnListItem, EcnStatus, Me, RevisionSummary } from '@/api/client'
import {
  REASONS,
  availableActions,
  conditionLock,
  decisionProblem,
  entryNotes,
  flowNotice,
  pendingDecisions,
  type FlowInput,
} from './records'
import { deadlineMark } from './ecnList'
import { assumedPlan, restFacts, reviewKey, reviewStale, revisionFacts, revisionGlance, sameAsRecorded } from './revisions'

const member: Me = {
  login_id: 'kim',
  name: '김담당',
  role: 'member',
  must_change_password: false,
  permissions: ['view', 'export', 'change_password', 'record'],
}
const admin: Me = {
  login_id: 'lead',
  name: '관리자',
  role: 'admin',
  must_change_password: false,
  permissions: ['view', 'export', 'switch_map', 'import', 'manage_accounts', 'change_password', 'record', 'approve'],
}
const demo: Me = { login_id: 'demo', name: '체험', role: 'demo', must_change_password: false, permissions: ['view', 'export'] }

function status(state: EcnStatus['state'], extra: Partial<EcnStatus> = {}): EcnStatus {
  const reviewing = state === 'in_review' || state === 'on_hold'
  const approved = state === 'approved' || state === 'in_progress' || state === 'closed'
  return {
    ecn_id: 'ECN-D-0119',
    title: '판 두께',
    state,
    version: 3,
    revision: 2,
    record_id: 'R-00000000000000aa',
    snapshot_id: 'G-0000000000000001',
    review: reviewing
      ? {
          seq: 5,
          revision: 2,
          requested_by: { login_id: 'kim', name: '김담당', role: 'member', dev: false },
          requested_at: '2026-10-09T03:00:00Z',
          steps: ['team_lead'], // 옛 판처럼 팀장 한 단계(1/1단계) — 결재선 세 단계는 아래 결재선 묶음
          step: 1,
        }
      : null,
    approved_revision: approved ? 2 : null,
    approval_dev: false,
    real: false,
    updated_at: '2026-10-09T03:00:00Z',
    ...extra,
  }
}

const base = (me: Me, s: EcnStatus | null, extra: Partial<FlowInput> = {}): FlowInput => ({
  me,
  status: s,
  resultReady: true,
  shownMatches: true,
  sameMap: true,
  sameVersion: true,
  loginMode: true,
  ...extra,
})
const names = (input: FlowInput) => availableActions(input).map((a) => `${a.action}${a.enabled ? '' : '×'}`)

describe('availableActions', () => {
  it('기록 없음: 담당자는 기록만 남기기 + 검토 요청(기록까지 한 번에), 체험은 아무것도 없음', () => {
    expect(names(base(member, null))).toEqual(['record', 'request_review'])
    expect(availableActions(base(member, null))[1]).toMatchObject({ dialog: true, records: true })
    expect(names(base(member, null, { resultReady: false }))).toEqual(['record×', 'request_review×'])
    expect(availableActions(base(member, null, { resultReady: false }))[1].reason).toBe(REASONS.notReady)
    expect(names(base(demo, null))).toEqual([])
  })

  it('분석: 화면 = 최신 기록이면 그 개정의 검토 요청만, 다르거나 지도가 바뀌었으면 기록하고 검토 요청', () => {
    expect(names(base(member, status('analyzed')))).toEqual(['request_review'])
    expect(availableActions(base(member, status('analyzed')))[0]).toMatchObject({ enabled: true, records: false })
    const differs = availableActions(base(member, status('analyzed'), { shownMatches: false }))
    expect(differs.map((a) => `${a.action}${a.enabled ? '' : '×'}`)).toEqual(['record', 'request_review'])
    expect(differs[1].records).toBe(true)
    expect(availableActions(base(member, status('analyzed'), { sameMap: false }))[0]).toMatchObject({
      action: 'request_review',
      enabled: true,
      records: true,
    })
  })

  it('반려·승인 뒤 고친 분석은 기록하고 다시 검토 요청, 같은 분석이면 검토 요청 없음', () => {
    expect(names(base(member, status('rejected')))).toEqual([])
    expect(names(base(member, status('rejected'), { shownMatches: false }))).toEqual(['record', 'request_review'])
    expect(names(base(member, status('approved'), { shownMatches: false }))).toEqual(['record', 'request_review', 'start'])
    // 검토·보류 중에는 진행 중 검토를 조용히 끝내지 않게 '기록만 남기기'만
    expect(names(base(member, status('in_review'), { shownMatches: false }))).toEqual(['record', 'withdraw'])
  })

  it('검토: 관리자는 취소·승인·반려·보류, 요청한 담당자는 취소만', () => {
    expect(names(base(admin, status('in_review')))).toEqual(['withdraw', 'approve', 'reject', 'hold'])
    expect(names(base(member, status('in_review')))).toEqual(['withdraw'])
    expect(names(base({ ...member, login_id: 'lee' }, status('in_review')))).toEqual([])
  })

  it('자기 결정: 로그인 모드에서 내가 요청한 검토는 결정 막힘, 개발 모드는 허용', () => {
    const mine = status('in_review', {
      review: {
        seq: 5,
        revision: 2,
        requested_by: { login_id: 'lead', name: '관리자', role: 'admin', dev: false },
        requested_at: '',
        steps: ['team_lead'],
        step: 1,
      },
    })
    const blocked = availableActions(base(admin, mine)).filter((a) => a.dialog)
    expect(blocked.every((a) => !a.enabled && a.reason === REASONS.selfDecision)).toBe(true)
    expect(availableActions(base(admin, mine, { loginMode: false })).filter((a) => a.dialog).every((a) => a.enabled)).toBe(
      true,
    )
  })

  it('지도가 다르면 승인만 막히고 반려는 됨, 보류 상태에서는 승인·반려만', () => {
    expect(names(base(admin, status('in_review'), { sameMap: false }))).toEqual(['withdraw', 'approve×', 'reject', 'hold'])
    expect(names(base(admin, status('on_hold')))).toEqual(['approve', 'reject'])
  })

  it('결정은 그 개정의 분석을 화면에서 볼 때만: 화면이 다르면 승인·반려·보류 막힘(이유), 계산 중이면 기다림', () => {
    const differs = availableActions(base(admin, status('in_review'), { shownMatches: false }))
    expect(differs.filter((a) => a.dialog).every((a) => !a.enabled && a.reason === REASONS.notShown)).toBe(true)
    expect(differs.find((a) => a.action === 'withdraw')?.enabled).toBe(true)
    const loading = availableActions(base(admin, status('in_review'), { resultReady: false }))
    expect(loading.filter((a) => a.dialog).every((a) => !a.enabled && a.reason === REASONS.waiting)).toBe(true)
    // 지도가 바뀐 개정은 맞춰 볼 수 없어: 승인은 지도 이유로 막히고 반려·보류는 됨(관리자도 기록 권한이라 새 개정 단추)
    expect(names(base(admin, status('in_review'), { shownMatches: false, sameMap: false }))).toEqual([
      'record',
      'withdraw',
      'approve×',
      'reject',
      'hold',
    ])
    // 실행 시작은 화면과 무관(승인한 개정을 실행, 지도가 바뀌어도 허용)
    expect(names(base(member, status('approved'), { shownMatches: false, sameMap: false }))).toEqual([
      'record',
      'request_review',
      'start',
    ])
  })

  it('계산 판이 바뀐 개정: 승인은 판 이유로 막히고 반려·보류는 화면과 맞추지 않아도 됨(검토·보류)', () => {
    const old = { shownMatches: false, sameVersion: false }
    const review = availableActions(base(admin, status('in_review'), old))
    expect(review.map((a) => `${a.action}${a.enabled ? '' : '×'}`)).toEqual(['record', 'withdraw', 'approve×', 'reject', 'hold'])
    expect(review.find((a) => a.action === 'approve')?.reason).toBe(REASONS.otherVersion)
    expect(names(base(admin, status('on_hold'), old))).toEqual(['record', 'approve×', 'reject'])
    // 지도·판 둘 다 바뀌면 지도 이유가 먼저
    expect(availableActions(base(admin, status('in_review'), { ...old, sameMap: false }))[2].reason).toBe(REASONS.otherMap)
    // 계산 중에는 반려·보류도 기다림(판이 바뀌어도 같음)
    const loading = availableActions(base(admin, status('in_review'), { ...old, resultReady: false }))
    expect(loading.filter((a) => a.action !== 'approve' && a.dialog).every((a) => a.reason === REASONS.waiting)).toBe(true)
  })

  it('계산 판이 바뀐 개정: 검토 요청은 지금 판으로 다시 기록해 올림(화면이 같아도), 실행 시작은 됨', () => {
    const analyzed = availableActions(base(member, status('analyzed'), { shownMatches: false, sameVersion: false }))
    expect(analyzed.map((a) => a.action)).toEqual(['record', 'request_review'])
    expect(analyzed[1]).toMatchObject({ enabled: true, records: true })
    expect(availableActions(base(member, status('analyzed'), { sameVersion: false }))[0]).toMatchObject({
      action: 'request_review',
      records: true,
    })
    expect(names(base(member, status('approved'), { shownMatches: false, sameVersion: false }))).toEqual([
      'record',
      'request_review',
      'start',
    ])
  })

  it('승인 → 실행 시작, 개발 모드 승인은 로그인 모드에서 실행 막히고 다시 검토 요청', () => {
    expect(names(base(member, status('approved')))).toEqual(['start'])
    expect(names(base(member, status('approved', { approval_dev: true })))).toEqual(['request_review', 'start×'])
    expect(names(base(member, status('approved', { approval_dev: true }), { loginMode: false }))).toEqual(['start'])
  })

  it('실행 → 종료, 실행·종료 중 다른 분석은 새 개정 막힘', () => {
    expect(names(base(member, status('in_progress')))).toEqual(['close'])
    expect(availableActions(base(member, status('closed'), { shownMatches: false }))[0]).toMatchObject({
      action: 'record',
      enabled: false,
      reason: REASONS.locked,
    })
  })
})

describe('상세 머리 조건 잠금(conditionLock)', () => {
  const detail = (state: EcnStatus['state'], by: string) => ({
    status: status(state),
    revisions: [
      { revision: 1, recorded_by: { login_id: 'other', name: 'other', role: 'member', dev: false } },
      { revision: 2, recorded_by: { login_id: by, name: by, role: 'member', dev: false } },
    ] as unknown as RevisionSummary[],
  })

  it('결재 중·결정된 건은 최신 개정을 기록한 사람만 바꿈, 종료는 모두 잠금, 기록 전·분석·반려는 잠그지 않음', () => {
    expect(conditionLock(detail('in_review', 'kim'), member)).toBeNull()
    expect(conditionLock(detail('in_review', 'kim'), admin)).toBe('결재 중 · 조건은 기록한 담당자만 수정')
    expect(conditionLock(detail('on_hold', 'kim'), admin)).toBe('결재 중 · 조건은 기록한 담당자만 수정')
    expect(conditionLock(detail('approved', 'kim'), admin)).toBe('결정된 설계변경 · 조건은 기록한 담당자만 수정')
    expect(conditionLock(detail('in_progress', 'lead'), admin)).toBeNull()
    expect(conditionLock(detail('closed', 'kim'), member)).toBe('종료된 설계변경 · 조건 수정 불가')
    for (const state of ['analyzed', 'rejected'] as const) expect(conditionLock(detail(state, 'kim'), admin)).toBeNull()
    expect(conditionLock(null, admin)).toBeNull()
  })
})

describe('검토 요청 확인 창 고정(reviewKey · reviewStale)', () => {
  const shown = (change: Record<string, unknown> = {}, analysis = 'A-1') =>
    ({
      analysis_id: analysis,
      request: { change: { ecn_id: 'ECN-D-0119', title: '판 두께', intent: 'strength', ...change } },
    }) as unknown as AnalysisResult
  const opened = { key: reviewKey(shown()), version: 3 }

  it('같은 분석·같은 상태 판이면 그대로 확인할 수 있음', () => {
    expect(reviewStale(opened, { key: reviewKey(shown()), version: 3 })).toBe(false)
  })

  it('연 뒤 다른 사람이 검토를 열거나 새 개정을 남기면(상태 판이 바뀜) 확인을 막음', () => {
    expect(reviewStale(opened, { key: reviewKey(shown()), version: 4 })).toBe(true)
  })

  it('연 뒤 화면의 분석이 바뀌면(다시 계산·사유·설계 승인·적용 범위·다른 ECN) 확인을 막음', () => {
    expect(reviewStale(opened, { key: reviewKey(shown({}, 'A-2')), version: 3 })).toBe(true)
    expect(reviewStale(opened, { key: reviewKey(shown({ intent: 'owner' })), version: 3 })).toBe(true)
    expect(reviewStale(opened, { key: reviewKey(shown({ design_status: 'in_review' })), version: 3 })).toBe(true)
    expect(reviewStale(opened, { key: reviewKey(shown({ effectivity: { effective_on: '2026-11-01' } })), version: 3 })).toBe(
      true,
    )
    expect(reviewStale(opened, { key: reviewKey(shown({ ecn_id: 'ECN-D-0045' })), version: 3 })).toBe(true)
  })
})

describe('sameAsRecorded · pendingDecisions', () => {
  const summary = (extra: Partial<RevisionSummary> = {}): RevisionSummary => ({
    revision: 2,
    record_id: 'R-00000000000000aa',
    analysis_id: 'A-1',
    recorded_at: '2026-10-09T03:00:00Z',
    recorded_by: { login_id: 'kim', name: '김담당', role: 'member', dev: false },
    snapshot_id: 'G-0000000000000001',
    data_mode: 'synthetic',
    title: '판 두께',
    intent: 'strength',
    verdict: 'warn',
    total: { value: 1000, low: 900, high: 1100 },
    deadline: { kind: 'by_date', last_day: '2026-10-27' },
    as_of: '2026-10-20',
    confirm_on: '2026-10-20',
    holds: [],
    alternatives: false,
    checklist: 0,
    ...extra,
  })
  const shown = (extra: { analysis_id?: string; title?: string; intent?: RevisionSummary['intent'] } = {}) =>
    ({
      analysis_id: extra.analysis_id ?? 'A-1',
      request: { change: { title: extra.title ?? '판 두께', intent: extra.intent === undefined ? 'strength' : extra.intent } },
    }) as unknown as AnalysisResult

  it('분석 ID·제목·변경 사유가 모두 같아야 같은 기록(사유만 바꿔도 새 개정을 남길 수 있게)', () => {
    expect(sameAsRecorded(summary(), shown())).toBe(true)
    expect(sameAsRecorded(null, shown())).toBe(false)
    expect(sameAsRecorded(summary(), shown({ analysis_id: 'A-2' }))).toBe(false)
    expect(sameAsRecorded(summary(), shown({ intent: 'owner_request' }))).toBe(false)
    expect(sameAsRecorded(summary(), shown({ intent: null }))).toBe(false)
    expect(sameAsRecorded(summary({ intent: null }), shown({ intent: null }))).toBe(true)
    expect(sameAsRecorded(summary(), shown({ title: '판 두께 (사유)' }))).toBe(false)
  })

  it('1.23.0 설계 승인 상태·적용 범위가 다르면 다른 기록(분석 ID가 같아도)', () => {
    const withChange = (change: Record<string, unknown>) =>
      ({
        analysis_id: 'A-1',
        request: { change: { title: '판 두께', intent: 'strength', ...change } },
      }) as unknown as AnalysisResult
    expect(sameAsRecorded(summary(), withChange({}))).toBe(true)
    expect(sameAsRecorded(summary(), withChange({ design_status: 'unknown', effectivity: null }))).toBe(true)
    expect(sameAsRecorded(summary(), withChange({ design_status: 'approved' }))).toBe(false)
    expect(sameAsRecorded(summary(), withChange({ effectivity: { effective_on: '2026-11-01' } }))).toBe(false)
    expect(
      sameAsRecorded(
        summary(),
        withChange({ design_status: 'owner_pending', effectivity: { effective_on: '2026-11-01' } }),
        { design_status: 'owner_pending', effectivity: { effective_on: '2026-11-01', note: null } },
      ),
    ).toBe(true)
    expect(sameAsRecorded(summary(), withChange({}), { design_status: 'approved' })).toBe(false)
  })

  it('1.28.0 변경 원인이 다르면 다른 기록, 없음·null은 같음, 검토 창 열쇠도 원인을 봄', () => {
    const withCause = (cause: string | null | undefined) =>
      ({
        analysis_id: 'A-1',
        request: { change: { ecn_id: 'E', title: '판 두께', intent: 'strength', cause } },
      }) as unknown as AnalysisResult
    expect(sameAsRecorded(summary(), withCause(undefined), { cause: null })).toBe(true)
    expect(sameAsRecorded(summary(), withCause('owner_request'))).toBe(false)
    expect(sameAsRecorded(summary(), withCause('owner_request'), { cause: 'owner_request' })).toBe(true)
    expect(sameAsRecorded(summary(), withCause(null), { cause: 'production' })).toBe(false)
    expect(reviewKey(withCause('owner_request'))).not.toBe(reviewKey(withCause(null)))
  })

  it('결재 대기 = 검토·보류만, 마감일 급한 것 → 먼저 요청한 것', () => {
    const item = (ecn: string, state: EcnStatus['state'], lastDay: string, at: string): EcnListItem => ({
      status: status(state, {
        ecn_id: ecn,
        review:
          state === 'in_review' || state === 'on_hold'
            ? {
                seq: 1,
                revision: 2,
                requested_by: { login_id: 'kim', name: '김담당', role: 'member', dev: false },
                requested_at: at,
                steps: ['team_lead'],
                step: 1,
              }
            : null,
      }),
      latest: summary({ deadline: { kind: 'by_date', last_day: lastDay } }),
    })
    const list = [
      item('ECN-A', 'in_review', '2026-10-30', '2026-10-09T01:00:00Z'),
      item('ECN-B', 'approved', '2026-10-21', '2026-10-09T01:00:00Z'),
      item('ECN-C', 'on_hold', '2026-10-25', '2026-10-09T02:00:00Z'),
      item('ECN-D', 'in_review', '2026-10-25', '2026-10-09T01:30:00Z'),
    ]
    expect(pendingDecisions(list).map((i) => i.status.ecn_id)).toEqual(['ECN-D', 'ECN-C', 'ECN-A'])
  })
})

describe('assumedPlan', () => {
  const of = (holds: { po_id: string; hold_days: number }[]) =>
    ({ request: { holds } }) as unknown as Pick<AnalysisResult, 'request'>
  it('보류가 없으면 null, 있으면 건수와 발주·일수', () => {
    expect(assumedPlan(of([]))).toBeNull()
    expect(
      assumedPlan(
        of([
          { po_id: 'PO-1', hold_days: 5 },
          { po_id: 'PO-2', hold_days: 3 },
        ]),
      ),
    ).toBe('발주 보류 2건(PO-1 5일·PO-2 3일)')
  })
  it('후행 설치도 가정으로 적고, 보류와 함께면 이어 적음', () => {
    const onBoard = (holds: { po_id: string; hold_days: number }[]) =>
      ({ request: { holds, outfit_on_board: true } }) as unknown as Pick<AnalysisResult, 'request'>
    expect(assumedPlan(onBoard([]))).toBe('후행 설치')
    expect(assumedPlan(onBoard([{ po_id: 'PO-1', hold_days: 5 }]))).toBe('발주 보류 1건(PO-1 5일) · 후행 설치')
  })
})

describe('flowNotice', () => {
  it('화면이 다르면 개정 번호, 승인 뒤 지도 다르면 실행 가능 안내, 담당자는 결정 대기', () => {
    expect(flowNotice(base(member, status('analyzed'), { shownMatches: false }))).toContain('개정 2')
    expect(flowNotice(base(member, status('approved'), { sameMap: false }))).toContain('실행은 가능')
    expect(flowNotice(base(member, status('in_review')))).toBe('팀장 결재 대기(1/1단계)')
    expect(flowNotice(base(admin, status('in_review')))).toBeNull()
    expect(flowNotice(base(member, null))).toBeNull()
  })

  it('계산 판이 바뀐 개정: 상태별 안내(검토·보류는 반려·보류 가능과 다시 기록, 승인 뒤는 검토서, 그 밖은 검토 요청이 다시 기록)', () => {
    const old = { shownMatches: false, sameVersion: false }
    const reviewing = flowNotice(base(admin, status('in_review'), old))
    expect(reviewing).toContain('이전 계산 판')
    expect(reviewing).toContain('반려·보류 가능')
    expect(flowNotice(base(member, status('on_hold'), old))).toContain('이 개정은 이전 계산 판')
    expect(flowNotice(base(member, status('closed'), old))).toBe('승인한 기록은 이전 계산 판 기준(기록 내용은 검토서에서)')
    expect(flowNotice(base(member, status('rejected'), old))).toContain('검토 요청 시 지금 판으로 다시 기록해')
  })

  it('반려된 개정과 같은 분석(검토 요청 단추 없음): 담당자에게 왜 없는지와 다시 올리는 길 한 줄', () => {
    const same = base(member, status('rejected'))
    expect(names(same)).not.toContain('request_review')
    expect(flowNotice(same)).toBe(REASONS.rejectedSame)
    expect(REASONS.rejectedSame).toContain('변경 원인·조건을 바꿔 새 개정으로 기록')
    // 화면이 다르면 검토 요청 단추가 있으니 안내는 개정 번호 쪽, 기록 권한이 없는 결재자·체험에게는 이 안내가 없음
    expect(names(base(member, status('rejected'), { shownMatches: false }))).toContain('request_review')
    expect(flowNotice(base(member, status('rejected'), { shownMatches: false }))).toContain('개정 2')
    const approverOnly: Me = { ...admin, permissions: admin.permissions.filter((p) => p !== 'record') }
    expect(flowNotice(base(approverOnly, status('rejected')))).toBeNull()
    expect(flowNotice(base(demo, status('rejected')))).toBeNull()
  })
})

describe('decisionProblem', () => {
  it('반려·보류 사유 필수, 확인 목록이 있으면 전부 체크 + 사유', () => {
    expect(decisionProblem('reject', ' ', [], new Set())).toBe('사유 입력 필요')
    expect(decisionProblem('approve', '', [], new Set())).toBeNull()
    expect(decisionProblem('approve', '확인', ['a', 'b'], new Set(['a']))).toContain('모두 확인')
    expect(decisionProblem('approve', '', ['a'], new Set(['a']))).toContain('사유')
    expect(decisionProblem('approve', '확인', ['a'], new Set(['a']))).toBeNull()
    expect(decisionProblem('hold', 'x'.repeat(501), [], new Set())).toContain('500자')
  })
})

describe('entryNotes', () => {
  it('사유·확인 수·대체·다른 지도·이전 계산 판·개발 모드', () => {
    const entry: AuditEntry = {
      seq: 3,
      at: '2026-10-09T03:00:00Z',
      actor: { login_id: 'dev', name: '개발', role: 'admin', dev: true },
      action: 'approve',
      ecn_id: 'ECN-D-0119',
      revision: 2,
      record_id: 'R-00000000000000aa',
      detail: {
        from_state: 'in_review',
        to_state: 'approved',
        reason: '확인함',
        acknowledged: ['a', 'b'],
        self_decision: true,
        other_map: false,
        other_version: true,
        steps: [],
        proxy: false,
        no_cost: false,
      },
      prev: '0'.repeat(64),
      digest: '1'.repeat(64),
    }
    expect(entryNotes(entry)).toEqual([
      '사유: 확인함',
      '확인 필요 2개를 확인하고 승인',
      '이전 계산 판으로 기록한 개정을 결정(현재 판으로 재계산·대조하지 않음)',
      '개발 모드에서 요청자가 직접 결정(업무 승인 아님)',
      '개발 모드 기록',
    ])
  })
})

describe('revisionFacts', () => {
  const revision: RevisionSummary = {
    revision: 1,
    record_id: 'R-00000000000000ab',
    analysis_id: 'A-9',
    recorded_at: '2026-10-24T11:23:00Z',
    recorded_by: { login_id: 'kim', name: '김담당', role: 'member', dev: false },
    snapshot_id: 'G-0000000000000001',
    data_mode: 'synthetic',
    title: 'B31P 판 두께 17.0→20.0mm (3장)',
    intent: 'strength',
    verdict: 'warn',
    total: { value: 34_210_000, low: 10_250_000, high: 80_130_000 },
    deadline: { kind: 'by_date', last_day: '2026-10-27' },
    as_of: '2026-10-20',
    confirm_on: '2026-10-20',
    holds: [],
    alternatives: false,
    checklist: 0,
  }

  it('결정 창 요약: 판정 · 변경 원인 · 총변경비용(범위) · 마감 · 확정일(기록 본문 값 그대로)', () => {
    expect(revisionFacts(revision, 'owner_request')).toEqual([
      { id: 'verdict', label: '판정', value: '경고' },
      { id: 'cause', label: '변경 원인', value: '선주 요청' },
      { id: 'total', label: '총변경비용', value: '3,421만원 · 1,025만~8,013만원', range: '1,025만~8,013만원' },
      // 마감 문장은 목록 표지(ecnList deadlineMark)의 읽기 문장 그대로 — 날짜는 아래에서 따로 본다
      { id: 'deadline', label: '결정 기한', value: deadlineMark(revision.deadline, revision.as_of).label },
      { id: 'confirm', label: '확정일', value: '10월 20일(화)' },
    ])
    expect(revisionFacts(revision, 'owner_request')[3].value).toContain('10월 27일(화)')
  })

  it('변경 원인 미입력은 주의 줄, 모르면(옛 개정) 줄을 빼고, 보류·대안은 가정 계산 줄로', () => {
    expect(revisionFacts(revision, null)[1]).toEqual({
      id: 'cause',
      label: '변경 원인',
      value: '미입력 — 비용 부담 판단 근거 없음',
      warn: true,
    })
    expect(revisionFacts(revision, undefined).map((f) => f.label)).not.toContain('변경 원인')
    const now = revisionFacts({ ...revision, deadline: { kind: 'confirm_now', last_day: '2026-10-20' } }, null)
    expect(now.find((f) => f.label === '결정 기한')?.value).toBe('10월 20일(화)(기준일)에 확정해야 추가손실 없음')
    const assumed = revisionFacts(
      { ...revision, holds: [{ po_id: 'PO-0037', hold_days: 12 }] as RevisionSummary['holds'], alternatives: true },
      'class_rule',
    ).at(-1)
    expect(assumed).toEqual({ id: 'assumed', label: '가정 계산', value: '발주 보류 1건(PO-0037 12일) · 대안 포함' })
  })

  it('결정 창 큰 숫자 칸: 총변경비용은 금액만 · 결정 기한은 날짜(D-n 없이) + 뜻 한 줄', () => {
    expect(revisionGlance(revision, '2026-10-20')).toEqual([
      { id: 'total', label: '총변경비용', value: '3,421만원', line: null, tone: 'neutral' },
      { id: 'deadline', label: '결정 기한', value: '10월 27일(화)', line: '그날까지 확정 시 추가손실 없음', tone: 'neutral' },
    ])
    const now = revisionGlance({ ...revision, deadline: { kind: 'confirm_now', last_day: '2026-10-20' } }, '2026-10-20')[1]
    expect(now).toMatchObject({ value: '10월 20일(화)', tone: 'danger' })
    const none = revisionGlance({ ...revision, deadline: { kind: 'none_in_horizon', last_day: '2026-12-19' } }, '2026-10-20')[1]
    expect(none).toMatchObject({ value: '기간 안 없음', line: '12월 19일(토)까지 확정해도 추가손실 없음', tone: 'success' })
    // D-3 이하면 위험 색(목록 표지와 같은 기준)
    const soon = revisionGlance({ ...revision, deadline: { kind: 'by_date', last_day: '2026-10-21' } }, '2026-10-20')[1]
    expect(soon?.tone).toBe('danger')
  })

  it('결정 창 큰 숫자 칸 위험 색은 개정 기준일이 아니라 오늘부터 센다(결정 도우미 결정 기한 카드와 같은 기준)', () => {
    // 개정 기준일 10-20 → 기한 10-27은 D-7이지만, 오늘 10-25면 D-2 · 기한 지난 10-30도 위험 색
    expect(revisionGlance(revision, '2026-10-25')[1]?.tone).toBe('danger')
    expect(revisionGlance(revision, '2026-10-30')[1]?.tone).toBe('danger')
    // 오늘이 개정 기준일보다 앞(기록 기준일이 늦은 지도)이면 남은 날이 늘어 보통 색
    const later = { ...revision, as_of: '2026-10-25' }
    expect(revisionGlance(later, '2026-10-20')[1]?.tone).toBe('neutral')
    // 경계: 오늘부터 3일이면 위험, 4일이면 보통
    expect(revisionGlance(revision, '2026-10-24')[1]?.tone).toBe('danger')
    expect(revisionGlance(revision, '2026-10-23')[1]?.tone).toBe('neutral')
    // 글은 그대로(날짜만, D-n 없이)
    expect(revisionGlance(revision, '2026-10-25')[1]).toMatchObject({ value: '10월 27일(화)', line: '그날까지 확정 시 추가손실 없음' })
  })

  it('큰 숫자 칸과 함께 쓰는 표: 판정·결정 기한은 빼고 총변경비용은 범위만, 나머지 줄은 그대로', () => {
    const facts = revisionFacts(revision, null)
    expect(restFacts(facts)).toEqual([
      { id: 'cause', label: '변경 원인', value: '미입력 — 비용 부담 판단 근거 없음', warn: true },
      { id: 'range', label: '금액 범위', value: '1,025만~8,013만원' },
      { id: 'confirm', label: '확정일', value: '10월 20일(화)' },
    ])
    // 범위가 없는(값 하나) 총변경비용은 줄을 빼고 칸만
    expect(restFacts([{ id: 'total', label: '총변경비용', value: '3,421만원' }])).toEqual([])
    // 거르기는 줄 종류(id)로 — 글자(라벨·' · ' 나누기)에 묶이지 않는다
    const renamed = facts.map((f) => ({ ...f, label: `${f.label}(개정)` }))
    expect(restFacts(renamed).map((f) => f.id)).toEqual(['cause', 'range', 'confirm'])
    const dotted = { id: 'total' as const, label: '총변경비용', value: '3,421만원 · 범위 · 끝', range: '1,025만~8,013만원' }
    expect(restFacts([dotted])).toEqual([{ id: 'range', label: '금액 범위', value: '1,025만~8,013만원' }])
  })

  it('후행 설치로 기록한 개정은 결정 창에도 가정 계산으로(화면의 분석 = 그 개정일 때 받은 값)', () => {
    expect(revisionFacts(revision, 'design_error', true).at(-1)).toEqual({ id: 'assumed', label: '가정 계산', value: '후행 설치' })
    for (const unknown of [false, undefined]) {
      expect(revisionFacts(revision, 'design_error', unknown).map((f) => f.label)).not.toContain('가정 계산')
    }
  })
})