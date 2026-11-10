// 구성원 관리 상태: 목록 불러오기 · 계정 만들기 · 비밀번호 초기화 · 역할·사용 여부 바꾸기 · 지우기 · 임시 비밀번호 복사.
// 한 번에 동작 하나만(busy), 끝나면 목록을 다시 불러온다. 서버가 막은 이유(마지막 팀장 등)는 그 문구 그대로.
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ApiError, api, type Account } from '@/api/client'
import { loginIdProblem } from '@/lib/account'
import type { StaffRole } from './roles'

/** 이 창에서 한 번만 보이는 임시 비밀번호. */
export interface Issued {
  loginId: string
  name: string
  password: string
  reason: 'created' | 'reset'
}

export interface Draft {
  loginId: string
  name: string
  role: StaffRole
}

/** 임시 비밀번호 상자(IssuedPassword): 비밀번호와 복사. */
export interface IssuedBox {
  issued: Issued
  copied: boolean
  onCopy: () => void
}

/** 구성원 추가 줄(MemberForm): 적는 값 · 칸 하나 고치기 · '구성원 추가'. */
export interface MemberDraftForm {
  draft: Draft
  /** 고친 칸만 바꾸고 나머지 칸은 그대로 둔다. */
  edit: (patch: Partial<Draft>) => void
  /** 진행 중인 동작(있으면 '구성원 추가'가 잠긴다). */
  busy: string | null
  submit: (event: FormEvent) => void
}

/** 그 줄에서 한 번 더 묻는 일: 어느 줄(아이디)의 비밀번호 초기화 또는 지우기. */
export interface Confirming {
  loginId: string
  action: 'reset' | 'delete'
}

/** 구성원 표(MemberTable): 목록(불러오는 중이면 null)과 줄마다 동작. */
export interface MemberRows {
  accounts: Account[] | null
  /** 진행 중인 동작(있으면 단추가 잠긴다 — 한 번에 하나만). */
  busy: string | null
  /** 한 번 더 묻고 있는 줄과 일(없으면 null). */
  confirming: Confirming | null
  onConfirming: (next: Confirming | null) => void
  onReset: (account: Account) => void
  onUpdate: (account: Account, body: { role?: StaffRole; disabled?: boolean }) => void
  onDelete: (account: Account) => void
}

const message = (caught: unknown) => (caught instanceof ApiError ? caught.message : String(caught))

/**
 * 반환: error = 대화상자 위 오류 한 줄, notice = 방금 끝낸 일 한 줄(지우기), change = 열고 닫기(닫으면 임시 비밀번호를
 * 지운다), password = 방금 받은 임시 비밀번호 상자(없으면 null), form = 추가 줄, table = 구성원 표.
 */
export function useMembers(open: boolean, onOpenChange: (open: boolean) => void) {
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [issued, setIssued] = useState<Issued | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirming, setConfirming] = useState<Confirming | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>({
    loginId: '',
    name: '',
    role: 'member',
  })

  const load = useCallback(async () => {
    try {
      setAccounts([...(await api.accounts()).items])
    } catch (caught) {
      setError(`구성원 목록 불러오기 실패 · ${message(caught)}`)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    let alive = true
    api.accounts().then(
      (list) => alive && setAccounts([...list.items]),
      (caught: unknown) => alive && setError(`구성원 목록 불러오기 실패 · ${message(caught)}`),
    )
    return () => {
      alive = false
    }
  }, [open])

  const change = (next: boolean) => {
    if (!next) {
      // 닫으면 임시 비밀번호를 지운다(다시 볼 수 없음)
      setIssued(null)
      setError(null)
      setNotice(null)
      setConfirming(null)
      setCopied(false)
    }
    onOpenChange(next)
  }

  const run = async (key: string, task: () => Promise<void>) => {
    if (busy) return
    setBusy(key)
    setError(null)
    setNotice(null)
    try {
      await task()
      await load()
    } catch (caught) {
      setError(message(caught))
    } finally {
      setBusy(null)
    }
  }

  const add = (event: FormEvent) => {
    event.preventDefault()
    const problem = loginIdProblem(draft.loginId) ?? (draft.name.trim() ? null : '이름 입력 필요')
    if (problem) {
      setError(problem)
      return
    }
    void run('add', async () => {
      const created = await api.createAccount({
        login_id: draft.loginId.trim().toLowerCase(),
        name: draft.name.trim(),
        role: draft.role,
      })
      setIssued({
        loginId: created.account.login_id,
        name: created.account.name,
        password: created.temporary_password,
        reason: 'created',
      })
      setCopied(false)
      setDraft({ loginId: '', name: '', role: 'member' })
    })
  }

  const reset = (account: Account) =>
    run(`reset:${account.login_id}`, async () => {
      const result = await api.resetPassword(account.login_id)
      setIssued({ loginId: account.login_id, name: account.name, password: result.temporary_password, reason: 'reset' })
      setCopied(false)
      setConfirming(null)
    })

  const update = (account: Account, body: { role?: StaffRole; disabled?: boolean }) =>
    run(`update:${account.login_id}`, async () => {
      await api.updateAccount(account.login_id, body)
    })

  const remove = (account: Account) =>
    run(`delete:${account.login_id}`, async () => {
      await api.deleteAccount(account.login_id)
      setConfirming(null)
      // 지운 사람에게 막 발급한 임시 비밀번호 상자는 닫는다(쓸 곳이 없음)
      setIssued((shown) => (shown?.loginId === account.login_id ? null : shown))
      setNotice(`${account.name}(${account.login_id}) 계정 삭제됨 · 기록·결재에 남은 이름은 그대로`)
    })

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setError('복사 실패 · 직접 골라 복사')
    }
  }

  const password: IssuedBox | null = issued && { issued, copied, onCopy: () => void copy(issued.password) }
  const form: MemberDraftForm = {
    draft,
    edit: (patch) => setDraft((d) => ({ ...d, ...patch })),
    busy,
    submit: add,
  }
  const table: MemberRows = {
    accounts,
    busy,
    confirming,
    onConfirming: setConfirming,
    onReset: reset,
    onUpdate: update,
    onDelete: remove,
  }
  return { error, notice, change, password, form, table }
}
