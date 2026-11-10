// 첫 로그인·비밀번호 초기화 뒤: 업무 화면 대신 새 비밀번호 정하기 카드 하나(다른 일은 서버도 403으로 막는다).
import type { Me } from '@/api/client'
import { Button } from '@/components/ui/button'
import { whoLabel } from '@/lib/account'
import type { Session } from '@/state/useSession'
import { AuthCard } from './AuthCard'
import { PasswordForm } from './PasswordForm'

export function PasswordGate({ session, me }: { session: Session; me: Me }) {
  return (
    <AuthCard
      title="새 비밀번호 정하기"
      testId="password-gate"
      description={
        <>
          {whoLabel(me)} 님, 처음 로그인했거나 비밀번호가 초기화되었습니다. 받은 비밀번호 대신 본인만 아는
          비밀번호를 정해 주십시오.
        </>
      }
      footer={
        <button
          type="button"
          className="text-primary underline-offset-4 hover:underline"
          onClick={() => void session.logout()}
        >
          다른 계정으로 로그인
        </button>
      }
    >
      <PasswordForm
        session={session}
        loginId={me.login_id}
        currentLabel="받은 비밀번호"
        onDone={() => undefined}
        actions={({ busy }) => (
          <Button type="submit" size="lg" className="h-10 w-full" disabled={busy}>
            {busy ? '변경하는 중입니다…' : '비밀번호 정하고 들어가기'}
          </Button>
        )}
      />
    </AuthCard>
  )
}
