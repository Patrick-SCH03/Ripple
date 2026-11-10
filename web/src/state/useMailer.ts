// Gmail 쓰기 창으로 열기(docs/records.md(통보)): 보내는 사람 이름(로그인한 사람), 열기·복사. 계산은 lib/mail.ts.
// 메일 앱(mailto)은 쓰지 않는다. Gmail은 초안이 주소로 Google에 가므로 합성 데이터일 때만
// 연다(canOpen) — 실데이터 지도는 복사만.
// 본문을 주소에 못 넣으면 본문을 클립보드로 넘기고 그 초안을 '붙여 넣기 기다림'으로 잠근다 — 잠긴 동안에는 카드·창 어디서든
// 다른 초안을 열거나 다른 글을 복사하지 않는다(앞 본문을 덮어쓰지 않게). 잠금은 복사가 끝나기 전에 건다.
// 팝업 차단으로 창이 열리지 않으면 열었다고 하지 않는다.
import { useCallback, useMemo, useRef, useState } from 'react'
import type { EmailDraft } from '@/api/client'
import { type MailText, planCompose } from '@/lib/mail'
import { useSignedIn } from './sessionContext'

export type OpenStatus =
  | 'opened' // Gmail 창을 열었음
  | 'blocked' // 팝업 차단으로 창이 열리지 않음
  | 'locked' // 다른 초안이 붙여 넣기를 기다리는 중이라 열지 않음
  | 'unavailable' // 실데이터 지도라 Gmail로 열지 않음

export interface OpenResult {
  status: OpenStatus
  /** 본문까지 채워 열었는가(아니면 클립보드로 넘기고 이 초안을 잠갔다). */
  bodyIncluded: boolean
  /** 클립보드로 넘긴 본문을 복사했는가(bodyIncluded면 true). */
  copied: boolean
}

export interface Mailer {
  /** Gmail로 열 수 있는가: 합성 데이터 지도일 때만(아니면 복사만). */
  canOpen: boolean
  signer: string
  /** 붙여 넣기를 기다리는 초안(없으면 null). */
  pending: string | null
  /** text: 번역 보기의 제목·본문(1.36.0, 없으면 한국어 원문). */
  open: (key: string, email: EmailDraft, text?: MailText) => Promise<OpenResult>
  /** 붙여 넣기를 마쳤다(잠금 풀기). */
  release: (key: string) => void
  /** 글 복사. 다른 초안이 붙여 넣기를 기다리면 복사하지 않는다(그 초안 자신의 본문 다시 복사는 된다). */
  copy: (text: string, key?: string) => Promise<boolean>
}

export function copyText(text: string): Promise<boolean> {
  // 클립보드는 보안 맥락(https·localhost)에서만 있다
  if (!('clipboard' in navigator)) return Promise.resolve(false)
  return navigator.clipboard.writeText(text).then(
    () => true,
    () => false,
  )
}

/** 새 탭을 열고 열렸는지 돌려준다(noopener를 주면 성공해도 null이라 직접 끊는다). */
function openTab(url: string): boolean {
  const tab = window.open(url, '_blank')
  if (!tab) return false
  tab.opener = null
  return true
}

export function useMailer(canOpen: boolean): Mailer {
  const { me } = useSignedIn()
  const [pending, setPending] = useState<string | null>(null)
  const lock = useRef<string | null>(null) // 같은 클릭 묶음 안에서도 바로 보이게(상태 반영 전)
  const signer = me.name

  const hold = useCallback((key: string | null) => {
    lock.current = key
    setPending(key)
  }, [])

  const open = useCallback(
    async (key: string, email: EmailDraft, text?: MailText): Promise<OpenResult> => {
      const plan = planCompose(email, signer, text)
      if (!canOpen) return { status: 'unavailable', bodyIncluded: plan.bodyIncluded, copied: false }
      if (lock.current && lock.current !== key) return { status: 'locked', bodyIncluded: plan.bodyIncluded, copied: false }
      if (!plan.bodyIncluded) hold(key)
      const copying = plan.bodyIncluded ? Promise.resolve(true) : copyText(plan.body)
      const status: OpenStatus = openTab(plan.url) ? 'opened' : 'blocked'
      if (status === 'blocked' && lock.current === key) hold(null)
      return { status, bodyIncluded: plan.bodyIncluded, copied: await copying }
    },
    [canOpen, signer, hold],
  )

  const release = useCallback(
    (key: string) => {
      if (lock.current === key) hold(null)
    },
    [hold],
  )

  const copy = useCallback((text: string, key?: string) => {
    if (lock.current && lock.current !== key) return Promise.resolve(false)
    return copyText(text)
  }, [])

  return useMemo(
    () => ({ canOpen, signer, pending, open, release, copy }),
    [canOpen, signer, pending, open, release, copy],
  )
}
