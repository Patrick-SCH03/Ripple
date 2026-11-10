// 아이디·비밀번호 입력 칸과 로그인 단추(LoginPage가 상태·흐름을 갖고 그리기만 맡긴다). 비밀번호 보기 단추는 이 안의 상태.
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  loginId: string
  password: string
  /** 실패 문구(서버 문구 그대로). 있으면 두 칸을 틀린 칸으로 표시한다. */
  error: string | null
  /** 아무 들어가기(로그인·체험)든 진행 중이면 단추를 막는다. */
  busy: boolean
  /** 이 폼의 로그인이 진행 중인가(단추 문구). */
  signingIn: boolean
  onLoginId: (value: string) => void
  onPassword: (value: string) => void
  onSubmit: (event: FormEvent) => void
}

export function LoginForm({
  loginId,
  password,
  error,
  busy,
  signingIn,
  onLoginId,
  onPassword,
  onSubmit,
}: Props) {
  const ids = { login: useId(), password: useId(), error: useId() }
  const [shown, setShown] = useState(false)
  const described = error ? ids.error : undefined
  return (
    <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.login} className="text-sm font-medium">
          아이디
        </label>
        <Input
          id={ids.login}
          name="username"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          value={loginId}
          onChange={(event) => onLoginId(event.target.value)}
          aria-invalid={!!error}
          aria-describedby={described}
          className="h-10"
          data-testid="login-id"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={ids.password} className="text-sm font-medium">
          비밀번호
        </label>
        <div className="relative">
          <Input
            id={ids.password}
            name="password"
            type={shown ? 'text' : 'password'}
            autoComplete="current-password"
            value={password}
            onChange={(event) => onPassword(event.target.value)}
            aria-invalid={!!error}
            aria-describedby={described}
            className="h-10 pr-10"
            data-testid="login-password"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute top-1 right-1"
            aria-label={shown ? '비밀번호 가리기' : '비밀번호 보기'}
            aria-pressed={shown}
            onClick={() => setShown((value) => !value)}
          >
            {shown ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
          </Button>
        </div>
      </div>
      {error && (
        <p id={ids.error} role="alert" className="text-sm text-danger" data-testid="login-error">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" className="h-10 w-full" disabled={busy}>
        <LogIn aria-hidden />
        {signingIn ? '로그인하는 중입니다…' : '로그인'}
      </Button>
    </form>
  )
}
