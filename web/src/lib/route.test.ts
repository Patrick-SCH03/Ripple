import { describe, expect, it } from 'vitest'
import { can } from './account'
import { MANAGE_PATH, landingPath, loginPath, parseRoute, safeNext } from './route'

describe('parseRoute', () => {
  it('소개 · 로그인 · 업무 화면, 끝의 /는 무시', () => {
    expect(parseRoute('/', '')).toMatchObject({ page: 'landing' })
    expect(parseRoute('/login', '')).toMatchObject({ page: 'login', next: '/app', reason: null })
    expect(parseRoute('/login/', '?reason=expired')).toMatchObject({ page: 'login', reason: 'expired' })
    expect(parseRoute('/app', '')).toMatchObject({ page: 'app' })
    expect(parseRoute('/app/', '')).toMatchObject({ page: 'app' })
  })

  it('알 수 없는 경로는 소개로', () => {
    expect(parseRoute('/admin', '')).toEqual({ redirect: '/' })
    expect(parseRoute('/application', '')).toEqual({ redirect: '/' })
  })

  it('모르는 이유는 버림', () => {
    expect(parseRoute('/login', '?reason=hacked')).toMatchObject({ reason: null })
  })

  it('판단 리포트: /app/report/<ECN>/<개정>, 형식이 틀리면 업무 화면으로', () => {
    expect(parseRoute('/app/report/ECN-D-0119/3', '')).toMatchObject({
      page: 'report',
      report: { ecnId: 'ECN-D-0119', revision: 3 },
    })
    expect(parseRoute('/app/report/ECN%2DD-0119/1/', '')).toMatchObject({ page: 'report', report: { ecnId: 'ECN-D-0119' } })
    expect(parseRoute('/app/report/ECN-D-0119/0', '')).toEqual({ redirect: '/app' })
    expect(parseRoute('/app/report/..%2F..%2Fx/1', '')).toEqual({ redirect: '/app' })
    expect(parseRoute('/app/report/%E0%A4%A/1', '')).toEqual({ redirect: '/app' })
    expect(parseRoute('/app/report/ECN-D-0119', '')).toMatchObject({ page: 'app' })
  })
})

describe('safeNext', () => {
  it('업무 화면 경로만 받는다', () => {
    expect(safeNext('/app')).toBe('/app')
    expect(safeNext('/app?ecn=ECN-D-0119')).toBe('/app?ecn=ECN-D-0119')
    expect(safeNext('/app/x')).toBe('/app/x')
  })

  it('다른 사이트·비슷한 이름·이중 슬래시·역슬래시는 /app', () => {
    for (const bad of ['https://evil.example', '//evil.example', '/application', '/app.evil.example', '/app//evil', '/app\\evil', '', null, undefined]) {
      expect(safeNext(bad)).toBe('/app')
    }
  })
})

describe('loginPath', () => {
  it('리포트 주소는 로그인 뒤 그대로 돌아온다', () => {
    expect(loginPath('/app/report/ECN-D-0119/3')).toBe('/login?next=%2Fapp%2Freport%2FECN-D-0119%2F3')
    expect(parseRoute('/login', '?next=%2Fapp%2Freport%2FECN-D-0119%2F3')).toMatchObject({
      next: '/app/report/ECN-D-0119/3',
    })
  })

  it('기본은 /login, 이유·돌아갈 곳을 붙인다', () => {
    expect(loginPath()).toBe('/login')
    expect(loginPath('/app', 'expired')).toBe('/login?reason=expired')
    expect(loginPath('/app?x=1', null)).toBe('/login?next=%2Fapp%3Fx%3D1')
    expect(loginPath('https://evil.example', 'signed-out')).toBe('/login?reason=signed-out')
  })

  it('만든 경로를 다시 읽으면 같은 곳', () => {
    const path = loginPath('/app?ecn=1', 'expired')
    const [pathname, search] = path.split('?')
    expect(parseRoute(pathname, `?${search}`)).toMatchObject({ page: 'login', next: '/app?ecn=1', reason: 'expired' })
  })
})

describe('landingPath', () => {
  it('결재자(팀장·파트장·본부장 — 승인 권한)는 결재·현황(결재함)으로, 담당자는 업무 화면, 고른 주소는 그대로', () => {
    const who = (role: 'admin' | 'member' | 'part_lead' | 'executive', permissions: ('view' | 'record' | 'approve')[]) => ({
      login_id: role,
      name: role,
      role,
      must_change_password: false,
      permissions,
    })
    const first = (me: ReturnType<typeof who>) => landingPath('/app', can(me, 'approve'))
    expect(first(who('part_lead', ['view', 'approve']))).toBe(MANAGE_PATH)
    expect(first(who('executive', ['view', 'approve']))).toBe(MANAGE_PATH)
    expect(first(who('admin', ['view', 'approve']))).toBe(MANAGE_PATH)
    expect(first(who('member', ['view', 'record']))).toBe('/app')
    expect(landingPath('/app/report/ECN-D-0119/1', true)).toBe('/app/report/ECN-D-0119/1')
  })
})
