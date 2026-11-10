// 사전 점검 표시: 수준 순 정렬 · P-06 현장 공유 묶음(맨 아래) · 요약 · 이름 · 합성 NCR 칩 · 옛 기록은 묶음 없음.
import { describe, expect, it } from 'vitest'
import type { AnalysisResult, PrecheckItem } from '@/api/client'
import { entityName, evidenceText, ncrText, notifyLine, precheckView, targetsOf } from './precheck'

function item(over: Partial<PrecheckItem> & Pick<PrecheckItem, 'key' | 'rule_id' | 'level'>): PrecheckItem {
  return {
    name: '규칙',
    finding: '무엇',
    targets: ['S-001:B31P'],
    evidence: [],
    text: '이 건에서 본 것이에요.',
    reason: '위험 이유예요.',
    ncr_count: 12,
    ...over,
  }
}

const result = (prechecks: PrecheckItem[] | undefined, contract = '1.32.0') =>
  ({ prechecks, versions: { contract } }) as unknown as Pick<AnalysisResult, 'prechecks' | 'versions'>

describe('사전 점검 묶음', () => {
  it('확인 필요 → 주의 → 점검 불가 순, P-06은 따로 맨 아래 묶음(블록 수), 요약은 0을 빼고', () => {
    const view = precheckView(
      result([
        item({ key: 'P-06:notify:S-001:L31C', rule_id: 'P-06', level: 'check' }),
        item({ key: 'P-05:support:X', rule_id: 'P-05', level: 'check' }),
        item({ key: 'P-01:late_install:B', rule_id: 'P-01', level: 'caution' }),
        item({ key: 'P-02:missing:A', rule_id: 'P-02', level: 'check' }),
        item({ key: 'P-06:notify:S-001:B31P', rule_id: 'P-06', level: 'check' }),
      ]),
    )!
    expect(view.items.map((i) => i.key)).toEqual(['P-02:missing:A', 'P-05:support:X', 'P-01:late_install:B'])
    expect(view.notify?.items.map((i) => i.key)).toEqual(['P-06:notify:S-001:B31P', 'P-06:notify:S-001:L31C'])
    expect(view.notify?.ncr).toBe(12)
    expect(view.summary).toBe('확인 필요 2 · 주의 1 · 현장 통보 2곳')
  })

  it('비면(응답에서 빠짐) 걸린 것 없음, 1.32.0 전 기록은 묶음 없음', () => {
    expect(precheckView(result(undefined))).toEqual({ items: [], notify: null, summary: '' })
    expect(precheckView(result([], '1.31.0'))).toBeNull()
  })

  it('이름: 지도 카드 이름 → 공정이면 블록 공정 → 직영 → 코드, 근거 한 줄, 지도에 없는 대상은 누를 수 없음', () => {
    const nodes = [{ id: 'S-001:A11C-PL-001', label: '선미 판 1' }]
    expect(entityName('S-001:A11C-PL-001', nodes)).toBe('선미 판 1')
    expect(entityName('S-001:B31P:pre_erection', nodes)).toBe('B31P PE')
    expect(entityName('direct', nodes)).toBe('직영')
    expect(entityName('S-001:B31P', nodes)).toBe('B31P')
    expect(
      evidenceText({ src: 'NEW:1', dst: 'S-001:A11C-PL-001', relation: 'penetration', virtual: true }, nodes),
    ).toBe('새 부재 →(관통) 선미 판 1 · 변경으로 생김')
    expect(targetsOf({ targets: ['S-001:A11C-PL-001', 'S-001:B31P'] }, nodes)).toEqual([
      { id: 'S-001:A11C-PL-001', name: '선미 판 1', node: 'S-001:A11C-PL-001' },
      { id: 'S-001:B31P', name: 'B31P', node: null },
    ])
  })

  it("합성 NCR 칩은 '합성'을 적고, 건수가 없으면(실데이터) 칩 없음", () => {
    expect(ncrText(3)).toBe('같은 유형 합성 NCR 3건')
    expect(ncrText(null)).toBeNull()
    expect(ncrText(undefined)).toBeNull()
  })

  it('현장 통보 한 항목: 핵심 한 줄(블록 · 통보할 주체) + 이미 한 공정 한 줄, 꼴이 다르면 원문 그대로', () => {
    const text =
      'B31P 블록에서 이미 한 공정(소조립·판넬조립·대조립 완료, 선행의장 진행 중)을 맡은 직영·해송 작업반에 변경 내용 통보 필요'
    expect(notifyLine(text)).toEqual({
      head: 'B31P · 직영·해송 작업반에 변경 통보 필요',
      done: '이미 한 공정 · 소조립·판넬조립·대조립 완료, 선행의장 진행 중',
    })
    // 줄인 글은 원문에 있던 블록·주체·공정 이름을 빼먹지 않는다
    const { head, done } = notifyLine(text)
    for (const name of ['B31P', '직영·해송 작업반', '소조립', '선행의장 진행 중']) expect(`${head} ${done}`).toContain(name)
    expect(notifyLine('수행 주체 미상 · 통보 대상 확인')).toEqual({ head: '수행 주체 미상 · 통보 대상 확인', done: null })
  })
})
