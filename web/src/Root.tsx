// 화면 입구(docs/operations.md(서비스) 3절): / 소개 → /login 로그인 → /app 업무 화면. 업무 화면은 로그인한 뒤에만, 따로 묶어
// 늦게 불러온다(소개·로그인이 그래프·차트 묶음을 기다리지 않게). 첫 로그인·초기화 뒤에는 비밀번호부터 바꾼다.
import { lazy, Suspense, useEffect } from 'react'
import { LandingPage } from '@/pages/landing/LandingPage'
import { LoginPage } from '@/pages/login/LoginPage'
import { PasswordGate } from '@/pages/login/PasswordGate'
import { OFFLINE_TEXT } from '@/pages/login/loginErrors'
import { SESSION_CHECK_TEXT, Splash } from '@/pages/login/Splash'
import { can } from '@/lib/account'
import { APP_PATH, landingPath, loginPath, parseRoute } from '@/lib/route'
import { SessionContext } from '@/state/sessionContext'
import { navigate, useLocation } from '@/state/useRoute'
import { useSession } from '@/state/useSession'

const WorkApp = lazy(() => import('./App'))
const ManageApp = lazy(() => import('./pages/manage/ManagePage'))
const ReportApp = lazy(() => import('./pages/report/ReportPage'))

export function Root() {
  const { pathname, search } = useLocation()
  const session = useSession()
  const route = parseRoute(pathname, search)
  const { state } = session

  // 경로 바로잡기: 모르는 경로 → 소개, 로그인한 채 로그인 화면 → 돌아갈 곳, 로그인 안 한 채 업무 화면 → 로그인
  // 관리자(결재자)의 첫 화면은 결재·현황, 결재·현황은 관리자만(그 밖은 업무 화면으로)
  const approver = state.status === 'signed-in' && can(state.me, 'approve')
  const target =
    'redirect' in route
      ? route.redirect
      : route.page === 'login' && state.status === 'signed-in'
        ? landingPath(route.next, approver)
        : (route.page === 'app' || route.page === 'manage' || route.page === 'report') && state.status === 'anonymous'
          ? loginPath(`${pathname}${search}`, state.reason) // 리포트·결재·현황 주소도 그대로 돌아오게
          : route.page === 'manage' && state.status === 'signed-in' && !approver
            ? APP_PATH
            : null
  useEffect(() => {
    if (target) navigate(target, { replace: true })
  }, [target])
  if (target || 'redirect' in route) return null

  if (route.page === 'landing') {
    return (
      <LandingPage
        session={session}
        onLogin={() => navigate('/login')}
        onEnter={() => navigate(landingPath(APP_PATH, approver))}
      />
    )
  }
  if (route.page === 'login') {
    // 로그인되면 위 경로 바로잡기가 첫 화면으로 보낸다(관리자 = 결재·현황, 그 밖 = 업무 화면 · 고른 주소가 있으면 그곳)
    return <LoginPage session={session} reason={route.reason} onSignedIn={() => undefined} />
  }
  if (state.status === 'loading') return <Splash text={SESSION_CHECK_TEXT} />
  // 상태 확인 실패도 로그인 전 화면이라 로그인 화면과 같은 합니다체 문구(서버·연결 오류 문구를 그대로 쓰지 않음)
  if (state.status === 'offline') return <Splash text={OFFLINE_TEXT} onRetry={session.retry} />
  if (state.status !== 'signed-in') return null
  if (state.me.must_change_password) return <PasswordGate session={session} me={state.me} />
  if (route.page === 'report' && route.report) {
    return (
      <Suspense fallback={<Splash text="검토서를 여는 중…" />}>
        <ReportApp ecnId={route.report.ecnId} revision={route.report.revision} />
      </Suspense>
    )
  }
  return (
    <SessionContext.Provider value={{ me: state.me, session }}>
      {route.page === 'manage' ? (
        <Suspense fallback={<Splash text="결재·현황을 여는 중…" />}>
          <ManageApp />
        </Suspense>
      ) : (
        <Suspense fallback={<Splash text="업무 화면을 여는 중…" />}>
          <WorkApp />
        </Suspense>
      )}
    </SessionContext.Provider>
  )
}
