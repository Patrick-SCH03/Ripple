// 메일 보내기(docs/records.md(통보)): 한 차례의 알림 초안을 Gmail 쓰기 창으로 차례로 연다. 앱은 보내지 않는다.
// Gmail은 합성 데이터만(실데이터 지도는 복사만) · 고르기 · '다음 메일 열기'(클릭 한 번에 한 통 — 팝업 차단을 피함) ·
// 본문이 길면 클립보드로 넘기고 그 초안을 잠근다(mailer.pending) — '붙여 넣기 완료'를 누르기 전에는 다음 메일·다른 줄 열기·
// 모두 복사를 막는다(앞 본문을 덮어쓰지 않게, 카드와 같은 잠금). 팝업이 막히면 열었음으로 두지 않는다.
import { Check, ClipboardCheck, Copy, Mail } from 'lucide-react'
import { useState } from 'react'
import type { Notification } from '@/api/client'
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
import { NOTIFY_TARGETS } from '@/lib/assistant'
import { useReturnFocus } from '@/lib/focus'
import {
  type DraftState,
  bodyText,
  draftKey,
  fullText,
  nextToOpen,
  personLabel,
} from '@/lib/mail'
import type { Mailer } from '@/state/useMailer'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  notifications: readonly Notification[]
  mailer: Mailer
}

const STATE_LABEL: Record<DraftState, string> = { opened: '열림', paste: '붙여 넣기 기다림', done: '붙여 넣음' }

export function MailDialog({ open, onOpenChange, notifications, mailer }: Props) {
  const returnFocus = useReturnFocus(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl" onCloseAutoFocus={returnFocus} data-testid="mail-dialog">
        <DialogHeader>
          <DialogTitle>메일 보내기</DialogTitle>
          <DialogDescription>
            초안을 새 탭 Gmail 쓰기 창에 한 통씩 · 보내기는 Gmail에서 직접
          </DialogDescription>
        </DialogHeader>
        {open && <MailList notifications={notifications} mailer={mailer} />}
      </DialogContent>
    </Dialog>
  )
}

function MailList({ notifications, mailer }: Omit<Props, 'open' | 'onOpenChange'>) {
  const drafts = notifications.filter((n) => n.email)
  const order = drafts.map(draftKey)
  const [selected, setSelected] = useState<Set<string>>(() => new Set(order))
  const [states, setStates] = useState<Record<string, DraftState | undefined>>({})
  const [notice, setNotice] = useState<string | null>(null)
  const waiting = mailer.pending && order.includes(mailer.pending) ? mailer.pending : null
  const locked = mailer.pending !== null
  const shown: Record<string, DraftState | undefined> = waiting ? { ...states, [waiting]: 'paste' } : states
  const next = locked ? null : nextToOpen(order, selected, shown)
  const done = order.filter((id) => selected.has(id) && shown[id]).length
  const fictional = drafts.some((n) => n.email?.fictional)

  const openOne = (notification: Notification) => {
    const email = notification.email
    if (!email) return
    const key = draftKey(notification)
    void mailer.open(key, email).then((result) => {
      if (result.status === 'unavailable') {
        setNotice('실제 데이터 지도 — Gmail 열기 없음 · 모두 복사로')
        return
      }
      if (result.status === 'locked') {
        setNotice('다른 초안 붙여 넣기 대기 중 · ‘붙여 넣기 완료’ 먼저')
        return
      }
      if (result.status === 'blocked') {
        setNotice('브라우저가 새 창 차단 · 주소창에서 팝업 허용 후 다시 열기')
        return
      }
      setStates((current) => ({ ...current, [key]: 'opened' }))
      setNotice(
        result.bodyIncluded
          ? `${email.subject} — Gmail 창 열림`
          : result.copied
            ? '본문이 길어 클립보드에 복사됨 · 메일 본문 칸에 붙여 넣은 뒤 ‘붙여 넣기 완료’'
            : '본문 복사 실패 · 그 줄의 ‘본문 다시 복사’',
      )
    })
  }
  const copyBody = (notification: Notification) => {
    const email = notification.email
    if (!email) return
    void mailer
      .copy(bodyText(email, mailer.signer), draftKey(notification))
      .then((ok) => setNotice(ok ? '본문 다시 복사됨' : '본문 복사 실패 · 메일 미리보기에서 직접 복사'))
  }
  const confirmPaste = (key: string) => {
    mailer.release(key)
    setStates((current) => ({ ...current, [key]: 'done' }))
    setNotice(null)
  }
  const copyAll = () => {
    const text = drafts
      .filter((n) => selected.has(draftKey(n)))
      .map((n) => (n.email ? fullText(n.email, mailer.signer) : ''))
      .join('\n\n────────\n\n')
    void mailer.copy(text).then((ok) => setNotice(ok ? '고른 초안 모두 복사됨' : '복사 실패'))
  }
  const toggle = (key: string) =>
    setSelected((current) => {
      const copy = new Set(current)
      if (copy.has(key)) copy.delete(key)
      else copy.add(key)
      return copy
    })

  const nextDraft = mailer.canOpen ? drafts.find((n) => draftKey(n) === next) : undefined
  return (
    <div className="min-w-0 space-y-3 text-sm">
      {!mailer.canOpen && (
        <p className="rounded-sm border border-warning/50 bg-warning/10 px-3 py-2 text-xs" data-testid="mail-unavailable">
          실제 데이터 지도 — Gmail 열기 없음(초안이 외부 서비스로 가지 않게) · 모두 복사 후 메일에 붙여 넣기
        </p>
      )}
      {fictional && (
        <p className="text-xs text-foreground-secondary">
          받는 사람: 시연용 가상 연락처(.example 주소 — 실제 배달 없음)
        </p>
      )}
      <ul className="max-h-[50vh] space-y-2 overflow-y-auto" data-testid="mail-rows">
        {drafts.map((notification) => {
          const key = draftKey(notification)
          const email = notification.email!
          const state = shown[key]
          return (
            <li key={key} className="flex items-start gap-2 rounded-md border border-border px-3 py-2" data-testid="mail-row">
              <input
                type="checkbox"
                className="mt-1 size-4 accent-primary"
                checked={selected.has(key)}
                onChange={() => toggle(key)}
                aria-label={`${email.subject} 고르기`}
              />
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="flex flex-wrap items-center gap-x-2">
                  <span className="text-xs text-foreground-secondary">{NOTIFY_TARGETS[notification.target]}</span>
                  <span className="font-medium">{email.to[0]?.organization ?? notification.recipient}</span>
                  {state && (
                    <span
                      className={`rounded-sm px-1.5 text-xs ${state === 'paste' ? 'bg-warning/15 text-warning' : 'bg-success/15 text-success'}`}
                      data-testid="mail-row-state"
                    >
                      {STATE_LABEL[state]}
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-foreground-secondary">
                  {email.to.length ? email.to.map(personLabel).join(', ') : '받는 사람 없음(직접 적기)'}
                </p>
                <p className="truncate text-xs">{email.subject}</p>
                {state === 'paste' && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Button size="xs" variant="outline" onClick={() => copyBody(notification)}>
                      <Copy aria-hidden />
                      본문 다시 복사
                    </Button>
                    <Button size="xs" onClick={() => confirmPaste(key)} data-testid="mail-pasted">
                      <ClipboardCheck aria-hidden />
                      붙여 넣기 완료
                    </Button>
                  </div>
                )}
              </div>
              <Button
                size="xs"
                variant="ghost"
                onClick={() => openOne(notification)}
                disabled={!mailer.canOpen || (locked && waiting !== key)}
                aria-label={`${email.subject} 열기`}
              >
                {state ? <Check aria-hidden /> : <Mail aria-hidden />}
                {state ? '다시 열기' : '열기'}
              </Button>
            </li>
          )
        })}
      </ul>
      <p role="status" aria-live="polite" className="min-h-6 text-xs text-foreground-secondary" data-testid="mail-notice">
        {notice ?? (waiting ? '붙여 넣기 확인 후 다음 메일 열기 가능' : '')}
      </p>
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">닫기</Button>
        </DialogClose>
        <Button variant="outline" onClick={copyAll} disabled={selected.size === 0 || locked}>
          <Copy aria-hidden />
          모두 복사
        </Button>
        <Button onClick={() => nextDraft && openOne(nextDraft)} disabled={!nextDraft} data-testid="mail-next">
          <Mail aria-hidden />
          {!mailer.canOpen
            ? 'Gmail 열기 불가'
            : nextDraft
              ? `다음 메일 열기 (${done + 1}/${selected.size})`
              : waiting
                ? '붙여 넣기 확인 기다림'
                : selected.size
                  ? '모두 열림'
                  : '고른 초안 없음'}
        </Button>
      </DialogFooter>
    </div>
  )
}
