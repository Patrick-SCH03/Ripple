// 설계변경 검토서 전용 값: KST 표기 · 연산 줄 · 대상 블록 · 핵심 수치 표(해당 없음도 줄) · 영향 범위 · 결재란 · 쪽 머리 CSS.
import { describe, expect, it } from 'vitest'
import type { Actor, AnalysisResult, AuditEntry } from '@/api/client'
import {
  cssString,
  figureRows,
  kstDay,
  kstStamp,
  opLine,
  pageCss,
  scopeSummary,
  sheetOf,
  signCells,
  sourceLine,
  targetBlocks,
} from './sheet'

const kim: Actor = { login_id: 'kim', name: '김설계', role: 'member', dev: false }
const part: Actor = { login_id: 'part-lead', name: '이파트장', role: 'part_lead', dev: false }
const lead: Actor = { login_id: 'lead', name: '박팀장', role: 'admin', dev: false }

function entry(seq: number, action: AuditEntry['action'], revision: number, actor: Actor, detail: Partial<AuditEntry['detail']> = {}): AuditEntry {
  return {
    seq,
    at: `2026-10-2${seq}T01:00:00Z`,
    actor,
    action,
    ecn_id: 'ECN-D-0119',
    revision,
    record_id: 'R-00000000000000aa',
    detail: {
      from_state: 'analyzed',
      to_state: 'in_review',
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

const name = (id: string) => ({ 'S-001:B31P-PL-002': '판 2', 'S-001:B31P-PL-005': '판 5' })[id] ?? id

const result = {
  analysis_id: 'A-1',
  request: {
    change: {
      ecn_id: 'ECN-D-0119',
      title: 'B31P 판 두께',
      ship_ids: ['S-001'],
      ops: [{ op: 'thickness', part_ids: ['S-001:B31P-PL-002', 'S-001:B31P-PL-005'], from_mm: 17, to_mm: 20 }],
      raw_text: null,
      cause: 'class_rule',
    },
    as_of: '2026-10-20',
    confirm_on: null,
    holds: [],
  },
  total: { value: 35_290_000, low: 13_680_000, high: 81_560_000 },
  cost_lines: [],
  timing: {
    deadline: { kind: 'by_date', last_day: '2026-10-27' },
    curve: [
      { confirm_on: '2026-10-20', total: { value: 35_290_000 }, additional_loss: { value: 0, low: 0, high: 0 }, events: [], max_exit_delay_days: 0 },
    ],
    holds: [],
    reallocations: [],
  },
  schedule: { zone_exits: [], max_exit_delay_days: 0, added_days_by_activity: {}, delivery: null },
  impacts: [
    { entity_type: 'block', entity_id: 'S-001:B31P', impact_type: 'rework', severity: 'high', path: [{}] },
    { entity_type: 'drawing', entity_id: 'DWG-1@A', impact_type: 'drawing_revision', severity: 'low', path: [{}] },
    { entity_type: 'part', entity_id: 'S-001:B31P-PL-003', impact_type: 'taper', severity: 'medium', path: [{}] },
    { entity_type: 'block', entity_id: 'S-001:B32P', impact_type: 'rework', severity: 'medium', path: [{}, {}] },
    { entity_type: 'po_line', entity_id: 'PO-1#1', impact_type: 'po_change', severity: 'high', path: [{}] },
  ],
  graph: {
    nodes: [
      { id: 'S-001:B31P-PL-002', label: '판 2' },
      { id: 'S-001:B32P', label: 'B32P 블록' },
    ],
    edges: [],
  },
  weight_change: {
    blocks: [{ block_id: 'S-001:B31P', name: 'No.3 COT 이중저 좌', before_t: 2.405, after_t: 2.83, delta_t: 0.425, counted: 2, missing: 0, parts: [] }],
    before_t: 2.405,
    after_t: 2.83,
    delta_t: 0.425,
    counted: 2,
    missing: 0,
  },
  trace: null,
} as unknown as AnalysisResult

describe('KST 표기', () => {
  it('UTC 시각 → KST 날짜·시각, 없으면 —', () => {
    expect(kstStamp('2026-10-20T15:30:00Z')).toBe('2026-10-21 00:30 KST')
    expect(kstDay('2026-10-20T15:30:00Z')).toBe('2026-10-21')
    expect(kstStamp(null)).toBe('—')
    expect(kstDay('not-a-date')).toBe('')
  })
})

describe('변경 내용 · 대상 블록', () => {
  it('연산 줄: 이름 3개까지 · 넘으면 외 n', () => {
    expect(opLine({ op: 'thickness', part_ids: ['S-001:B31P-PL-002', 'S-001:B31P-PL-005'], from_mm: 17, to_mm: 20 }, name)).toBe(
      '두께 변경 · 2개(판 2, 판 5) · 17mm → 20mm',
    )
    expect(opLine({ op: 'remove_part', part_ids: ['a', 'b', 'c', 'd', 'e'] }, name)).toBe('부재 삭제 · 5개(a, b, c 외 2)')
    expect(opLine({ op: 'add_part', block_id: 'S-001:B31P', kind: 'stiffener', spec_id: 'HP240', qty: 0.4, attach_to_part_id: null }, name)).toBe(
      '부재 추가 · HP240 수량 0.4 · 블록 B31P',
    )
    expect(opLine({ op: 'add_penetration', plate_part_id: 'S-001:B31P-PL-002', pipe_part_id: 'P', diameter_mm: 150 }, name)).toBe(
      '관통부 추가 · 판 2 · 지름 150mm',
    )
  })

  it('대상 블록: 중량 변화 블록 → 연결 추적 블록 → —', () => {
    expect(targetBlocks(result)).toBe('B31P')
    expect(targetBlocks({ weight_change: undefined, trace: [{ block: { entity_id: 'S-001:E21C' } }] } as never)).toBe('E21C')
    expect(targetBlocks({ weight_change: undefined, trace: null } as never)).toBe('—')
  })
})

describe('핵심 수치 · 영향 범위', () => {
  it('해당 없음도 줄로: 총변경비용 → 결정 기한(날짜 · D-n) → 구역 출구 0일 → 이미 발주된 품목', () => {
    const rows = figureRows(result)
    expect(rows.map((r) => r.label)).toEqual(['총변경비용', '결정 기한', '구역 출구 지연', '이미 발주된 품목'])
    expect(rows[0].value).toBe('3,529만원')
    expect(rows[1].value).toBe('10월 27일(화) · D-7')
    expect(rows[2]).toMatchObject({ value: '0일', detail: '지연 없음' })
    expect(rows[3]).toMatchObject({ value: '0건', caution: '발주 단계 판단 불가 1건' })
  })

  it('영향 범위: 엔터티 종류별 수 · 2차 영향(경로 두 단계 이상) · 심각도 순 이름', () => {
    const scope = scopeSummary(result)
    expect(scope.counts).toEqual([
      { label: '블록', count: 2 },
      { label: '발주 품목', count: 1 },
      { label: '공정', count: 0 },
      { label: '도면', count: 1 },
    ])
    expect(scope.secondary).toBe(1)
    expect(scope.highlights).toEqual(['B32P 블록 — 블록 재작업'])
  })
})

describe('결재란', () => {
  it('담당 = 마지막 검토 요청, 단계별 마지막 결정(전결 표시), 기록 없는 칸은 빈칸', () => {
    const audit = [
      entry(1, 'record', 1, kim),
      entry(2, 'request_review', 1, kim, { steps: ['part_lead', 'team_lead', 'executive'] }),
      entry(3, 'approve', 1, part, { review_seq: 2, step: 'part_lead' }),
      entry(4, 'hold', 1, lead, { review_seq: 2, step: 'team_lead' }),
      entry(5, 'approve', 1, lead, { review_seq: 2, step: 'team_lead' }),
      entry(6, 'approve', 2, lead, { review_seq: 9, step: 'executive' }),
    ]
    const cells = signCells(audit, 1)
    expect(cells.map((c) => [c.role, c.name, c.mark, c.proxy, c.day])).toEqual([
      ['담당', '김설계', '검토 요청', false, '2026-10-22'],
      ['파트장', '이파트장', '승인', false, '2026-10-23'],
      ['팀장', '박팀장', '승인', false, '2026-10-25'],
      ['본부장', null, null, false, ''],
    ])
    const proxied = signCells([entry(2, 'request_review', 1, kim), entry(3, 'approve', 1, lead, { review_seq: 2, step: 'part_lead', proxy: true })], 1)
    expect(proxied[1]).toMatchObject({ name: '박팀장', mark: '승인', proxy: true })
  })

  it('검토 요청 없음 → 네 칸 모두 빈칸, 무비용 담당자 처리 → 담당 칸만, 단계 없는 옛 결정 → 팀장 칸', () => {
    expect(signCells([entry(1, 'record', 1, kim)], 1).every((c) => c.name === null)).toBe(true)
    const settled = signCells([entry(1, 'settle', 1, kim)], 1)
    expect(settled[0]).toMatchObject({ name: '김설계', mark: '담당자 처리' })
    expect(settled.slice(1).every((c) => c.name === null)).toBe(true)
    const old = signCells([entry(2, 'request_review', 1, kim), entry(3, 'reject', 1, lead, { review_seq: 2, step: null })], 1)
    expect(old[2]).toMatchObject({ role: '팀장', name: '박팀장', mark: '반려' })
  })

  it('검토서 한 벌: 결재선은 그 검토에 고정한 결재선, 작성일 = 기록 시각(KST), 중량 변화 그대로', () => {
    const audit = [entry(2, 'request_review', 1, kim, { steps: ['part_lead', 'team_lead', 'executive'] })]
    const sheet = sheetOf(result, audit, 1, '2026-10-20T00:10:00Z')
    expect(sheet.line).toBe('파트장 → 팀장 → 본부장')
    expect(sheet.writtenAt).toBe('2026-10-20 09:10 KST')
    expect(sheet.blocks).toBe('B31P')
    expect(sheet.change.cause).toBe('선급·규정')
    expect(sheet.weight?.delta_t).toBe(0.425)
    expect(sheetOf({ ...result, weight_change: undefined } as AnalysisResult, [], 1, '').weight).toBeNull()
  })
})

describe('꼬리', () => {
  it('출처 · 쪽 머리 CSS(따옴표·역빗금 막음)', () => {
    expect(sourceLine(true)).toBe('합성 데이터 · Ripple 분석 결과')
    expect(sourceLine(false)).toBe('Ripple 분석 결과')
    expect(cssString('a "b" \\c')).toBe('"a \\"b\\" \\\\c"')
    const css = pageCss('설계변경 검토서 · ECN-D-0119 개정 1', '합성 데이터 · Ripple 분석 결과')
    expect(css).toContain('@top-right { content: "설계변경 검토서 · ECN-D-0119 개정 1"')
    expect(css).toContain('counter(page) " / " counter(pages)')
  })
})
