// 위 막대 아래 알림 한 줄(작업 공간이 바뀜·지도 전환 실패·시작 때 복구 실패). 내가 한 일의 결과(info)는 몇 초 뒤
// 저절로 닫히고, 모르는 사이 바뀐 것(warning)·실패(danger)는 사용자가 닫을 때까지 남는다.
import { X } from 'lucide-react'
import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Notice } from '@/lib/workspace'

const TONES = {
  info: 'border-primary/40 bg-primary/8',
  warning: 'border-warning/50 bg-warning/10',
  danger: 'border-danger/40 bg-danger/8',
} as const

export function NoticeBar({ notice, onDismiss }: { notice: Notice | null; onDismiss: () => void }) {
  useEffect(() => {
    if (notice?.tone !== 'info') return
    const timer = window.setTimeout(onDismiss, 6000)
    return () => window.clearTimeout(timer)
  }, [notice, onDismiss])

  if (!notice) return null
  return (
    <div
      role={notice.tone === 'info' ? 'status' : 'alert'}
      data-testid="notice-bar"
      className={cn('flex shrink-0 items-center gap-2 border-b px-3 py-1 text-sm', TONES[notice.tone])}
    >
      <p className="min-w-0 flex-1">{notice.text}</p>
      <Button variant="ghost" size="icon-sm" aria-label="알림 닫기" onClick={onDismiss}>
        <X aria-hidden />
      </Button>
    </div>
  )
}
