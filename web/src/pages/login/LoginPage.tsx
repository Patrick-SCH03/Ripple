// 로그인(docs/operations.md(서비스) 3절): 아이디·비밀번호 → 업무 화면. 체험이 켜져 있으면 체험 계정으로도.
// 실패 문구는 아이디·비밀번호 중 어느 쪽이 틀렸는지 말하지 않는다(오류 코드별 합니다체 문구, loginErrors.ts).
// 빠른 로그인(시연 배포 전용, options.quick_login)이면 역할 단추 둘(담당자·파트장, QuickChoices)만 둔다 — 아이디·비밀번호 입력 칸과 체험
// 단추는 그리지 않는다(팀원·관리자 계정은 빠른 로그인을 끈 배포에서 쓴다, docs/operations.md(배포)).
// 상태 확인 전에는 카드 몸을 비워 둔다 — 입력 칸을 그렸다가 빠른 로그인 단추로 바꾸지 않게.
import { useState, type FormEvent } from 'react'
import type { QuickRole } from '@/api/client'
import { Button } from '@/components/ui/button'
import type { LoginReason } from '@/lib/route'
import { navigate } from '@/state/useRoute'
import type { Session } from '@/state/useSession'
import { AuthCard, Notice } from './AuthCard'
import { LoginForm } from './LoginForm'
import { OFFLINE_TEXT, loginErrorText } from './loginErrors'
import { QuickChoices } from './QuickChoices'

interface Props {
  session: Session
  reason: LoginReason | null
  onSignedIn: () => void
}

type Busy = 'login' | 'demo' | QuickRole | null

/** 실패 문구와 그 문구를 낸 곳(빠른 로그인 단추 아래 또는 입력 칸 아래에 한 번만 보이게). */
interface Failure {
  text: string
  from: 'quick' | 'form'
}

const isQuick = (what: NonNullable<Busy>): what is QuickRole => what !== 'login' && what !== 'demo'

/** 빠른 로그인 단추가 들어가는 중인 역할(다른 들어가기 중이거나 쉬는 중이면 null). */
const quickBusy = (busy: Busy): QuickRole | null => (busy !== null && isQuick(busy) ? busy : null)

export function LoginPage({ session, reason, onSignedIn }: Props) {
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState<Busy>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const options = session.options
  const quick = session.optionsChecked && !!options?.quick_login
  const form = session.optionsChecked && !quick
  const notReady = form && options !== null && options.required && !options.accounts_ready

  /** 들어가기 공통(로그인·체험·빠른 로그인): 하는 동안 다른 단추를 막고, 실패하면 서버 문구, 성공하면 onSignedIn. */
  const enter = async (what: NonNullable<Busy>, send: () => Promise<Error | null>, onFailure?: () => void) => {
    if (busy) return
    setBusy(what)
    setFailure(null)
    const result = await send()
    setBusy(null)
    if (result) {
      setFailure({ text: loginErrorText(result), from: isQuick(what) ? 'quick' : 'form' })
      onFailure?.()
      return
    }
    onSignedIn()
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    if (!loginId.trim() || !password) {
      setFailure({ text: '아이디와 비밀번호를 입력해 주십시오', from: 'form' })
      return
    }
    await enter('login', () => session.login(loginId.trim(), password), () => setPassword(''))
  }

  const loginForm = (
    <LoginForm
      loginId={loginId}
      password={password}
      error={failure?.from === 'form' ? failure.text : null}
      busy={busy !== null}
      signingIn={busy === 'login'}
      onLoginId={setLoginId}
      onPassword={setPassword}
      onSubmit={(event) => void submit(event)}
    />
  )

  return (
    <AuthCard
      title="로그인"
      description="설계변경 영향도 분석 업무 화면에 로그인합니다."
      testId="login"
      footer={
        <p>
          {form && '계정은 팀장이 발급합니다 · '}
          <a
            href="/"
            className="text-primary underline-offset-4 hover:underline"
            onClick={(event) => {
              event.preventDefault()
              navigate('/')
            }}
          >
            소개로 돌아가기
          </a>
        </p>
      }
    >
      {reason === 'expired' && <Notice tone="warning">로그인이 만료되었습니다. 다시 로그인해 주십시오.</Notice>}
      {reason === 'signed-out' && <Notice tone="primary">로그아웃되었습니다.</Notice>}
      {session.state.status === 'offline' && <Notice tone="danger">{OFFLINE_TEXT}</Notice>}
      {notReady && (
        <Notice tone="warning">
          아직 팀장 계정이 없습니다. 배포 안내(docs/operations.md(배포))의 '첫 관리자 만들기'를 따라 주십시오.
        </Notice>
      )}
      {quick && (
        <>
          <QuickChoices busy={quickBusy(busy)} onChoose={(role) => void enter(role, () => session.quick(role))} />
          {failure?.from === 'quick' && (
            <p role="alert" className="mt-3 text-sm text-danger" data-testid="login-error">
              {failure.text}
            </p>
          )}
        </>
      )}
      {form && loginForm}
      {form && options?.demo_login && (
        <div className="mt-6 border-t border-border pt-6">
          <Button
            variant="outline"
            size="lg"
            className="h-10 w-full"
            onClick={() => void enter('demo', () => session.demo())}
            disabled={busy !== null}
            data-testid="login-demo"
          >
            {busy === 'demo' ? '체험 계정으로 들어가는 중입니다…' : '체험 계정으로 둘러보기'}
          </Button>
          <p className="mt-2 text-center text-xs text-foreground-secondary">
            합성 데이터만 볼 수 있으며, 엑셀 가져오기·지도 전환은 할 수 없습니다.
          </p>
        </div>
      )}
    </AuthCard>
  )
}
