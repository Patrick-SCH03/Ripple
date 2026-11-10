// 상세 '통보문 보기'(계약 1.37.0, docs/records.md(통보) 7절): 사전 점검 '현장 통보 필수' 옆 단추로 여는 대화상자.
// 보던 분석의 요청 그대로 서버가 다시 분석해 AI 비서와 같은 규칙으로 만든 작업반(사내 협력사) 통보문을 같은 메일 카드로
// 보인다(언어 전환 · 복사 · Gmail로 쓰기 · 통보 기록). 외부 AI 없음. 처음 열 때 한 번 받고 같은 분석이면 다시 받지 않는다(실패는 다시 열 때 다시 받음).
import { LoaderCircle, Mail } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type AnalysisNotices, type AnalysisResult } from '@/api/client'
import { NotificationCard } from '@/components/assistant/NotificationCard'
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
import { cn } from '@/lib/utils'
import { useMailer } from '@/state/useMailer'

/** '현장 통보 필수' 줄 옆 단추(접힌 모양·펼친 모양 같은 단추). */
export function NoticeOpenButton({ onClick, compact }: { onClick: () => void; compact: boolean }) {
  return (
    <Button
      size="sm"
      variant="outline"
      className={cn('shrink-0', compact && 'h-11 px-3')}
      onClick={onClick}
      aria-haspopup="dialog"
      data-testid="notice-open"
    >
      <Mail aria-hidden />
      통보문 보기
    </Button>
  )
}

type Loaded = { id: string; notices: AnalysisNotices } | { id: string; error: string }

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  result: AnalysisResult
  /** Gmail로 열 수 있는가(합성 데이터 지도만 — 실데이터는 복사만). */
  webMail: boolean
}

export function CrewNoticeDialog({ open, onOpenChange, result, webMail }: Props) {
  const returnFocus = useReturnFocus(open)
  const mailer = useMailer(webMail)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const id = result.analysis_id
  const current = loaded?.id === id ? loaded : null

  useEffect(() => {
    if (!open || current) return
    const controller = new AbortController()
    api.analysisNotices(result.request, 'crew', controller.signal).then(
      (notices) => setLoaded({ id, notices }),
      (error: unknown) => {
        if (controller.signal.aborted) return
        setLoaded({ id, error: error instanceof Error && error.message ? error.message : '통보문을 만들지 못함' })
      },
    )
    return () => controller.abort()
  }, [open, current, id, result.request])

  const notices = current && 'notices' in current ? current.notices : null
  const cards = notices?.notifications ?? []
  // 실패한 채 닫으면 기억을 비운다 — 다시 열 때 같은 실패 글만 남지 않고 다시 받는다
  const changeOpen = (next: boolean) => {
    if (!next && current && 'error' in current) setLoaded(null)
    onOpenChange(next)
  }
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="sm:max-w-2xl" onCloseAutoFocus={returnFocus} data-testid="notice-dialog">
        <DialogHeader>
          <DialogTitle>현장 통보문{cards.length > 0 && ` · 작업반 ${cards.length}곳`}</DialogTitle>
          <DialogDescription>사전 점검 현장 통보 대상 작업반(사내 협력사)에 보낼 메일 초안 · 보내기는 Gmail에서 직접</DialogDescription>
        </DialogHeader>
        <div className="max-h-[65vh] space-y-3 overflow-y-auto pr-1">
          {!current ? (
            <p className="flex items-center gap-2 text-sm text-foreground-secondary" role="status">
              <LoaderCircle aria-hidden className="size-4 animate-spin" />
              통보문 만드는 중…
            </p>
          ) : 'error' in current ? (
            <p role="alert" className="text-sm text-danger">
              통보문 만들기 실패 · {current.error}
            </p>
          ) : cards.length === 0 ? (
            <p className="text-sm text-foreground-secondary" data-testid="notice-empty">
              보낼 작업반 통보문 없음 · 직영·수행 주체 모름 공정은 사내 작업 지시로
            </p>
          ) : (
            <>
              {notices && notices.analysis_id !== id && (
                <p className="text-sm text-warning">지금 지도 기준으로 다시 계산한 통보문 · 보던 분석과 조건 다름</p>
              )}
              <ul className="space-y-3">
                {cards.map((notification) => (
                  <NotificationCard
                    key={`${notification.target}-${notification.recipient_id}`}
                    notification={notification}
                    stale={false}
                    mailer={mailer}
                    defaultExpanded={cards.length === 1}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
        <DialogFooter className="sm:justify-start">
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
