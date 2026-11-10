// 감사 로그 확인(관리자 사용자 메뉴, docs/records.md(기록·결재) 6절): 감사 사슬 + 참조 무결성(기록 본문 해시·개정 연결·투영 = 재생).
// 열 때마다 서버가 처음부터 다시 검증한다(본문을 열 때 새로 만들어 이전 결과가 남지 않는다). 정상이면 줄 수·기록 수,
// 아니면 처음 어긋난 줄과 이유.
import { api } from '@/api/client'
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
import { useFetched } from '@/state/useFetched'

export function AuditDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const returnFocus = useReturnFocus(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" onCloseAutoFocus={returnFocus} data-testid="audit-dialog">
        <DialogHeader>
          <DialogTitle>감사 로그 확인</DialogTitle>
          <DialogDescription>
            기록·검토·결정 감사 줄의 연속성과 기록 내용 변조 여부를 서버가 다시 확인
          </DialogDescription>
        </DialogHeader>
        {open && <AuditResult />}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const verify = () => api.verifyAudit()

function AuditResult() {
  const { data: check, error } = useFetched(verify)
  return (
    <div role="status" aria-live="polite" className="text-sm">
      {error ? (
        <p className="rounded-sm border border-danger/40 px-3 py-2 text-danger">{error}</p>
      ) : !check ? (
        <p className="text-foreground-secondary">확인하는 중…</p>
      ) : check.ok ? (
        <p className="rounded-sm border border-success/50 px-3 py-2 text-success" data-testid="audit-ok">
          이상 없음 · 감사 줄 {check.entries}개 · 기록 {check.records}개
        </p>
      ) : (
        <div className="space-y-2 rounded-sm border border-danger/40 px-3 py-2" data-testid="audit-broken">
          <p className="font-semibold text-danger">
            변조 흔적 있음{check.broken_at ? ` · ${check.broken_at}번째 줄부터` : ''}
          </p>
          <ul className="list-disc space-y-0.5 pl-5 text-foreground-secondary">
            {check.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
