// 확인표 항목 '고침': 대상 후보 체크(후보 이름 · 부재 ID, 여럿 고르기) + 수치 입력(mm·수량). 나머지는 비서로 넘긴다.
// 고칠 칸(대상 칸 · 수치 칸)은 항목의 칸 정의에서 고른다(lib/intake).
import { useId } from 'react'
import type { ChangeDraft, IntakeItem } from '@/api/client'
import { Input } from '@/components/ui/input'
import { fillText, numberSlots, targetSlot, type RowState } from '@/lib/intake'
import { cn } from '@/lib/utils'

const UNIT: Record<string, string> = { millimeter: 'mm', quantity: '규격 단위' }

interface Props {
  item: IntakeItem
  /** 항목의 초안(읽지 못한 항목은 고칠 수 없어 카드가 이 칸을 그리지 않는다). */
  draft: ChangeDraft
  row: RowState
  onRow: (row: RowState) => void
  /** 좁은 화면: 후보 줄·입력칸이 터치 높이(현장 태블릿 44px). */
  compact: boolean
  busy: boolean
}

export function ItemEditForm({ item, draft, row, onRow, compact, busy }: Props) {
  const ids = useId()
  const target = targetSlot(item)
  const numbers = numberSlots(item)
  const height = compact ? 'h-11' : 'h-9'
  return (
    <div className="grid gap-2 rounded-md bg-muted/50 p-2 sm:grid-cols-2" data-testid="intake-edit">
      {target && (
        <fieldset className="space-y-1 text-sm" disabled={busy}>
          <legend className="text-foreground-secondary">
            {target.label}
            <span className="ml-1 text-xs">(지금 {fillText(draft.slots?.[target.name]) ?? '없음'} · 고르면 변경)</span>
          </legend>
          {item.candidates.length > 0 ? (
            item.candidates.map((candidate) => {
              const checked = row.partIds?.includes(candidate.part_id) ?? false
              return (
                <label key={candidate.part_id} className={cn('flex items-center gap-2', compact && 'min-h-11')}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const rest = (row.partIds ?? []).filter((id) => id !== candidate.part_id)
                      const next = checked ? rest : [...rest, candidate.part_id]
                      onRow({ ...row, partIds: next.length > 0 ? next : null })
                    }}
                    className="size-4"
                  />
                  <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <span>{candidate.label}</span>
                    <span className="font-mono text-sm whitespace-nowrap text-foreground-secondary">
                      {candidate.part_id}
                    </span>
                  </span>
                </label>
              )
            })
          ) : (
            <p className="text-foreground-secondary">고를 후보 없음 — 대상이 다르면 비서로 넘기기</p>
          )}
        </fieldset>
      )}
      {numbers.map((slot) => (
        <label key={slot.name} className="space-y-1 text-sm" htmlFor={`${ids}-${slot.name}`}>
          <span className="text-foreground-secondary">
            {slot.label}({UNIT[slot.kind] ?? ''})
          </span>
          <Input
            id={`${ids}-${slot.name}`}
            inputMode="decimal"
            value={row.values[slot.name] ?? ''}
            placeholder={fillText(draft.slots?.[slot.name]) ?? '숫자'}
            disabled={busy}
            onChange={(event) => onRow({ ...row, values: { ...row.values, [slot.name]: event.target.value } })}
            className={cn('rounded-sm tabular-nums', height)}
          />
        </label>
      ))}
      {!target && numbers.length === 0 && (
        <p className="text-sm text-foreground-secondary">표에서 고칠 칸 없음 — 비서로 넘기기</p>
      )}
    </div>
  )
}
