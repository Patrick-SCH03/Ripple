// 메일 초안 카드 한 장(docs/records.md(통보), DESIGN.md 6절 AI 비서): 카드마다 경계가 분명하게 — 진한 테두리 + 옅은 머리 띠
// (수신 구분 칩 · 회사·담당 이름 굵게 · Gmail로 쓰기 · 복사). 처음에는 접힌 요약(받는 사람 한 줄 + 제목)만, 펼치면 참조 · 본문 ·
// 통보 기록. 작업반 통보에 번역(1.36.0)이 있으면 접힌 상태에서도 머리 바로 아래에 '통보문 언어' 단추.
// 앱은 보내지 않는다: 'Gmail로 쓰기'는 새 탭의 Gmail 쓰기 창에 초안을 채워 열고, 보내기는 사람이 누른다.
// 실데이터 지도에서는 Gmail로 열지 않아 단추를 숨기고 복사만 둔다.
// 본문이 길어 주소에 못 넣으면 본문을 클립보드로 넘기고 이 초안을 '붙여 넣기 기다림'으로 잠근다(mailer.pending) — 잠긴 동안
// 다른 초안의 메일 쓰기·복사는 막고, 이 카드에서 ‘본문 다시 복사’·'붙여 넣기 완료'를 고른다.
// AI 비서 칸과 상세 사전 점검의 '통보문 보기' 대화상자(1.37.0)가 같은 카드를 쓴다.
import { Check, ChevronDown, ClipboardCheck, Copy, Mail } from 'lucide-react'
import { useContext, useEffect, useId, useState } from 'react'
import type { Notification, NoticeStep } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NOTIFY_CHIPS, NOTIFY_TARGETS } from '@/lib/assistant'
import { draftKey, fullText, personLabel, recipientLine } from '@/lib/mail'
import { DEFAULT_VIEW, type MailView, viewText } from '@/lib/mailView'
import { NOTICE_STEPS, NOTICE_STEP_LABEL, noticeKey, noticeLine } from '@/lib/notices'
import { cn } from '@/lib/utils'
import { NoticeContext } from '@/state/noticeContext'
import type { Mailer, OpenStatus } from '@/state/useMailer'
import { BlockText } from './BlockText'
import { MailLanguageBar } from './MailLanguageBar'

type Note = OpenStatus | 'copied' | 'copy-failed' | 'paste-failed'

const NOTE: Record<Exclude<Note, 'copied'>, { text: string; danger?: boolean }> = {
  opened: { text: 'Gmail 창 열림 · 보내기는 Gmail에서' },
  unavailable: { text: '실제 데이터 지도 — Gmail 열기 없음 · 복사 후 메일에 붙여 넣기', danger: true },
  blocked: { text: '브라우저가 새 창 차단 · 주소창에서 팝업 허용 후 다시 열기', danger: true },
  locked: { text: '다른 초안 붙여 넣기 대기 중 · 그 초안의 ‘붙여 넣기 완료’ 먼저', danger: true },
  'copy-failed': { text: '복사 실패 · 직접 골라 복사', danger: true },
  'paste-failed': { text: '본문 복사 실패 · ‘본문 다시 복사’', danger: true },
}

/** 가상 연락처 안내(늘 떠 있는 줄 대신 받는 사람 옆 ⓘ — DESIGN.md 2절 보조 한 줄 원칙). */
const FICTIONAL_LINES = ['.example 주소(RFC 2606 예약 도메인) — 실제 배달 없음', '합성 지도에만 붙는 지어낸 회사·사람']

interface Props {
  notification: Notification
  /** 지금 상세에 보이는 분석이 아닌 차례의 초안. */
  stale: boolean
  mailer: Mailer
  /** 처음부터 펼쳐 둘까(대화상자에 한 장뿐일 때). */
  defaultExpanded?: boolean
}

/** 카드 테두리·머리 띠: 카드끼리 붙어 보이지 않게 진한 테두리와 옅은 바탕 머리(DESIGN.md 2절 구역 카드와 같은 모양). */
const CARD = 'overflow-hidden rounded-md border border-border-strong bg-surface'
const HEAD = 'flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border-strong bg-muted px-3 py-2'

function TargetChip({ notification }: { notification: Notification }) {
  return (
    <span
      className="inline-flex h-6 shrink-0 items-center rounded-sm border border-border-strong bg-surface px-1.5 text-xs font-medium text-foreground-secondary"
      title={NOTIFY_TARGETS[notification.target]}
      data-testid="mail-target"
    >
      <span className="sr-only">{NOTIFY_TARGETS[notification.target]}</span>
      <span aria-hidden>{NOTIFY_CHIPS[notification.target]}</span>
    </span>
  )
}

export function NotificationCard({ notification, stale, mailer, defaultExpanded = false }: Props) {
  const [note, setNote] = useState<Note | null>(null)
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [view, setView] = useState<MailView>(DEFAULT_VIEW)
  const detailId = useId()
  const email = notification.email
  const key = draftKey(notification)
  const waiting = mailer.pending === key
  const lockedByOther = mailer.pending !== null && !waiting
  const company = email?.to[0]?.organization ?? notification.recipient

  useEffect(() => {
    if (note !== 'copied') return
    const timer = window.setTimeout(() => setNote(null), 2000)
    return () => window.clearTimeout(timer)
  }, [note])

  if (!email) return <LegacyCard notification={notification} stale={stale} mailer={mailer} />

  const text = viewText(email, mailer.signer, view)
  const body = text.body
  const onCopy = () =>
    void mailer.copy(fullText(email, mailer.signer, text), key).then((ok) => setNote(ok ? 'copied' : 'copy-failed'))
  const onOpen = () =>
    void mailer.open(key, email, text).then((result) => {
      if (!result.bodyIncluded && result.status !== 'blocked' && result.status !== 'locked' && !result.copied) {
        setNote('paste-failed')
      } else setNote(result.status)
    })
  const onCopyBody = () => void mailer.copy(body, key).then((ok) => setNote(ok ? null : 'paste-failed'))
  const shown = note && note !== 'copied' ? NOTE[note] : null
  const translated = (email.translations?.length ?? 0) > 0

  return (
    <li className={CARD} data-testid="mail-card" data-target={notification.target}>
      <div className={HEAD}>
        <TargetChip notification={notification} />
        {/* 회사·담당 이름은 말줄임 없이(좁으면 단추가 다음 줄로) — '가람…'처럼 잘려 누구에게 가는지 안 보였음 */}
        <span className="min-w-0 flex-1 basis-24 break-keep" data-testid="mail-company">
          <span className="font-semibold">{notification.recipient}</span>
          {company !== notification.recipient && !notification.recipient.includes(company) && (
            <span className="text-sm text-foreground-secondary"> · {company}</span>
          )}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {mailer.canOpen && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onOpen}
              disabled={lockedByOther}
              title={lockedByOther ? '다른 초안의 붙여 넣기 먼저' : undefined}
              aria-label={`${company}에 보낼 메일을 Gmail로 쓰기`}
              data-testid="mail-open"
            >
              <Mail aria-hidden />
              Gmail로 쓰기
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={onCopy}
            disabled={lockedByOther}
            aria-label={`${company} 메일 초안 복사`}
          >
            {note === 'copied' ? <Check aria-hidden /> : <Copy aria-hidden />}
            {note === 'copied' ? '복사됨' : '복사'}
          </Button>
        </div>
      </div>
      {translated && (
        <div className="border-b border-border px-3 py-2">
          <MailLanguageBar email={email} view={view} onView={setView} showMissing={expanded} />
        </div>
      )}
      <div className="space-y-1.5 px-3 py-2.5">
        <p className="flex min-w-0 items-center gap-2 text-sm">
          <span className="shrink-0 text-foreground-secondary">받는 사람</span>
          <span
            className="min-w-0 truncate"
            title={email.to.map(personLabel).join(', ') || undefined}
            data-testid="mail-to"
          >
            {recipientLine(email, company)}
          </span>
          {email.fictional && <InfoPop title="시연용 가상 연락처" lines={FICTIONAL_LINES} />}
        </p>
        <p className={cn('text-sm font-medium', !expanded && 'line-clamp-2')} data-testid="mail-subject">
          {text.subject}
        </p>
        {expanded && (
          <div id={detailId} className="space-y-2 pt-1">
            <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
              <dt className="text-foreground-secondary">주소</dt>
              <dd className="min-w-0 break-all">{email.to.map(personLabel).join(', ') || '없음'}</dd>
              {email.cc.length > 0 && (
                <>
                  <dt className="text-foreground-secondary">참조</dt>
                  <dd className="min-w-0 break-all">{email.cc.map(personLabel).join(', ')}</dd>
                </>
              )}
            </dl>
            <div
              className="whitespace-pre-line rounded-sm border border-border bg-canvas px-3 py-2 text-sm leading-relaxed"
              data-testid="mail-body"
            >
              {body}
            </div>
          </div>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="-ml-2 h-8 px-2 text-primary"
          aria-expanded={expanded}
          aria-controls={expanded ? detailId : undefined}
          onClick={() => setExpanded((open) => !open)}
          data-testid="mail-expand"
        >
          {expanded ? '접기' : email.cc.length ? '본문·참조 보기' : '본문 보기'}
          <ChevronDown aria-hidden className={cn('transition-transform', expanded && 'rotate-180')} />
        </Button>
        {stale && <p className="text-xs text-warning">지난 분석의 초안 · 조건 바뀜, 확인 후 보내기</p>}
        <div role="status" aria-live="polite" className="space-y-1 text-xs" data-testid="mail-card-status">
          {waiting && (
            <div className="space-y-1 rounded-sm border border-warning/50 bg-warning/10 px-2 py-1.5">
              <p>본문이 길어 클립보드에 복사됨 · 메일 본문 칸에 붙여 넣은 뒤 ‘붙여 넣기 완료’</p>
              <div className="flex flex-wrap gap-2">
                <Button size="xs" variant="outline" onClick={onCopyBody}>
                  <Copy aria-hidden />
                  본문 다시 복사
                </Button>
                <Button size="xs" onClick={() => mailer.release(key)} data-testid="mail-card-pasted">
                  <ClipboardCheck aria-hidden />
                  붙여 넣기 완료
                </Button>
              </div>
            </div>
          )}
          {shown && !(waiting && note === 'opened') && (
            <p className={shown.danger ? 'text-danger' : 'text-foreground-secondary'}>{shown.text}</p>
          )}
          {note === 'copied' && <span className="sr-only">메일 초안 복사됨</span>}
        </div>
        {!stale && <NoticeRow notification={notification} company={company} expanded={expanded} />}
      </div>
    </li>
  )
}

/**
 * 통보 기록(1.28.0): 이 받는 쪽에 보냈는지·받았다고 확인했는지·회신이 왔는지를 날짜와 함께 감사 사슬에 남긴다.
 * 앱은 메일을 보내지 않으니 사람이 한 일을 적는다. 고칠 수 없고, 잘못 적었으면 같은 단계를 새 날짜로 다시 적는다.
 * 접힌 카드에서는 남긴 기록이 있을 때만 상태 한 줄, 펼치면 날짜·단계 단추(기록 전이면 안내는 ⓘ).
 */
function NoticeRow({
  notification,
  company,
  expanded,
}: {
  notification: Notification
  company: string
  expanded: boolean
}) {
  const bridge = useContext(NoticeContext)
  const [on, setOn] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 다른 설계변경으로 넘어가는 중(새 분석 전·실패)에는 줄 자체를 숨긴다 — 그 설계변경의 통보 상태가 섞여 보이지 않게
  if (!bridge?.ready) return null
  const state = bridge.states.get(noticeKey(notification.target, notification.recipient_id))
  if (!expanded && !state) return null
  const day = on ?? bridge.today
  const write = (step: NoticeStep) =>
    void bridge
      .log({ target: notification.target, recipient_id: notification.recipient_id, step, on: day, note: null })
      .then(setError)
  return (
    <div className="space-y-1.5 border-t border-border pt-2 text-xs" data-testid="notice-row">
      <p className="flex flex-wrap items-center gap-x-1.5">
        <span className="font-medium">통보 기록</span>
        <span className="text-foreground-secondary" data-testid="notice-line">
          {noticeLine(state, bridge.today)}
        </span>
        {expanded && !bridge.recorded && (
          <InfoPop title="통보 기록" lines={['결재 띠에서 기록 후 보낸 날·확인·회신 기록 가능']} />
        )}
      </p>
      {expanded && bridge.recorded && bridge.canLog && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Input
            type="date"
            aria-label={`${company} 통보 날짜`}
            value={day}
            max={bridge.today}
            onChange={(event) => setOn(event.target.value || null)}
            className="h-7 w-auto rounded-sm px-2 text-xs tabular-nums md:text-xs"
          />
          {NOTICE_STEPS.map((step) => (
            <Button
              key={step}
              size="xs"
              variant={state?.[step] ? 'secondary' : 'outline'}
              disabled={bridge.busy || day > bridge.today}
              onClick={() => write(step)}
              data-testid={`notice-${step}`}
            >
              {NOTICE_STEP_LABEL[step]}
            </Button>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

/** 계약 1.21.0 전 초안(메일 없음): 요약 문장만. */
function LegacyCard({ notification, stale, mailer }: Props) {
  const [copied, setCopied] = useState<boolean | null>(null)
  const text = notification.body.blocks.map((block) => block.text).join(' ')
  return (
    <li className={CARD}>
      <div className={HEAD}>
        <TargetChip notification={notification} />
        <span className="min-w-0 flex-1 basis-24 font-semibold break-keep">{notification.recipient}</span>
        <Button size="sm" variant="ghost" onClick={() => void mailer.copy(text).then(setCopied)}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? '복사됨' : '복사'}
        </Button>
      </div>
      <div className="space-y-1 px-3 py-2 text-sm">
        {notification.body.blocks.map((block, index) => (
          <BlockText key={index} block={block} />
        ))}
        {stale && <p className="text-xs text-warning">지난 분석의 초안 · 조건 바뀜, 확인 후 보내기</p>}
        {copied === false && <p className="text-xs text-danger">복사 실패 · 직접 골라 복사</p>}
      </div>
    </li>
  )
}
