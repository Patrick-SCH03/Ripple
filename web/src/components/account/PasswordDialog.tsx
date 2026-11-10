// 비밀번호 바꾸기(사용자 메뉴). 바꾸면 다른 기기의 로그인은 끊기고 이 화면은 새 세션으로 이어진다.
import { useState } from 'react'
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
import { PasswordForm } from '@/pages/login/PasswordForm'
import { useSignedIn } from '@/state/sessionContext'

export function PasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { me, session } = useSignedIn()
  const returnFocus = useReturnFocus(open)
  const [done, setDone] = useState(false)
  const change = (next: boolean) => {
    if (next) setDone(false)
    onOpenChange(next)
  }
  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent className="sm:max-w-md" onCloseAutoFocus={returnFocus} data-testid="password-dialog">
        <DialogHeader>
          <DialogTitle>비밀번호 바꾸기</DialogTitle>
          <DialogDescription>변경 시 다른 기기 로그인 해제 · 이 화면은 유지</DialogDescription>
        </DialogHeader>
        {done ? (
          <>
            <p role="status" className="rounded-sm border border-success/50 px-3 py-2 text-sm text-success">
              비밀번호 변경됨
            </p>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">닫기</Button>
              </DialogClose>
            </DialogFooter>
          </>
        ) : (
          <PasswordForm
            key={String(open)}
            session={session}
            loginId={me.login_id}
            onDone={() => setDone(true)}
            actions={({ busy }) => (
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="outline">
                    닫기
                  </Button>
                </DialogClose>
                <Button type="submit" disabled={busy}>
                  {busy ? '바꾸는 중…' : '바꾸기'}
                </Button>
              </DialogFooter>
            )}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
