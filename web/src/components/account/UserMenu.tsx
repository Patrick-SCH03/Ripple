// 사용자 메뉴(위 막대 오른쪽 끝): 이름·역할 · 비밀번호 바꾸기 · 구성원 관리·AI 호출 기록(관리자) · 로그아웃.
// 대화상자는 메뉴 항목에서 상태로 연다(닫히면 메뉴 단추로 초점을 돌려줌).
import { Bot, KeyRound, LogOut, ShieldCheck, UserRound, Users } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ROLE_LABEL, can, whoLabel } from '@/lib/account'
import type { LayoutMode } from '@/lib/viewport'
import { useSignedIn } from '@/state/sessionContext'
import { AuditDialog } from './AuditDialog'
import { LlmCallsDialog } from './LlmCallsDialog'
import { MembersDialog } from './MembersDialog'
import { PasswordDialog } from './PasswordDialog'

export function UserMenu({ mode }: { mode: LayoutMode }) {
  const { me, session } = useSignedIn()
  const [open, setOpen] = useState<'password' | 'members' | 'audit' | 'llm' | null>(null)
  const compact = mode === 'phone' || mode === 'tablet'
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" aria-label={`${whoLabel(me)} 메뉴`} data-testid="user-menu">
            <UserRound aria-hidden />
            {!compact && <span className="max-w-28 truncate">{me.name}</span>}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuLabel className="flex flex-col gap-0.5">
            <span>
              {me.name}
              {me.name !== ROLE_LABEL[me.role] && (
                <span className="text-xs font-normal text-foreground-secondary"> · {ROLE_LABEL[me.role]}</span>
              )}
            </span>
            <span className="font-mono text-xs font-normal text-foreground-secondary">{me.login_id}</span>
          </DropdownMenuLabel>
          {me.role === 'demo' && (
            <p className="px-2 pb-1.5 text-xs text-foreground-secondary">
              체험 계정: 합성 데이터만 · 지도 바꾸기·가져오기 불가
            </p>
          )}
          <DropdownMenuSeparator />
          {can(me, 'change_password') && (
            <DropdownMenuItem onSelect={() => setOpen('password')}>
              <KeyRound aria-hidden />
              비밀번호 바꾸기…
            </DropdownMenuItem>
          )}
          {can(me, 'manage_accounts') && (
            <DropdownMenuItem onSelect={() => setOpen('members')} data-testid="open-members">
              <Users aria-hidden />
              구성원 관리…
            </DropdownMenuItem>
          )}
          {can(me, 'manage_accounts') && (
            <DropdownMenuItem onSelect={() => setOpen('llm')} data-testid="open-llm-calls">
              <Bot aria-hidden />
              AI 호출 기록…
            </DropdownMenuItem>
          )}
          {can(me, 'approve') && (
            <DropdownMenuItem onSelect={() => setOpen('audit')} data-testid="open-audit">
              <ShieldCheck aria-hidden />
              감사 로그 확인…
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onSelect={() => void session.logout()} data-testid="logout">
            <LogOut aria-hidden />
            로그아웃
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <PasswordDialog open={open === 'password'} onOpenChange={(next) => setOpen(next ? 'password' : null)} />
      {can(me, 'manage_accounts') && (
        <MembersDialog open={open === 'members'} onOpenChange={(next) => setOpen(next ? 'members' : null)} />
      )}
      {can(me, 'manage_accounts') && (
        <LlmCallsDialog open={open === 'llm'} onOpenChange={(next) => setOpen(next ? 'llm' : null)} />
      )}
      {can(me, 'approve') && (
        <AuditDialog open={open === 'audit'} onOpenChange={(next) => setOpen(next ? 'audit' : null)} />
      )}
    </>
  )
}
