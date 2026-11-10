// 구성원 관리(팀장, docs/operations.md(서비스) 2절): 계정 만들기(임시 비밀번호는 이 창에서 한 번만 보임) · 비밀번호 초기화 ·
// 사용 중지/다시 사용 · 역할 바꾸기(팀장 · 담당자) · 삭제(지운 뒤 안내 한 줄). 마지막 팀장을 끄거나 내리거나 지우는 일은
// 서버가 막고 그 문구를 그대로 보인다.
// 상태와 동작은 members/useMembers, 추가 줄·표·임시 비밀번호 상자는 members/의 부품.
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useReturnFocus } from '@/lib/focus'
import { useSignedIn } from '@/state/sessionContext'
import { IssuedPassword } from './members/IssuedPassword'
import { MemberForm } from './members/MemberForm'
import { MemberTable } from './members/MemberTable'
import { useMembers } from './members/useMembers'

export function MembersDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { me } = useSignedIn()
  const returnFocus = useReturnFocus(open)
  const { error, notice, change, password, form, table } = useMembers(open, onOpenChange)

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent
        className="max-h-[92vh] gap-4 overflow-y-auto sm:max-w-4xl"
        onCloseAutoFocus={returnFocus}
        data-testid="members-dialog"
      >
        <DialogHeader>
          <DialogTitle>구성원 관리</DialogTitle>
          <DialogDescription>
            팀원 계정 만들기 · 임시 비밀번호 전달 → 첫 로그인 때 본인 비밀번호로 변경
          </DialogDescription>
        </DialogHeader>

        {error && (
          <p role="alert" className="rounded-sm border border-danger/50 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="rounded-sm border border-border px-3 py-2 text-sm" data-testid="members-notice">
            {notice}
          </p>
        )}
        {password && <IssuedPassword {...password} />}

        <MemberForm form={form} />

        <MemberTable meId={me.login_id} rows={table} />

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
