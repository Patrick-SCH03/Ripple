// 비밀번호 바꾸기 입력(첫 로그인 화면·사용자 메뉴의 대화상자가 함께 씀): 지금 비밀번호 · 새 비밀번호 · 한 번 더.
// 규칙은 서버와 같게 먼저 알려 주고(lib/account), 최종 판단(흔한 비밀번호 등)은 서버 문구를 그대로 보인다.
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { Input } from '@/components/ui/input'
import { PASSWORD_RULE_TEXT, passwordProblem } from '@/lib/account'
import type { Session } from '@/state/useSession'

interface Props {
  session: Session
  loginId: string
  /** 바꾼 뒤(새 세션). */
  onDone: () => void
  /** 단추 줄: 제출 단추를 받아 배치한다(대화상자는 '닫기'와 함께). */
  actions: (submit: { busy: boolean }) => ReactNode
  currentLabel?: string
}

export function PasswordForm({ session, loginId, onDone, actions, currentLabel = '지금 비밀번호' }: Props) {
  const ids = { current: useId(), next: useId(), again: useId(), rule: useId(), error: useId() }
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    const problem = !current
      ? `${currentLabel}를 입력해 주십시오`
      : (passwordProblem(next, loginId) ?? (next !== again ? '새 비밀번호를 두 번 똑같이 입력해 주십시오' : null))
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    const failure = await session.changePassword(current, next)
    setBusy(false)
    if (failure) {
      setError(failure.message)
      return
    }
    onDone()
  }

  const field = (id: string, label: string, value: string, set: (value: string) => void, extra: object = {}) => (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        type="password"
        value={value}
        onChange={(event) => set(event.target.value)}
        aria-invalid={!!error}
        className="h-10"
        {...extra}
      />
    </div>
  )

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate data-testid="password-form">
      {field(ids.current, currentLabel, current, setCurrent, { autoComplete: 'current-password' })}
      {field(ids.next, '새 비밀번호', next, setNext, { autoComplete: 'new-password', 'aria-describedby': ids.rule })}
      <p id={ids.rule} className="-mt-2 text-xs text-foreground-secondary">
        {PASSWORD_RULE_TEXT}
      </p>
      {field(ids.again, '새 비밀번호 한 번 더', again, setAgain, { autoComplete: 'new-password' })}
      {error && (
        <p id={ids.error} role="alert" className="text-sm text-danger" data-testid="password-error">
          {error}
        </p>
      )}
      {actions({ busy })}
    </form>
  )
}
