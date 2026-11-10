// 열 한 줄: 열 문자 · 파일 머리글 · 예시 값 → 양식 항목 고르기(후보 먼저) · 원본 단위 · 상태 배지.
// 넓으면 한 줄 네 칸(칸 폭 고정), 좁으면 위아래.
import type { ColumnProposal, MappingProposal, SheetProposal, TemplateField } from '@/api/client'
import { NativeSelect } from '@/components/ui/native-select'
import {
  NONE,
  chooseKey,
  chooseUnit,
  field,
  headerUnitConflict,
  templateOf,
  unitLabel,
  type ColumnChoice,
  type ColumnStatus,
} from '@/lib/mapping'
import { NONE_VALUE, PICK_VALUE } from './options'
import { StatusBadge } from './StatusBadge'

export function ColumnRow({
  proposal,
  sheet,
  column,
  choice,
  status,
  busy,
  onChange,
}: {
  proposal: MappingProposal
  sheet: SheetProposal
  column: ColumnProposal
  choice: ColumnChoice
  status: ColumnStatus
  /** 다시 제안·읽기 중에는 고칠 수 없다(늦게 온 응답이 고친 것을 되돌리지 않게) */
  busy: boolean
  onChange: (choice: ColumnChoice) => void
}) {
  const template = templateOf(proposal, sheet.template)
  const target = field(proposal, sheet.template, choice.key)
  const candidates =
    column.answer && (column.answer.route === 'choose' || column.answer.route === 'restate')
      ? column.answer.prediction_set.filter((key) => key !== NONE)
      : []
  const others = (template?.columns ?? []).filter((f) => !candidates.includes(f.key))
  const name = column.header ?? `${column.letter}열(머리글 없음)`
  return (
    <li
      className="grid grid-cols-1 gap-2 px-3 py-2 text-sm sm:grid-cols-[minmax(0,1fr)_13rem_11rem_9.5rem] sm:items-center"
      data-testid="review-column"
      data-letter={column.letter}
      data-status={status}
    >
      <div className="min-w-0">
        <p className="font-medium break-keep">
          <span className="mr-1.5 font-mono text-xs text-foreground-secondary">{column.letter}</span>
          {name}
        </p>
        {column.samples.length > 0 && (
          <p className="truncate font-mono text-xs text-foreground-secondary">{column.samples.join(' · ')}</p>
        )}
      </div>
      <NativeSelect
        aria-label={`${column.letter}열 '${name}'의 양식 항목`}
        value={status === 'choose' ? PICK_VALUE : (choice.key ?? NONE_VALUE)}
        aria-invalid={status === 'choose' || status === 'clash'}
        disabled={busy}
        onChange={(event) => onChange(chooseKey(column, field(proposal, sheet.template, event.target.value || null)))}
      >
        {status === 'choose' && (
          <option value={PICK_VALUE} disabled>
            선택 필요
          </option>
        )}
        <option value={NONE_VALUE}>해당 없음(읽지 않음)</option>
        {candidates.length > 0 && (
          <optgroup label="후보">
            {candidates.map((key) => {
              const f = field(proposal, sheet.template, key)
              return f ? <FieldOption key={key} field={f} /> : null
            })}
          </optgroup>
        )}
        <optgroup label={candidates.length ? '그 밖의 항목' : '양식 항목'}>
          {others.map((f) => (
            <FieldOption key={f.key} field={f} />
          ))}
        </optgroup>
      </NativeSelect>
      {target?.unit ? (
        <NativeSelect
          aria-label={`${column.letter}열 '${name}'의 원본 단위`}
          value={choice.unit ?? NONE_VALUE}
          aria-invalid={status === 'unit'}
          disabled={busy}
          onChange={(event) => onChange(chooseUnit(column, choice, event.target.value || null))}
        >
          <option value={NONE_VALUE} disabled>
            원본 단위 고르기
          </option>
          {target.units.map((u) => (
            <option key={u.unit} value={u.unit}>
              {unitLabel(u, target)}
            </option>
          ))}
        </NativeSelect>
      ) : headerUnitConflict(column, target) ? (
        <label className="inline-flex items-start gap-1.5 text-xs">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={choice.ignoreUnit}
            disabled={busy}
            onChange={(event) => onChange({ ...choice, ignoreUnit: event.target.checked, touched: true })}
          />
          <span>
            머리글 단위({column.header_unit})를 쓰지 않고 값 그대로 읽기
            <span className="block text-foreground-secondary">값이 그 단위로 적혔으면 원본 수정</span>
          </span>
        </label>
      ) : (
        <span className="text-xs text-foreground-secondary">단위 없음</span>
      )}
      <StatusBadge
        status={status}
        label={status === 'unit' && !target?.unit ? '머리글 단위 확인 필요' : undefined}
      />
    </li>
  )
}

function FieldOption({ field: f }: { field: TemplateField }) {
  return (
    <option value={f.key}>
      {f.title}
      {f.required ? ' (필수)' : ''}
    </option>
  )
}
