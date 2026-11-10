// 머리글 행 고르기: 앞 행 미리보기에서 행 하나(또는 아래 행까지 두 줄)를 머리글로 고른다.
import { useState } from 'react'
import type { SheetProposal } from '@/api/client'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function HeaderPicker({ sheet, busy, onPick }: { sheet: SheetProposal; busy: boolean; onPick: (rows: number[]) => void }) {
  const [row, setRow] = useState<number | null>(sheet.header_rows[0] ?? null)
  const [two, setTwo] = useState(sheet.header_rows.length === 2)
  const numbers = new Set(sheet.preview.map((r) => r.row))
  const twoPossible = row !== null && numbers.has(row + 1)
  return (
    <fieldset className="rounded-md border border-border p-2" aria-label="머리글 행 고르기">
      <legend className="px-1 text-sm text-foreground-secondary">머리글 행 선택(앞 {sheet.preview.length}행)</legend>
      <div className="max-h-60 overflow-auto">
        <table className="w-full border-collapse text-xs">
          <tbody>
            {sheet.preview.map((preview) => (
              <tr key={preview.row} className={cn(row === preview.row || (two && row !== null && preview.row === row + 1) ? 'bg-primary/8' : '')}>
                <td className="w-16 py-1 pr-2 align-top">
                  <label className="inline-flex items-center gap-1">
                    <input type="radio" name={`header-${sheet.file_sheet}`} checked={row === preview.row} onChange={() => setRow(preview.row)} />
                    {preview.row}행
                  </label>
                </td>
                {preview.cells.slice(0, 8).map((cell, i) => (
                  <td key={i} className="max-w-28 truncate py-1 pr-2 text-foreground-secondary">
                    {cell ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={two && twoPossible} disabled={!twoPossible} onChange={(event) => setTwo(event.target.checked)} />
          아래 행까지 두 줄 머리글
        </label>
        <Button size="sm" disabled={busy || row === null} onClick={() => row !== null && onPick(two && twoPossible ? [row, row + 1] : [row])}>
          이 행을 머리글로
        </Button>
      </div>
    </fieldset>
  )
}
