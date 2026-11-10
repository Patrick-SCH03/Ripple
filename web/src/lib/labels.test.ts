// 이름표: 계약 1.32.0의 새 값(PE·시운전·사외 협력사·작업반 통보·블록 형상)이 원문 그대로 보이지 않는다.
// 계약 값 전부를 덮는지는 서버 검사(tests/checks/labels.py)가 계약 열거형과 이 파일을 대조한다.
import { describe, expect, it } from 'vitest'
import { NOTIFY_TARGETS, subcontractNote } from './assistant'
import { ACTIVITY_NAMES, BLOCK_SHAPE_NAMES, BLOCK_STAGE_NAMES, SUPPLIER_KIND_NAMES, activityName, attrValue } from './labels'

describe('공정·이정표 이름', () => {
  it('PE·시운전과 바뀐 이름(판넬조립·대조립)', () => {
    expect(activityName('S-001:B31P:pre_erection')).toBe('B31P PE')
    expect(activityName('S-001:sea_trial')).toBe('시운전')
    expect(activityName('S-001:T31C:panel')).toBe('T31C 판넬조립')
    expect(activityName('S-001:T31C:assembly')).toBe('T31C 대조립')
  })

  it('블록 단계는 공정 이름과 같고 진행 순서대로(PE는 선행도장과 탑재 사이)', () => {
    const stages = Object.keys(BLOCK_STAGE_NAMES)
    expect(stages.indexOf('pre_erection')).toBe(stages.indexOf('pre_painting') + 1)
    expect(stages.indexOf('erected')).toBe(stages.indexOf('pre_erection') + 1)
    for (const kind of ['sub_assembly', 'panel', 'assembly', 'pre_outfitting', 'pre_painting', 'pre_erection']) {
      expect(BLOCK_STAGE_NAMES[kind]).toBe(ACTIVITY_NAMES[kind])
    }
  })
})

describe('협력사·작업반·형상', () => {
  it('사외 협력사(단품)·사외 블록 제작·사내 협력사 작업반 통보', () => {
    expect(SUPPLIER_KIND_NAMES.parts).toBe('사외 협력사(단품)')
    expect(SUPPLIER_KIND_NAMES.block).toBe('사외 블록 제작')
    expect(NOTIFY_TARGETS.crew).toBe('사내 협력사 작업반')
  })

  it('블록 형상 세 가지', () => {
    expect(BLOCK_SHAPE_NAMES).toEqual({ flat: '평블록', curved: '곡블록', bow_stern: '선수미 블록' })
  })
})

describe('통보 대상·하도급법 안내(1.32.0)', () => {
  it('발주처는 공급사·사외 협력사, 작업반은 사내 협력사', () => {
    expect(NOTIFY_TARGETS.supplier).toBe('공급사·사외 협력사')
    expect(NOTIFY_TARGETS.crew).toBe('사내 협력사 작업반')
  })

  it('하도급법 안내는 사내·사외 협력사를 함께 적고, 도면 담당만이면 없음', () => {
    for (const target of ['supplier', 'fabricator', 'crew'] as const) {
      const note = subcontractNote([{ target }])
      expect(note).toContain('사내 협력사(작업반)·사외 협력사')
      expect(note).toContain('하도급법')
    }
    expect(subcontractNote([{ target: 'drawing' }])).toBeNull()
  })
})

describe('근거 속성 값', () => {
  it('종류: 부재와 공정 모두 한글(공정 탑재가 erection으로 보이지 않게)', () => {
    expect(attrValue('kind', 'erection')).toBe('탑재')
    expect(attrValue('kind', 'plate')).not.toBe('plate')
    expect(attrValue('kind', 'unknown_kind')).toBe('unknown_kind')
  })
})
