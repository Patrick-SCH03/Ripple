// 방금 만든(또는 초기화한) 임시 비밀번호 상자: 이 창을 닫으면 다시 볼 수 없다.
import { Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { IssuedBox } from './useMembers'

export function IssuedPassword({ issued, copied, onCopy }: IssuedBox) {
  return (
    <div className="rounded-md border border-primary/40 p-3" data-testid="issued-password">
      <p className="text-sm">
        {issued.name}({issued.loginId}) 님의 {issued.reason === 'created' ? '임시 비밀번호' : '새 임시 비밀번호'}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <code className="rounded-sm border border-border bg-muted px-2 py-1 font-mono text-md select-all">
          {issued.password}
        </code>
        <Button variant="outline" size="sm" onClick={onCopy}>
          <Copy aria-hidden />
          {copied ? '복사됨' : '복사'}
        </Button>
      </div>
      <p className="mt-2 text-xs text-foreground-secondary">
        창을 닫으면 다시 볼 수 없음 · 메신저에 남기지 말고 본인에게 직접 전달
      </p>
    </div>
  )
}
