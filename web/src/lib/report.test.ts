import { describe, expect, it } from 'vitest'
import type { Actor, AnalysisResult, AuditEntry, EcnDetail, EcnRecord, RevisionSummary } from '@/api/client'
import { designText, historyOf, reportOf, reportPath, traceLinkText } from './report'

const kim: Actor = { login_id: 'kim', name: '김담당', role: 'member', dev: false }
const lead: Actor = { login_id: 'lead', name: '관리자', role: 'admin', dev: false }
const dev: Actor = { login_id: 'dev', name: '개발', role: 'admin', dev: true }

function entry(seq: number, action: AuditEntry['action'], revision: number, actor: Actor, detail: Partial<AuditEntry['detail']> = {}): AuditEntry {
  return {
    seq,
    at: `2026-10-09T0${seq}:00:00Z`,
    actor,
    action,
    ecn_id: 'ECN-D-0119',
    revision,
    record_id: revision === 2 ? 'R-00000000000000bb' : 'R-00000000000000aa',
    detail: {
      from_state: 'analyzed',
      to_state: 'analyzed',
      acknowledged: [],
      other_map: false,
      other_version: false,
      self_decision: false,
      steps: [],
      proxy: false,
      no_cost: false,
      ...detail,
    },
    prev: '0'.repeat(64),
    digest: '1'.repeat(64),
  }
}

function summary(revision: number, recordId: string, by: Actor, at: string): RevisionSummary {
  return {
    revision,
    record_id: recordId,
    analysis_id: 'A-1',
    recorded_at: at,
    recorded_by: by,
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
  }
}

// 결과는 리포트가 읽는 필드만 채운 최소 모양(숫자는 결과 그대로 옮겨지는지만 본다)
const result = {
  analysis_id: 'A-1',
  request: {
    change: { ecn_id: 'ECN-D-0119', title: '판 두께', ship_ids: ['S-001'], intent: 'strength', ops: [] },
    as_of: '2026-10-20',
    confirm_on: null,
    holds: [],
    include_alternatives: false,
  },
  verdict: { level: 'warn', reasons: ['구역 출구 일정 지연 가능'] },
  total: { value: 35_290_000, low: 13_680_000, high: 81_560_000 },
  cost_lines: [
    { line_id: 'L-2', label: '도면 개정', amount: { value: 670_000, low: 300_000, high: 1_840_000 }, determinacy: 'determined' },
    { line_id: 'L-1', label: '블록 재작업', amount: { value: 25_930_000, low: 8_760_000, high: 63_620_000 }, determinacy: 'state_unknown' },
  ],
  timing: {
    deadline: { kind: 'by_date', last_day: '2026-10-27' },
    curve: [
      { confirm_on: '2026-10-20', total: { value: 35_290_000 }, additional_loss: { value: 0 }, events: [], max_exit_delay_days: 7 },
      { confirm_on: '2026-10-28', total: { value: 47_390_000 }, additional_loss: { value: 12_100_000 }, events: ['재작업'], max_exit_delay_days: 14 },
    ],
    holds: [],
    reallocations: [],
  },
  schedule: { zone_exits: [], max_exit_delay_days: 0, added_days_by_activity: {}, delivery: null },
  unresolved: [],
  alternatives: [],
  recommendation: null,
} as unknown as AnalysisResult

function detailOf(revisions: RevisionSummary[], audit: AuditEntry[]): EcnDetail {
  const latest = revisions.at(-1)!
  return {
    status: {
      ecn_id: 'ECN-D-0119',
      title: '판 두께',
      state: 'analyzed',
      version: audit.length,
      revision: latest.revision,
      record_id: latest.record_id,
      snapshot_id: 'G-0000000000000001',
      review: null,
      approved_revision: null,
      approval_dev: false,
      real: false,
      updated_at: '2026-10-09T09:00:00Z',
    },
    revisions,
    audit,
    checklist: [],
    same_version: true,
    latest_design_status: 'unknown',
    latest_effectivity: null,
  }
}

const record = (id: string): EcnRecord => ({
  record_id: id,
  body: { ecn_id: 'ECN-D-0119', snapshot_id: 'G-0000000000000001', data_mode: 'synthetic', result, checklist: [] },
})

describe('reportOf', () => {
  // 개정 1(기록 aa) → 개정 2(기록 bb) 검토 요청 → 개정 3(옛 내용으로 되돌림 = 기록 aa)이 개정 2 검토를 끝냄
  const audit = [
    entry(1, 'record', 1, kim),
    entry(2, 'record', 2, kim),
    entry(3, 'request_review', 2, kim, { to_state: 'in_review' }),
    entry(4, 'record', 3, lead, { from_state: 'in_review', superseded_review_seq: 3 }),
  ]
  const revisions = [
    summary(1, 'R-00000000000000aa', kim, '2026-10-09T01:00:00Z'),
    summary(2, 'R-00000000000000bb', kim, '2026-10-09T02:00:00Z'),
    summary(3, 'R-00000000000000aa', lead, '2026-10-09T04:00:00Z'),
  ]
  const detail = detailOf(revisions, audit)

  it('개정 번호로 고른다: 같은 기록 ID를 가리키는 개정 1·3은 기록한 사람·시각·이력이 다름', () => {
    const one = reportOf(detail, record('R-00000000000000aa'), 1)
    const three = reportOf(detail, record('R-00000000000000aa'), 3)
    if (typeof one === 'string' || typeof three === 'string') throw new Error('리포트 없음')
    expect(one.recordedBy).toContain('김담당')
    expect(three.recordedBy).toContain('관리자')
    expect(one.history.map((h) => h.seq)).toEqual([1])
    expect(three.history.map((h) => h.seq)).toEqual([4])
    expect(one.newer).toBe(3)
    expect(three.newer).toBeNull()
  })

  it('개정 2 리포트에는 뒤 개정 3의 기록이 끝낸 그 검토가 이어 보임', () => {
    const two = reportOf(detail, record('R-00000000000000bb'), 2)
    if (typeof two === 'string') throw new Error('리포트 없음')
    expect(two.history.map((h) => h.seq)).toEqual([2, 3, 4])
    expect(two.history[2].label).toContain('개정 3 기록')
    expect(two.history[2].notes).toContain('진행 중이던 검토는 새 개정으로 끝남')
  })

  it('없는 개정 · 다른 기록이면 문제 코드', () => {
    expect(reportOf(detail, record('R-00000000000000aa'), 9)).toBe('no_revision')
    expect(reportOf(detail, record('R-00000000000000bb'), 1)).toBe('record_mismatch')
  })

  it('숫자는 결과 필드 그대로(금액 큰 순·판단 불가·합계·계단)', () => {
    const one = reportOf(detail, record('R-00000000000000aa'), 1)
    if (typeof one === 'string') throw new Error('리포트 없음')
    expect(one.costs.map((c) => c.label)).toEqual(['블록 재작업', '도면 개정'])
    expect(one.costs[0].unknown).toBe(true)
    expect(one.total.value).toBe('3,529만원')
    expect(one.steps).toHaveLength(1)
    expect(one.steps[0].added).toBe('1,210만원')
    expect(one.conditions).toContain('발주 보류 없음')
    expect(one.synthetic).toBe(true)
    expect(one.cause).toBe('미입력') // 원인 필드가 없는 기록(1.28.0 전)
  })

  it('후행 설치로 계산한 개정은 분석 조건에 그 가정을 적음(기록 본문의 요청에서)', () => {
    const board = { ...result, request: { ...result.request, outfit_on_board: true } }
    const onBoard: EcnRecord = { ...record('R-00000000000000aa'), body: { ...record('R-00000000000000aa').body, result: board } }
    const model = reportOf(detail, onBoard, 1)
    if (typeof model === 'string') throw new Error('리포트 없음')
    expect(model.conditions).toContain('후행 설치')
    const plain = reportOf(detail, record('R-00000000000000aa'), 1)
    if (typeof plain === 'string') throw new Error('리포트 없음')
    expect(plain.conditions).not.toContain('후행 설치')
  })

  it('개발 모드 자기 결정은 업무 승인이 아니라고 이력에 남김', () => {
    const devAudit = [
      entry(1, 'record', 1, dev),
      entry(2, 'request_review', 1, dev, { to_state: 'in_review' }),
      entry(3, 'approve', 1, dev, { from_state: 'in_review', to_state: 'approved', self_decision: true, review_seq: 2 }),
    ]
    const devDetail = detailOf([summary(1, 'R-00000000000000aa', dev, '2026-10-09T01:00:00Z')], devAudit)
    const model = reportOf(devDetail, record('R-00000000000000aa'), 1)
    if (typeof model === 'string') throw new Error('리포트 없음')
    expect(model.history[2].notes.join(' ')).toContain('업무 승인 아님')
  })
})

describe('historyOf · reportPath', () => {
  it('그 개정의 줄 + 대체한 뒤 개정 기록, 순번 순', () => {
    const audit = [entry(3, 'request_review', 2, kim), entry(4, 'record', 3, lead, { superseded_review_seq: 3 }), entry(2, 'record', 2, kim)]
    expect(historyOf(audit, 2).map((e) => e.seq)).toEqual([2, 3, 4])
    expect(historyOf(audit, 3).map((e) => e.seq)).toEqual([4])
  })

  it('주소는 ECN 번호를 인코딩', () => {
    expect(reportPath('ECN-D-0119', 3)).toBe('/app/report/ECN-D-0119/3')
    expect(reportPath('ECN-AI-ab.c_1', 1)).toBe('/app/report/ECN-AI-ab.c_1/1')
  })
})

describe('designText · traceLinkText(1.23.0)', () => {
  it('승인 상태 이름은 늘 남고 적용 시작일은 뒤에 붙음, 옛 기록은 미입력', () => {
    expect(designText('owner_pending', null)).toBe('선주 승인 대기')
    expect(designText('owner_pending', '2026-11-01')).toMatch(/^선주 승인 대기 · 적용 시작 /)
    expect(designText(undefined, null)).toBe('미입력')
  })
  it('연결 고리: 이름은 늘, 상태는 있을 때만', () => {
    expect(traceLinkText({ label: 'B31P', status: '조립' })).toBe('B31P · 조립')
    expect(traceLinkText({ label: 'PO-1#1', status: null })).toBe('PO-1#1')
  })
})
