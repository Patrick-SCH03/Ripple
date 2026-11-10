import { describe, expect, it } from 'vitest'
import type { ColumnProposal, MappingProposal, SheetProposal, TemplateSheet } from '@/api/client'
import {
  chooseKey,
  chooseUnit,
  columnStatus,
  factorText,
  field,
  initialChoices,
  pending,
  sheetOrder,
  toMapping,
  unitLabel,
} from './mapping'

const parts: TemplateSheet = {
  key: 'parts',
  name: '부재',
  required: true,
  columns: [
    { key: 'part_id', header: '부재ID', title: '부재ID', required: true, kind: 'text', unit: '', units: [] },
    {
      key: 'thickness_mm',
      header: '두께',
      title: '두께(mm)',
      required: false,
      kind: 'float',
      unit: 'mm',
      units: [
        { unit: 'mm', factor: 1 },
        { unit: 'cm', factor: 10 },
        { unit: 'm', factor: 1000 },
      ],
    },
    { key: 'grade', header: '강종', title: '강종', required: false, kind: 'text', unit: '', units: [] },
  ],
}

function column(position: number, patch: Partial<ColumnProposal>): ColumnProposal {
  return {
    position,
    letter: String.fromCharCode(65 + position),
    header: null,
    samples: [],
    key: null,
    method: 'decided',
    unit_state: 'not_needed',
    auto: false,
    problems: [],
    ...patch,
  }
}

function answer(route: 'auto' | 'confirm' | 'choose' | 'restate', top: string) {
  return {
    question_id: 'q',
    topic: 'excel_column' as const,
    probabilities: { [top]: 0.9, __none__: 0.1 },
    top,
    prediction_set: [top],
    route,
    backend: 'local' as const,
    policy_version: 'column-v1',
  }
}

function sheet(patch: Partial<SheetProposal> = {}): SheetProposal {
  return {
    file_sheet: 'BOM',
    template: 'parts',
    candidates: ['parts'],
    certain: true,
    header_rows: [1],
    reasons: [],
    preview: [],
    columns: [
      column(0, { header: '부재ID', key: 'part_id', method: 'exact', auto: true }),
      column(1, { header: 'THK [m]', key: 'thickness_mm', unit: 'm', unit_state: 'confirmed', factor: 1000, auto: true, answer: answer('auto', 'thickness_mm') }),
      column(2, { header: '강재 등급', key: 'grade', answer: answer('choose', 'grade') }),
      column(3, { header: '비고', key: null, answer: answer('confirm', '__none__') }),
    ],
    missing_required: [],
    unit_notes: [],
    ...patch,
  }
}

function proposal(sheets: SheetProposal[]): MappingProposal {
  return {
    import_id: 'i',
    file: 'a.xlsx',
    version: 1,
    exact: false,
    pending: 2,
    sheets,
    template: [parts],
    policy_version: 'column-v1',
    calibration: '합성 변형 엑셀 기준 보정',
  }
}

describe('열 확인 계산', () => {
  it('제안 값으로 미리 채우고 머리글 단위는 그 항목에서 고를 수 있을 때만', () => {
    const p = proposal([sheet()])
    const choices = initialChoices(p)
    expect(choices.BOM!.columns[1]).toEqual({ key: 'thickness_mm', unit: 'm', ignoreUnit: false, touched: false })
    expect(choices.BOM!.columns[0]).toEqual({ key: 'part_id', unit: null, ignoreUnit: false, touched: false })
  })

  it('상태: 자동 진행은 접고, 고르기는 사람이 고를 때까지 막고, 확인은 미리 채워 위에', () => {
    const p = proposal([sheet()])
    const choices = initialChoices(p)
    const s = p.sheets[0]!
    expect(s.columns.map((c) => columnStatus(s, c, choices.BOM!, p))).toEqual(['auto', 'auto', 'choose', 'confirm'])
    const done = { ...choices.BOM!, columns: { ...choices.BOM!.columns, 2: { key: 'grade', unit: null, ignoreUnit: false, touched: true } } }
    expect(columnStatus(s, s.columns[2]!, done, p)).toBe('done')
  })

  it("'해당 없음'만 남은 판단(덧붙인 비고 열)은 막지 않고 확인, 읽을지 갈리면 고르기", () => {
    const onlyNone = column(4, { header: 'Remark', answer: { ...answer('restate', '__none__'), prediction_set: ['__none__'] } })
    const split = column(5, { header: '확인', answer: { ...answer('choose', '__none__'), prediction_set: ['__none__', 'grade'] } })
    const s = sheet({ columns: [...sheet().columns, onlyNone, split] })
    const p = proposal([s])
    const choices = initialChoices(p)
    expect(columnStatus(s, onlyNone, choices.BOM!, p)).toBe('confirm')
    expect(columnStatus(s, split, choices.BOM!, p)).toBe('choose')
  })

  it('같은 항목에 두 열이면 둘 다 겹침, 단위가 필요한 항목에 단위가 없으면 단위', () => {
    const p = proposal([sheet()])
    const s = p.sheets[0]!
    const base = initialChoices(p).BOM!
    const twin = { ...base, columns: { ...base.columns, 3: { key: 'grade', unit: null, ignoreUnit: false, touched: true } } }
    expect(columnStatus(s, s.columns[2]!, twin, p)).toBe('clash')
    expect(columnStatus(s, s.columns[3]!, twin, p)).toBe('clash')
    const unitless = { ...base, columns: { ...base.columns, 1: { key: 'thickness_mm', unit: null, ignoreUnit: false, touched: true } } }
    expect(columnStatus(s, s.columns[1]!, unitless, p)).toBe('unit')
  })

  it('항목을 바꾸면 머리글 단위를 그 항목에서 고를 수 있을 때만 다시 채움', () => {
    const p = proposal([sheet()])
    const thk = p.sheets[0]!.columns[1]!
    expect(chooseKey(thk, field(p, 'parts', 'grade'))).toEqual({ key: 'grade', unit: null, ignoreUnit: false, touched: true })
    expect(chooseKey(thk, field(p, 'parts', 'thickness_mm'))).toEqual({ key: 'thickness_mm', unit: 'm', ignoreUnit: false, touched: true })
    expect(chooseKey(thk, null)).toEqual({ key: null, unit: null, ignoreUnit: false, touched: true })
  })

  it('남은 일: 확실하지 않은 시트·고르기 열·빠진 필수 항목은 막고, 확인 열은 보고 넘어감', () => {
    const p = proposal([sheet({ certain: false })])
    const choices = initialChoices(p)
    const left = pending(p, choices)
    expect(left.sheets).toEqual(['BOM'])
    expect(left.blocking).toBe(2) // 시트 + 고르기 열
    expect(left.review).toBe(1)
    const noId = { ...choices, BOM: { ...choices.BOM!, columns: { ...choices.BOM!.columns, 0: { key: null, unit: null, ignoreUnit: false, touched: true } } } }
    expect(pending(p, noId).missing.BOM?.map((f) => f.key)).toEqual(['part_id'])
  })

  it('확정 매핑: 서버 계약 모양, 단위 없는 항목은 단위를 싣지 않고, 읽지 않는 시트는 열 없이', () => {
    const p = proposal([sheet(), sheet({ file_sheet: '표지', template: null, header_rows: [], columns: [] })])
    const choices = initialChoices(p)
    choices.BOM!.columns[2] = { key: 'grade', unit: 'mm', ignoreUnit: false, touched: true }
    expect(toMapping(p, choices)).toEqual({
      sheets: [
        {
          file_sheet: 'BOM',
          template: 'parts',
          header_rows: [1],
          columns: [
            { position: 0, key: 'part_id', unit: null, ignore_unit: false },
            { position: 1, key: 'thickness_mm', unit: 'm', ignore_unit: false },
            { position: 2, key: 'grade', unit: null, ignore_unit: false },
            { position: 3, key: null, unit: null, ignore_unit: false },
          ],
        },
        { file_sheet: '표지', header_rows: [], columns: [] },
      ],
    })
  })

  it('앞의 고침은 같은 양식 시트·머리글 행이면 다시 제안받아도 남음', () => {
    const p = proposal([sheet()])
    const choices = initialChoices(p)
    choices.BOM!.columns[2] = { key: 'grade', unit: null, ignoreUnit: false, touched: true }
    expect(initialChoices(p, choices).BOM!.columns[2]!.touched).toBe(true)
    const moved = proposal([sheet({ header_rows: [2] })])
    expect(initialChoices(moved, choices).BOM!.columns[2]!.touched).toBe(false)
  })

  it("단위 없는 항목에 머리글 단위(%)가 있으면 '머리글 단위를 쓰지 않음'을 고를 때까지 막고, 고르면 확정 매핑에 명시", () => {
    const rate = column(4, { header: '강종(%)', key: 'grade', method: 'exact', unit: '%', header_unit: '%', unit_state: 'unresolved' })
    const s = sheet({ columns: [...sheet().columns, rate] })
    const p = proposal([s])
    const choices = initialChoices(p)
    choices.BOM!.columns[2] = { key: null, unit: null, ignoreUnit: false, touched: true } // 같은 항목(강종) 겹침을 피함
    expect(choices.BOM!.columns[4]).toEqual({ key: 'grade', unit: null, ignoreUnit: false, touched: false })
    expect(columnStatus(s, rate, choices.BOM!, p)).toBe('unit')
    expect(pending(p, choices).blocking).toBeGreaterThan(0)
    choices.BOM!.columns[4] = { key: 'grade', unit: null, ignoreUnit: true, touched: true }
    expect(columnStatus(s, rate, choices.BOM!, p)).toBe('done')
    const mapped = toMapping(p, choices).sheets[0]!.columns.find((c) => c.position === 4)
    expect(mapped).toEqual({ position: 4, key: 'grade', unit: null, ignore_unit: true })
  })

  it('머리글 단위와 다른 원본 단위를 고르면 그 자체가 명시(ignore_unit), 같은 단위면 아님', () => {
    const thk = sheet().columns[1]!
    const withHeader = { ...thk, header_unit: 'm' }
    const base = { key: 'thickness_mm', unit: 'm', ignoreUnit: false, touched: false }
    expect(chooseUnit(withHeader, base, 'mm')).toEqual({ key: 'thickness_mm', unit: 'mm', ignoreUnit: true, touched: true })
    expect(chooseUnit(withHeader, base, 'm')).toEqual({ key: 'thickness_mm', unit: 'm', ignoreUnit: false, touched: true })
    expect(chooseUnit(thk, base, 'cm').ignoreUnit).toBe(false) // 머리글에 단위가 없으면 명시할 것도 없음
  })

  it('단위 이름과 배율 표기', () => {
    const thk = parts.columns[1]!
    expect(unitLabel({ unit: 'mm', factor: 1 }, thk)).toBe('mm')
    expect(unitLabel({ unit: 'm', factor: 1000 }, thk)).toBe('m → mm ×1,000')
    expect(unitLabel({ unit: 'ton', factor: 1 }, { ...thk, unit: 't' })).toBe('ton (= t)')
    expect(factorText(0.001)).toBe('0.001')
    expect(factorText(1000000)).toBe('1,000,000')
  })

  it('시트 순서: 사람이 정할 시트 → 막는 열 → 확인 열 → 나머지', () => {
    const quiet = sheet({ file_sheet: '조용', columns: [column(0, { key: 'part_id', method: 'exact', auto: true })] })
    const unsure = sheet({ file_sheet: '모름', certain: false, columns: [] })
    const p = proposal([quiet, sheet(), unsure])
    expect(sheetOrder(p, initialChoices(p)).map((s) => s.file_sheet)).toEqual(['모름', 'BOM', '조용'])
  })
})
