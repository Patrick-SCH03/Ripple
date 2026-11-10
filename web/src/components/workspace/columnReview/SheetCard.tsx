// 시트 카드 하나: 양식 시트 고르기(읽지 않음 포함) · 확실하지 않으면 이유와 확인 단추 · 머리글 행과 '머리글 행 바꾸기' ·
// 열 줄(자동으로 맞춘 열은 접어 'n개 보기') · 빠진 필수 항목.
import { useState } from 'react'
import type { MappingProposal, SheetProposal, TemplateField } from '@/api/client'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import { BLOCKING, columnStatus, templateOf, type ColumnChoice, type ColumnStatus, type SheetChoice } from '@/lib/mapping'
import { ColumnRow } from './ColumnRow'
import { HeaderPicker } from './HeaderPicker'
import { NONE_VALUE } from './options'
import { StatusBadge } from './StatusBadge'

export function SheetCard({
  proposal,
  sheet,
  choice,
  missing,
  busy,
  onColumn,
  onSheet,
}: {
  proposal: MappingProposal
  sheet: SheetProposal
  choice: SheetChoice
  missing: TemplateField[]
  busy: boolean
  onColumn: (sheet: string, position: number, choice: ColumnChoice) => void
  onSheet: (sheet: string, template: string | null, headerRows: number[] | null) => void
}) {
  const [picking, setPicking] = useState(false)
  const [showAuto, setShowAuto] = useState(false)
  const template = templateOf(proposal, sheet.template)
  const statuses = new Map(sheet.columns.map((c) => [c.position, columnStatus(sheet, c, choice, proposal)]))
  const rank = (s: ColumnStatus) => (BLOCKING.has(s) ? 0 : s === 'confirm' ? 1 : s === 'done' ? 2 : 3)
  const columns = [...sheet.columns].sort(
    (a, b) => rank(statuses.get(a.position)!) - rank(statuses.get(b.position)!) || a.position - b.position,
  )
  const hidden = columns.filter((c) => statuses.get(c.position) === 'auto')
  const shown = showAuto ? columns : columns.filter((c) => statuses.get(c.position) !== 'auto')
  const rows = sheet.header_rows
  return (
    <section
      aria-label={`'${sheet.file_sheet}' 시트`}
      data-testid="review-sheet"
      data-sheet={sheet.file_sheet}
      className="rounded-md border border-border"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <h3 className="font-semibold">‘{sheet.file_sheet}’ 시트</h3>
        <span aria-hidden className="text-foreground-secondary">
          →
        </span>
        <NativeSelect
          aria-label={`'${sheet.file_sheet}' 시트를 읽을 양식 시트`}
          className="w-auto min-w-36"
          value={sheet.template ?? NONE_VALUE}
          disabled={busy}
          onChange={(event) => onSheet(sheet.file_sheet, event.target.value || null, null)}
        >
          <option value={NONE_VALUE}>읽지 않음</option>
          {proposal.template.map((t) => (
            <option key={t.key} value={t.key}>
              {t.name}
              {t.required ? ' (필수 시트)' : ''}
            </option>
          ))}
        </NativeSelect>
        {sheet.certain ? null : <StatusBadge status="choose" label="시트 확인 필요" />}
      </div>
      <div className="space-y-2 px-3 py-2">
        {!sheet.template && sheet.certain && <p className="text-sm text-foreground-secondary">읽지 않는 시트</p>}
        {sheet.template && sheet.unit_notes.length > 0 && (
          <p className="text-sm text-warning" data-testid="unit-notes">
            제목·메모 행에 단위 표기 있음({sheet.unit_notes.map((note) => `'${note}'`).join(', ')}). 머리글에 단위가
            없는 열은 양식 단위로 짐작하지 않음 · 원본 단위 선택
          </p>
        )}
        {!sheet.certain && (
          <div className="space-y-2">
            <ul className="list-disc pl-5 text-sm text-foreground-secondary">
              {sheet.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {/* 단추는 이유 아래 따로 한 줄(이유 글 줄바꿈에 따라 자리가 움직이지 않게) */}
            {sheet.template && rows.length > 0 && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onSheet(sheet.file_sheet, sheet.template ?? null, [...rows])}>
                이 양식 시트·머리글 맞음
              </Button>
            )}
            {!sheet.template && (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onSheet(sheet.file_sheet, null, null)}>
                읽지 않음으로 확정
              </Button>
            )}
          </div>
        )}
        {template && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-foreground-secondary">
              머리글{' '}
              {rows.length === 2 ? `${rows[0]}~${rows[1]}행(두 줄)` : rows.length === 1 ? `${rows[0]}행` : '없음'}
            </span>
            <Button size="sm" variant="ghost" onClick={() => setPicking((v) => !v)} aria-expanded={picking}>
              머리글 행 바꾸기
            </Button>
          </div>
        )}
        {template && picking && (
          <HeaderPicker
            sheet={sheet}
            busy={busy}
            onPick={(picked) => {
              setPicking(false)
              onSheet(sheet.file_sheet, sheet.template ?? null, picked)
            }}
          />
        )}
        {template && (
          <ul className="divide-y divide-border rounded-md border border-border" aria-label={`'${sheet.file_sheet}' 시트의 열`}>
            {shown.map((column) => (
              <ColumnRow
                key={column.position}
                proposal={proposal}
                sheet={sheet}
                column={column}
                choice={choice.columns[column.position] ?? { key: null, unit: null, ignoreUnit: false, touched: false }}
                status={statuses.get(column.position)!}
                busy={busy}
                onChange={(next) => onColumn(sheet.file_sheet, column.position, next)}
              />
            ))}
            {hidden.length > 0 && (
              <li className="px-3 py-1.5">
                <Button size="sm" variant="ghost" onClick={() => setShowAuto((v) => !v)} aria-expanded={showAuto}>
                  {showAuto ? '자동으로 맞춘 열 접기' : `자동으로 맞춘 열 ${hidden.length}개 보기`}
                </Button>
              </li>
            )}
          </ul>
        )}
        {missing.length > 0 && (
          <p role="alert" className="text-sm text-danger">
            필수 항목 {missing.map((f) => `‘${f.title}’`).join(', ')}을(를) 고른 열 없음 · 그 값이 든 열의 양식 항목
            선택
          </p>
        )}
      </div>
    </section>
  )
}
