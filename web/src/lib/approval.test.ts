import { describe, expect, it } from 'vitest'
import type { ApprovalPlan, EcnStatus, Me } from '@/api/client'
import { currentStep, decideAs, decisionNote, lineGuide, lineNames, lineNodes, lineSummary, submitLine } from './approval'
import { availableActions, entryNotes, flowNotice, type FlowInput } from './records'

const me = (role: Me['role'], login_id: string, permissions: Me['permissions']): Me => ({
  login_id,
  name: login_id,
  role,
  must_change_password: false,
  permissions,
})
const APPROVER: Me['permissions'] = ['view', 'export', 'change_password', 'approve']
const part = me('part_lead', 'part', APPROVER)
const boss = me('executive', 'boss', APPROVER)
const lead = me('admin', 'lead', ['view', 'export', 'switch_map', 'import', 'manage_accounts', 'change_password', 'approve'])
const kim = me('member', 'kim', ['view', 'export', 'change_password', 'record'])

const LINE = ['part_lead', 'team_lead', 'executive'] as const

function reviewing(step: number, state: EcnStatus['state'] = 'in_review'): EcnStatus {
  return {
    ecn_id: 'ECN-D-0119',
    title: '판 두께',
    state,
    version: 4,
    revision: 1,
    record_id: 'R-00000000000000aa',
    snapshot_id: 'G-0000000000000001',
    review: {
      seq: 3,
      revision: 1,
      requested_by: { login_id: 'kim', name: '김설계', role: 'member', dev: false },
      requested_at: '2026-10-28T01:00:00Z',
      steps: [...LINE],
      step,
    },
    approved_revision: null,
    approval_dev: false,
    real: false,
    updated_at: '2026-10-28T01:00:00Z',
  }
}

function analyzed(): EcnStatus {
  return { ...reviewing(1), state: 'analyzed', review: null }
}

function plan(extra: Partial<ApprovalPlan> = {}): ApprovalPlan {
  return {
    no_cost: false,
    line: [...LINE],
    steps: [...LINE],
    days_per_step_low: 1,
    days_per_step: 2,
    workdays: 6,
    submit_by: '2026-11-02',
    late: false,
    late_low: false,
    line_steps: 3,
    holds: [],
    ...extra,
  }
}

const input = (who: Me, status: EcnStatus | null, extra: Partial<FlowInput> = {}): FlowInput => ({
  me: who,
  status,
  resultReady: true,
  shownMatches: true,
  sameMap: true,
  sameVersion: true,
  loginMode: true,
  ...extra,
})

const names = (i: FlowInput) => availableActions(i).map((a) => a.action)

describe('결재선: 지금 단계의 결재자만 결정, 팀장은 전결', () => {
  it('역할 → 단계: 파트장은 1단계, 팀장은 2단계(1·3단계는 전결), 본부장은 3단계', () => {
    expect([1, 2, 3].map((s) => decideAs(part, reviewing(s), true))).toEqual(['own', null, null])
    expect([1, 2, 3].map((s) => decideAs(lead, reviewing(s), true))).toEqual(['proxy', 'own', 'proxy'])
    expect([1, 2, 3].map((s) => decideAs(boss, reviewing(s), true))).toEqual([null, null, 'own'])
    expect(decideAs(kim, reviewing(1), true)).toBeNull()
    expect(currentStep(reviewing(2))).toBe('team_lead')
  })

  it('결정 단추: 자기 단계면 승인·반려·보류, 다른 단계 결재자는 단추 없이 안내, 팀장 전결은 표시', () => {
    expect(names(input(part, reviewing(1)))).toEqual(['approve', 'reject', 'hold'])
    expect(names(input(part, reviewing(2)))).toEqual([])
    expect(flowNotice(input(part, reviewing(2)))).toBe('팀장 결재 대기(2/3단계)')
    expect(flowNotice(input(kim, reviewing(1)))).toBe('파트장 결재 대기(1/3단계)')
    const proxied = availableActions(input(lead, reviewing(3))).filter((a) => a.dialog)
    expect(proxied.map((a) => [a.action, a.proxy])).toEqual([
      ['approve', true],
      ['reject', true],
      ['hold', true],
    ])
    expect(availableActions(input(lead, reviewing(2))).filter((a) => a.dialog).every((a) => !a.proxy)).toBe(true)
    expect(names(input(boss, reviewing(3, 'on_hold')))).toEqual(['approve', 'reject'])
  })

  it('개발 모드(로그인 끔): 서버처럼 모든 단계가 자기 단계 — 전결 표시 없음', () => {
    expect([1, 2, 3].map((s) => decideAs(lead, reviewing(s), false))).toEqual(['own', 'own', 'own'])
    expect(decideAs(kim, reviewing(1), false)).toBeNull() // 승인 권한이 없으면 개발 모드라도 결정 단추 없음
    const dev = availableActions(input(lead, reviewing(1), { loginMode: false })).filter((a) => a.dialog)
    expect(dev.map((a) => [a.action, a.proxy])).toEqual([
      ['approve', false],
      ['reject', false],
      ['hold', false],
    ])
  })

  it('무비용 담당자 처리: 기록한 개정이 무비용이고 화면이 그 개정이면 담당자에게만, 지도가 바뀌면 흐림', () => {
    const free = plan({ no_cost: true, steps: [], workdays: 0, submit_by: null })
    expect(names(input(kim, analyzed(), { plan: free }))).toContain('settle')
    expect(names(input(kim, analyzed(), { plan: plan() }))).not.toContain('settle')
    expect(names(input(kim, analyzed(), { plan: free, shownMatches: false }))).not.toContain('settle')
    expect(names(input(lead, analyzed(), { plan: free }))).not.toContain('settle')
    const moved = availableActions(input(kim, analyzed(), { plan: free, sameMap: false })).find((a) => a.action === 'settle')
    expect(moved?.enabled).toBe(false)
  })

  it('결정 대화상자 안내: 단계·다음 단계, 전결이면 감사 기록, 마지막 단계면 실행 가능', () => {
    expect(decisionNote('approve', reviewing(1), 'own')).toBe('파트장 결재(1/3단계) · 승인 시 팀장 결재로')
    expect(decisionNote('approve', reviewing(3), 'proxy')).toBe(
      '본부장 단계(3/3단계) 팀장 전결 · 감사 기록에 전결·원래 단계 남음 · 마지막 단계 — 승인 시 실행 가능',
    )
    expect(decisionNote('reject', reviewing(2), 'own')).toBe('팀장 결재(2/3단계)')
    expect(decisionNote('settle', analyzed(), null)).toBeNull()
  })

  it('이력 세부: 결재선·결정한 단계(전결)·무비용', () => {
    const base = {
      seq: 4,
      at: '2026-10-28T02:00:00Z',
      actor: { login_id: 'lead', name: '박팀장', role: 'admin' as const, dev: false },
      ecn_id: 'ECN-D-0119',
      revision: 1,
      record_id: 'R-00000000000000aa',
      prev: '0'.repeat(64),
      digest: '1'.repeat(64),
    }
    const detail = {
      from_state: 'in_review' as const,
      to_state: 'in_review' as const,
      acknowledged: [],
      other_map: false,
      other_version: false,
      self_decision: false,
      steps: [],
      proxy: true,
      no_cost: false,
      step: 'part_lead' as const,
    }
    expect(entryNotes({ ...base, action: 'approve', detail })).toEqual(['파트장 단계 · 팀장 전결'])
    expect(entryNotes({ ...base, action: 'request_review', detail: { ...detail, step: null, proxy: false, steps: [...LINE] } })).toEqual([
      '결재선 파트장 → 팀장 → 본부장',
    ])
    expect(
      entryNotes({ ...base, action: 'settle', detail: { ...detail, step: null, proxy: false, no_cost: true, to_state: 'approved' } }),
    ).toEqual(['비용이 도면 개정뿐이라 결재 없이 담당자 처리'])
  })

  it('검토 요청 창 결재선 글: 서버 결재 계획의 결재선·단계당 근무일 그대로(결재선이 없으면 그리지 않음)', () => {
    expect(lineSummary(plan())).toBe('파트장 → 팀장 → 본부장 · 단계마다 1~2근무일')
    expect(lineSummary(plan({ line: ['team_lead'], steps: ['team_lead'], days_per_step_low: 2, days_per_step: 3 }))).toBe(
      '팀장 · 단계마다 2~3근무일',
    )
    expect(lineNames(plan())).toBe('파트장·팀장·본부장')
    expect(lineSummary(plan({ line: [] }))).toBeNull()
    expect(lineSummary(null)).toBeNull()
    expect(lineNames(undefined)).toBeNull()
  })
})

describe('결재 계획 문구(서버 값 그대로)', () => {
  it('결재 올릴 기한: 날짜·소요, 검토 중이면 남은 단계, 기한 경과 시 결정 가능일·그날 추가손실', () => {
    expect(submitLine(plan(), false)).toEqual({ text: '결재 올릴 기한 11월 2일(월)(결재 3단계 · 근무일 3~6일)', tone: 'ok' })
    expect(submitLine(plan({ steps: ['team_lead', 'executive'], workdays: 4 }), true)?.text).toBe(
      '남은 결재 기한 11월 2일(월)(결재 2단계 · 근무일 2~4일)',
    )
    const late = plan({ late: true, earliest: '2026-11-05', earliest_loss: 12_100_000 })
    expect(submitLine(late, false)).toEqual({
      text: '결재 올릴 기한 11월 2일(월) 지남 · 결정 가능일 11월 5일(목) · 추가손실 1,210만원',
      tone: 'late',
    })
    expect(submitLine(late, true)?.text).toBe('남은 결재 기한 11월 2일(월) 지남 · 결정 가능일 11월 5일(목) · 추가손실 1,210만원')
    expect(submitLine(plan({ submit_by: null }), false)).toBeNull() // 기간 안 손실 없음
    expect(submitLine(plan({ no_cost: true, steps: [], workdays: 0, submit_by: null }), false)?.tone).toBe('none')
    expect(submitLine(null, false)).toBeNull()
  })

  it('단계당 1일 기한: 대표 기한 전이면 함께, 대표만 지났으면 주의 색으로 그날까지, 둘 다 지나면 지금처럼', () => {
    // 결정 기한 11월 6일(금): 대표 6근무일 앞 10월 29일(목), 단계당 1일이면 3근무일 앞 11월 3일(화)
    const early = plan({ submit_by: '2026-10-29', submit_by_low: '2026-11-03' })
    expect(submitLine(early, false)).toEqual({
      text: '결재 올릴 기한 10월 29일(목) · 단계당 1일이면 11월 3일(화) (결재 3단계)',
      tone: 'ok',
    })
    // 결정 기한 11월 4일(수), 업무상 오늘 10월 28일: 대표 10월 27일(화)은 지났고 단계당 1일 10월 30일(금)은 남음
    const caution = plan({ submit_by: '2026-10-27', submit_by_low: '2026-10-30', late: true, earliest: '2026-11-05' })
    expect(submitLine(caution, false)).toEqual({
      text: '결재 올릴 기한 10월 27일(화)(단계당 2일) 지남 · 단계당 1일이면 10월 30일(금)까지',
      tone: 'caution',
    })
    expect(submitLine({ ...caution, steps: ['executive'], workdays: 2 }, true)?.text).toBe(
      '남은 결재 기한 10월 27일(화)(단계당 2일) 지남 · 단계당 1일이면 10월 30일(금)까지',
    )
    const both = { ...caution, submit_by_low: '2026-10-26', late_low: true, earliest_loss: 12_100_000 }
    expect(submitLine(both, false)).toEqual({
      text: '결재 올릴 기한 10월 27일(화) 지남 · 결정 가능일 11월 5일(목) · 추가손실 1,210만원',
      tone: 'late',
    })
    // 단계당 근무일이 같으면(두 기한이 같은 날) 빠른 경우를 따로 적지 않음, 무비용은 그대로 결재 없음
    expect(submitLine(plan({ submit_by_low: '2026-11-02' }), false)?.text).toBe('결재 올릴 기한 11월 2일(월)(결재 3단계 · 근무일 3~6일)')
    const free = plan({ no_cost: true, steps: [], workdays: 0, submit_by: null, submit_by_low: null })
    expect(submitLine(free, false)).toEqual({ text: '담당자 처리 — 결재 없음(비용이 도면 개정뿐 · 승인 가능)', tone: 'none' })
  })

  it('결재함 줄에 한 줄로 들어가게 짧게(1억 원대 추가손실이어도 60자 안)', () => {
    const longest = [
      plan({ submit_by: '2026-10-27', submit_by_low: '2026-10-30', late: true, earliest: '2026-11-05' }),
      plan({ submit_by: '2026-10-27', submit_by_low: '2026-10-26', late: true, late_low: true, earliest: '2026-11-05', earliest_loss: 123_456_789 }),
      plan({ submit_by: '2026-10-29', submit_by_low: '2026-11-03' }),
    ]
    for (const p of longest) for (const reviewing of [false, true]) expect(submitLine(p, reviewing)!.text.length).toBeLessThanOrEqual(60)
  })

  it('성질: 단계당 1일 기한이 있고 대표 기한이 지났으면, 단계당 1일 기한이 남았는지에 따라 주의·위험이 갈림', () => {
    for (const lateLow of [false, true]) {
      const p = plan({ submit_by: '2026-10-27', submit_by_low: '2026-10-30', late: true, late_low: lateLow, earliest: '2026-11-05' })
      const line = submitLine(p, false)!
      expect(line.tone).toBe(lateLow ? 'late' : 'caution')
      expect(line.text.includes('10월 30일(금)')).toBe(!lateLow)
    }
  })

  it('결재선 안내와 진행: 무비용이면 담당자 처리, 앞 단계 승인은 사람·전결', () => {
    expect(lineGuide(plan())).toBe('결재선 파트장 → 팀장 → 본부장 · 결재 3단계 · 근무일 3~6일')
    expect(lineGuide(plan({ no_cost: true, steps: [], workdays: 0, submit_by: null }))).toContain('결재 없이 담당자 처리')
    const nodes = lineNodes([...LINE], 3, [
      { step: 'part_lead', actor: { login_id: 'part', name: '이파트장', role: 'part_lead', dev: false }, at: '', proxy: false },
      { step: 'team_lead', actor: { login_id: 'lead', name: '박팀장', role: 'admin', dev: false }, at: '', proxy: false },
    ])
    expect(nodes.map((n) => [n.label, n.state, n.by])).toEqual([
      ['파트장', 'done', '이파트장'],
      ['팀장', 'done', '박팀장'],
      ['본부장', 'now', null],
    ])
    const proxied = lineNodes([...LINE], 2, [
      { step: 'part_lead', actor: { login_id: 'lead', name: '박팀장', role: 'admin', dev: false }, at: '', proxy: true },
    ])
    expect(proxied[0].by).toBe('박팀장 전결')
  })
})
