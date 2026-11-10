// 구성원 표: 이름·아이디 · 역할(고르기) · 상태 · 마지막 로그인 · 동작(비밀번호 초기화 확인 · 사용 중지/다시 사용 ·
// 삭제 확인). 나 자신의 줄은 역할·동작을 바꿀 수 없고 지울 수 없다는 이유 한 줄. 빠른 로그인 고정 계정 줄도 바꿀 수 없어
// 동작 대신 자물쇠와 이유 한 줄(DESIGN.md 12절 — 막는 것은 서버, ripple/auth/quick.py locked·members.py delete_account).
import { KeyRound, Lock, Trash2 } from 'lucide-react'
import type { Account } from '@/api/client'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import { accountState, deleteBlock, formatKstTime, isQuickAccount } from '@/lib/account'
import { ROLE_OPTIONS, ROW_COLUMNS, type StaffRole } from './roles'
import type { MemberRows } from './useMembers'

type Actions = Omit<MemberRows, 'accounts'>

export function MemberTable({ meId, rows }: { meId: string; rows: MemberRows }) {
  const { accounts, ...actions } = rows
  return (
    <div role="table" aria-label="구성원" className="flex flex-col">
      <div
        role="row"
        // 칸 폭(em)은 줄과 같은 글자 크기(text-sm) 기준, 머리글 글자만 작게
        className={`hidden border-b border-border px-2 pb-2 text-sm text-foreground-secondary *:text-xs md:grid md:gap-3 ${ROW_COLUMNS}`}
      >
        <span role="columnheader">이름·아이디</span>
        <span role="columnheader">역할</span>
        <span role="columnheader">상태</span>
        <span role="columnheader">마지막 로그인</span>
        <span role="columnheader" className="sr-only">
          동작
        </span>
      </div>
      {accounts === null && <p className="px-2 py-3 text-sm text-foreground-secondary">불러오는 중…</p>}
      {accounts?.map((account) => (
        <MemberRow
          key={account.login_id}
          account={account}
          self={account.login_id === meId}
          blocked={deleteBlock(account, meId, accounts)}
          {...actions}
        />
      ))}
    </div>
  )
}

/** blocked = 지울 수 없는 이유(lib/account deleteBlock, 지울 수 있으면 null). */
function MemberRow({
  account,
  self,
  blocked,
  busy,
  confirming,
  onConfirming,
  onReset,
  onUpdate,
  onDelete,
}: { account: Account; self: boolean; blocked: string | null } & Actions) {
  const key = account.login_id
  const fixed = isQuickAccount(key)
  const editable = !self && !fixed
  return (
    <div
      role="row"
      data-login={key}
      className={`grid gap-2 border-b border-border px-2 py-3 text-sm md:items-center md:gap-3 ${ROW_COLUMNS}`}
    >
      <span role="cell" className="min-w-0">
        <span className="block truncate text-sm font-medium" title={account.name}>
          {account.name}
          {self && <span className="ml-1 text-xs font-normal text-foreground-secondary">(나)</span>}
        </span>
        <span className="block truncate font-mono text-xs whitespace-nowrap text-foreground-secondary" title={account.login_id}>
          {account.login_id}
        </span>
      </span>
      <span role="cell">
        <NativeSelect
          aria-label={`${account.name} 역할`}
          value={account.role}
          disabled={!editable || busy !== null}
          onChange={(event) => void onUpdate(account, { role: event.target.value as StaffRole })}
        >
          {ROLE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </NativeSelect>
      </span>
      <span role="cell" className={`text-sm ${account.disabled ? 'text-danger' : ''}`}>
        {accountState(account)}
      </span>
      <span role="cell" className="text-sm whitespace-nowrap text-foreground-secondary tabular-nums">
        {formatKstTime(account.last_login_at)}
      </span>
      <span role="cell" className="flex flex-wrap gap-2 md:justify-end">
        {fixed && (
          <span className="flex items-center gap-1.5 text-xs text-foreground-secondary" data-testid="member-locked">
            <Lock className="size-3.5 shrink-0" aria-hidden />
            시연용 고정 계정 — 변경 불가
          </span>
        )}
        {self && !fixed && <Reason>{blocked}</Reason>}
        {editable && (
          <RowActions
            account={account}
            blocked={blocked}
            busy={busy}
            confirming={confirming}
            onConfirming={onConfirming}
            onReset={onReset}
            onUpdate={onUpdate}
            onDelete={onDelete}
          />
        )}
      </span>
    </div>
  )
}

/** 단추 대신 보이는 이유 한 줄(지울 수 없는 줄). */
function Reason({ children }: { children: string | null }) {
  return (
    <span className="text-xs text-foreground-secondary" data-testid="member-undeletable">
      {children}
    </span>
  )
}

/**
 * 바꿀 수 있는 줄의 동작: 비밀번호 초기화 · 사용 중지/다시 사용 · 삭제. 초기화와 삭제는 그 줄에서 한 번 더 묻는다
 * (무엇이 바뀌는지 한 줄 + 왼쪽 '닫기' + 오른쪽 실행). 지울 수 없는 줄(마지막 팀장)은 삭제 단추 대신 이유.
 */
function RowActions({
  account,
  blocked,
  busy,
  confirming,
  onConfirming,
  onReset,
  onUpdate,
  onDelete,
}: { account: Account; blocked: string | null } & Actions) {
  const key = account.login_id
  const asking = confirming?.loginId === key ? confirming.action : null
  if (asking === 'reset') {
    return (
      <ConfirmLine
        what="현재 로그인 해제 · 새 임시 비밀번호 발급"
        busy={busy}
        onClose={() => onConfirming(null)}
        onConfirm={() => void onReset(account)}
      >
        초기화
      </ConfirmLine>
    )
  }
  if (asking === 'delete') {
    return (
      <ConfirmLine
        what="계정·로그인 삭제 · 이 아이디 재사용 불가 · 기록·결재에 남은 이름은 그대로"
        danger
        busy={busy}
        onClose={() => onConfirming(null)}
        onConfirm={() => void onDelete(account)}
        testId="member-delete-confirm"
      >
        삭제
      </ConfirmLine>
    )
  }
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={busy !== null}
        onClick={() => onConfirming({ loginId: key, action: 'reset' })}
      >
        <KeyRound aria-hidden />
        비밀번호 초기화
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={busy !== null}
        onClick={() => void onUpdate(account, { disabled: !account.disabled })}
      >
        {account.disabled ? '다시 사용' : '사용 중지'}
      </Button>
      {blocked ? (
        <Reason>{blocked}</Reason>
      ) : (
        <Button
          variant="outline"
          size="sm"
          disabled={busy !== null}
          onClick={() => onConfirming({ loginId: key, action: 'delete' })}
          aria-label={`${account.name} 계정 삭제`}
        >
          <Trash2 aria-hidden />
          삭제
        </Button>
      )}
    </>
  )
}

/** 그 줄에서 한 번 더 묻기: 무엇이 바뀌는지 한 줄 · 왼쪽 '닫기' · 오른쪽 실행(지우기는 위험 색). */
function ConfirmLine({
  what,
  danger = false,
  busy,
  onClose,
  onConfirm,
  testId,
  children,
}: {
  what: string
  danger?: boolean
  busy: string | null
  onClose: () => void
  onConfirm: () => void
  testId?: string
  children: string
}) {
  return (
    <span className="flex flex-wrap items-center gap-2" data-testid={testId}>
      <span className="text-xs text-foreground-secondary">{what}</span>
      <Button variant="outline" size="sm" onClick={onClose}>
        닫기
      </Button>
      <Button size="sm" variant={danger ? 'destructive' : 'default'} disabled={busy !== null} onClick={onConfirm}>
        {children}
      </Button>
    </span>
  )
}
