// 구성원 추가 줄: 아이디(영문 소문자·숫자) · 이름 · 역할 → '구성원 추가'.
import { UserPlus } from 'lucide-react'
import { useId } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { NAME_MAX } from '@/lib/account'
import { ROLE_OPTIONS, type StaffRole } from './roles'
import type { MemberDraftForm } from './useMembers'

export function MemberForm({ form }: { form: MemberDraftForm }) {
  const { draft, edit, busy, submit } = form
  // 칸마다 라벨과 잇는 ID
  const ids = { id: useId(), name: useId(), role: useId() }
  return (
    <form
      className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-[1fr_1fr_7.5rem_auto] sm:items-end"
      onSubmit={submit}
      noValidate
    >
      <div className="flex flex-col gap-1">
        <label htmlFor={ids.id} className="text-xs text-foreground-secondary">
          아이디(영문 소문자·숫자)
        </label>
        <Input
          id={ids.id}
          value={draft.loginId}
          autoCapitalize="none"
          spellCheck={false}
          onChange={(event) => edit({ loginId: event.target.value })}
          data-testid="member-id"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={ids.name} className="text-xs text-foreground-secondary">
          이름
        </label>
        <Input
          id={ids.name}
          value={draft.name}
          maxLength={NAME_MAX}
          onChange={(event) => edit({ name: event.target.value })}
          data-testid="member-name"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={ids.role} className="text-xs text-foreground-secondary">
          역할
        </label>
        <NativeSelect
          id={ids.role}
          value={draft.role}
          onChange={(event) => edit({ role: event.target.value as StaffRole })}
        >
          {ROLE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </NativeSelect>
      </div>
      <Button type="submit" disabled={busy !== null} data-testid="member-add">
        <UserPlus aria-hidden />
        {busy === 'add' ? '만드는 중…' : '구성원 추가'}
      </Button>
    </form>
  )
}
