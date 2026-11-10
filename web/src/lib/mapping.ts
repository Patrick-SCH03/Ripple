// 엑셀 열 확인(docs/input.md(엑셀 양식) 4절): 서버 제안(MappingProposal)과 사람이 고친 것을 합쳐 확정 매핑을 만들고,
// 읽기 전에 막아야 할 것(같은 항목 두 열·단위 미해결·필수 항목 없음·골라야 하는 열)과 확인할 것을 센다. 화면 밖 계산만.
//
// - 시트 상태(양식 시트·읽지 않음)와 머리글 행은 서버가 다시 제안한다(덮어쓰기). 확실하지 않은 시트는 사람이 정할 때까지
//   막는다(같은 값으로 '맞음'을 눌러도 서버가 사람이 정한 것으로 받아 확실해진다).
// - 열은 화면에서만 고친다: 자동 진행 열은 미리 채워 접고, 확인 열은 미리 채워 위에 보이고, 고르기·다시 묻기 열은
//   사람이 고를 때까지 막는다.
// - 머리글에 단위가 적혀 있으면 그와 다른 원본 단위(단위 없는 항목이면 '단위 없음')는 사람이 '머리글 단위를 쓰지
//   않음'을 명시해야(ignore_unit) 읽는다 — 서버도 같은 규칙으로 거절한다(% 일률 100배 오독 방지).
import type {
  ColumnProposal,
  ConfirmedMapping,
  MappingProposal,
  SheetProposal,
  TemplateField,
  TemplateSheet,
  UnitOption,
} from '@/api/client'

export interface ColumnChoice {
  key: string | null
  unit: string | null
  /** 머리글에 적힌 단위를 쓰지 않음(사람이 명시) */
  ignoreUnit: boolean
  /** 사람이 고르거나 바꿈 */
  touched: boolean
}

export interface SheetChoice {
  template: string | null
  headerRows: number[]
  columns: Record<number, ColumnChoice>
}

export type Choices = Record<string, SheetChoice>

/** 열 상태: 자동 진행 · 확인(미리 채움) · 고르기(사람이 골라야 함) · 단위(원본 단위를 골라야 함) · 겹침(같은 항목 두 열) · 고침(사람이 정함). */
export type ColumnStatus = 'auto' | 'confirm' | 'choose' | 'unit' | 'clash' | 'done'

export const BLOCKING: ReadonlySet<ColumnStatus> = new Set(['choose', 'unit', 'clash'])

/** 판단 계층의 '해당 없음' 선택지 ID(서버 NONE_OPTION). */
export const NONE = '__none__'

function sameRows(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i])
}

/** 제안으로 고른 값을 채운다. 앞의 고침(previous)은 같은 양식 시트·머리글 행인 시트의 같은 열이면 그대로 둔다. */
export function initialChoices(proposal: MappingProposal, previous: Choices = {}): Choices {
  const choices: Choices = {}
  for (const sheet of proposal.sheets) {
    const before = previous[sheet.file_sheet]
    const keep = before && before.template === sheet.template && sameRows(before.headerRows, sheet.header_rows)
    const columns: Record<number, ColumnChoice> = {}
    for (const column of sheet.columns) {
      const old = keep ? before.columns[column.position] : undefined
      columns[column.position] =
        old && old.touched
          ? old
          : {
              key: column.key ?? null,
              unit: proposedUnit(column, field(proposal, sheet.template, column.key ?? null)),
              ignoreUnit: false,
              touched: false,
            }
    }
    choices[sheet.file_sheet] = { template: sheet.template ?? null, headerRows: [...sheet.header_rows], columns }
  }
  return choices
}

/** 양식 시트의 열 정의. */
export function field(proposal: MappingProposal, template: string | null | undefined, key: string | null): TemplateField | null {
  if (!template || !key) return null
  return templateOf(proposal, template)?.columns.find((f) => f.key === key) ?? null
}

export function templateOf(proposal: MappingProposal, template: string | null | undefined): TemplateSheet | null {
  return proposal.template.find((t) => t.key === template) ?? null
}

/** 그 항목으로 읽을 때 미리 채울 원본 단위: 제안 단위(머리글 단위·지정 양식 관례)가 그 항목에서 고를 수 있는 단위면 그것. */
function proposedUnit(column: ColumnProposal, target: TemplateField | null): string | null {
  if (!target || !target.unit) return null
  const unit = column.unit ?? null
  return unit && target.units.some((u) => u.unit === unit) ? unit : null
}

/** 사람이 항목을 바꾼 열의 새 선택. 단위는 머리글 단위가 그 항목에서 고를 수 있을 때만 미리 채운다. */
export function chooseKey(column: ColumnProposal, target: TemplateField | null): ColumnChoice {
  return { key: target?.key ?? null, unit: proposedUnit(column, target), ignoreUnit: false, touched: true }
}

/** 원본 단위를 고른 선택. 머리글에 적힌 단위와 다른 단위를 고르면 그 자체가 '머리글 단위를 쓰지 않음'의 명시다. */
export function chooseUnit(column: ColumnProposal, choice: ColumnChoice, unit: string | null): ColumnChoice {
  const written = column.header_unit ?? null
  return { ...choice, unit, ignoreUnit: written !== null && unit !== null && unit !== written, touched: true }
}

/** 단위 없는 항목인데 머리글에 단위가 적힌 열: 사람이 '머리글 단위를 쓰지 않고 그대로 읽기'를 골라야 읽는다. */
export function headerUnitConflict(column: ColumnProposal, target: TemplateField | null): boolean {
  return !!target && !target.unit && !!column.header_unit
}

export function columnStatus(sheet: SheetProposal, column: ColumnProposal, choices: SheetChoice, proposal: MappingProposal): ColumnStatus {
  const choice = choices.columns[column.position]
  if (!choice) return 'auto'
  if (choice.key) {
    const clash = Object.entries(choices.columns).some(([pos, other]) => Number(pos) !== column.position && other.key === choice.key)
    if (clash) return 'clash'
    const target = field(proposal, sheet.template, choice.key)
    if (target?.unit && !choice.unit) return 'unit'
    if (headerUnitConflict(column, target) && !choice.ignoreUnit) return 'unit'
  }
  if (choice.touched) return 'done'
  if (column.auto) return 'auto'
  const answer = column.answer
  if (!answer) return 'confirm'
  // '해당 없음'만 남은 판단(덧붙인 비고·순번 열 등)은 읽지 않음을 미리 채워 확인만 받는다 — 해당 없음은 자동 진행하지
  // 않지만, 읽지 않은 열은 리포트에 남아 잘못 빼도 조용히 지나가지 않는다. 읽을지 말지·어느 항목인지 갈리면 고른다
  const onlyNone = answer.top === NONE && answer.prediction_set.every((key) => key === NONE)
  if ((answer.route === 'choose' || answer.route === 'restate') && !onlyNone) return 'choose'
  return 'confirm'
}

export interface Pending {
  /** 읽기 전에 정해야 하는 것(이게 있으면 '이대로 읽기'를 막는다) */
  blocking: number
  /** 미리 채운 값을 보고 넘어가도 되는 것 */
  review: number
  /** 필수 항목인데 고른 열이 없는 양식 열(시트별) */
  missing: Record<string, TemplateField[]>
  /** 사람이 정해야 하는 시트(확실하지 않음) */
  sheets: string[]
}

export function pending(proposal: MappingProposal, choices: Choices): Pending {
  const result: Pending = { blocking: 0, review: 0, missing: {}, sheets: [] }
  for (const sheet of proposal.sheets) {
    const choice = choices[sheet.file_sheet]
    if (!choice) continue
    if (!sheet.certain) {
      result.sheets.push(sheet.file_sheet)
      result.blocking += 1
    }
    if (!sheet.template) continue
    for (const column of sheet.columns) {
      const status = columnStatus(sheet, column, choice, proposal)
      if (BLOCKING.has(status)) result.blocking += 1
      else if (status === 'confirm') result.review += 1
    }
    const chosen = new Set(Object.values(choice.columns).map((c) => c.key))
    const missing = (templateOf(proposal, sheet.template)?.columns ?? []).filter((f) => f.required && !chosen.has(f.key))
    if (missing.length) {
      result.missing[sheet.file_sheet] = missing
      result.blocking += missing.length
    }
  }
  return result
}

/** 확정 매핑(서버 계약 그대로). 단위 없는 항목은 원본 단위를 싣지 않는다. */
export function toMapping(proposal: MappingProposal, choices: Choices): ConfirmedMapping {
  return {
    sheets: proposal.sheets.map((sheet) => {
      const choice = choices[sheet.file_sheet]
      if (!sheet.template || !sheet.header_rows.length || !choice) return { file_sheet: sheet.file_sheet, header_rows: [], columns: [] }
      return {
        file_sheet: sheet.file_sheet,
        template: sheet.template,
        header_rows: [...sheet.header_rows],
        columns: sheet.columns.map((column) => {
          const picked = choice.columns[column.position] ?? { key: null, unit: null, ignoreUnit: false, touched: false }
          const target = field(proposal, sheet.template, picked.key)
          return {
            position: column.position,
            key: picked.key,
            unit: target?.unit ? picked.unit : null,
            ignore_unit: !!picked.key && !!column.header_unit && picked.ignoreUnit,
          }
        }),
      }
    }),
  }
}

/** 원본 단위 고르기 이름: 양식 단위와 같으면 양식 표기('DN'), 배율 1인 다른 표기면 'ton (= t)', 다르면 'm → mm ×1,000'. */
export function unitLabel(option: UnitOption, target: TemplateField): string {
  if (option.unit.toLowerCase() === target.unit.toLowerCase()) return target.unit
  if (option.factor === 1) return `${option.unit} (= ${target.unit})`
  return `${option.unit} → ${target.unit} ×${factorText(option.factor)}`
}

export function factorText(factor: number): string {
  if (Number.isInteger(factor)) return factor.toLocaleString('en-US')
  return String(Number(factor.toPrecision(6)))
}

/** 시트를 확인할 것이 많은 순서로(막는 것 → 확인할 것 → 나머지), 같으면 원래 순서. */
export function sheetOrder(proposal: MappingProposal, choices: Choices): SheetProposal[] {
  const weight = (sheet: SheetProposal): number => {
    const choice = choices[sheet.file_sheet]
    if (!sheet.certain) return 0
    if (!choice || !sheet.template) return 3
    const statuses = sheet.columns.map((c) => columnStatus(sheet, c, choice, proposal))
    if (statuses.some((s) => BLOCKING.has(s))) return 1
    if (statuses.some((s) => s === 'confirm')) return 2
    return 3
  }
  return proposal.sheets
    .map((sheet, index) => ({ sheet, index, w: weight(sheet) }))
    .sort((a, b) => a.w - b.w || a.index - b.index)
    .map((x) => x.sheet)
}
