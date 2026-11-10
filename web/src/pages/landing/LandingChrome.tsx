// 소개 화면의 위 막대(로고 · 목차 · 로그인/업무 화면으로)와 바닥(출품 안내 · 합성 데이터 표시 · 바닥 목차).
import { BrandMark } from '@/components/common/BrandMark'
import { Button } from '@/components/ui/button'
import { FOOTER_NAV, NAV } from './content'
import { FULL } from './layout'

/** scrolled: 조금이라도 내렸으면 막대 아래에 선을 긋는다. */
export function LandingHeader({
  scrolled,
  signedIn,
  onEnter,
  onLogin,
}: {
  scrolled: boolean
  signedIn: boolean
  onEnter: () => void
  onLogin: () => void
}) {
  return (
    <header
      className={`sticky top-0 z-20 -mt-px border-b bg-surface transition-colors duration-200 ${
        scrolled ? 'border-border' : 'border-transparent'
      }`}
    >
      <div className={`${FULL} flex h-16 items-center gap-4`}>
        <a href="/" className="flex shrink-0 items-center gap-2 rounded-sm text-foreground no-underline">
          <BrandMark size={28} className="shrink-0" />
          <span className="text-lg font-bold tracking-tight">Ripple</span>
        </a>
        <nav aria-label="소개 목차" className="hidden flex-1 items-center justify-center lg:flex">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="rounded-md px-2.5 py-2 text-sm font-medium whitespace-nowrap text-foreground-secondary hover:bg-muted hover:text-foreground xl:px-3.5 xl:text-md"
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto shrink-0 lg:ml-0">
          {signedIn ? (
            <Button className="h-9 px-4 font-semibold" onClick={onEnter}>
              업무 화면으로
            </Button>
          ) : (
            <Button variant="secondary" className="h-9 px-4 font-semibold" onClick={onLogin}>
              로그인
            </Button>
          )}
        </div>
      </div>
    </header>
  )
}

export function LandingFooter() {
  return (
    <footer className="border-t border-border bg-surface">
      <div className={`${FULL} flex flex-col gap-6 py-10 md:flex-row md:items-start md:justify-between`}>
        <div className="flex flex-col gap-1.5 text-sm text-foreground-secondary">
          <p className="flex items-center gap-2 text-foreground">
            <BrandMark size={22} className="shrink-0" />
            <span className="text-md font-bold tracking-tight">Ripple</span>
          </p>
          <p className="mt-1">2026 K-조선 해커톤 본선 출품작 · 팀 Ripple</p>
          <p>공개 화면과 예시는 합성 데이터입니다.</p>
        </div>
        <nav aria-label="바닥 목차" className="flex max-w-[520px] flex-wrap gap-x-5 gap-y-2 text-sm md:justify-end">
          {FOOTER_NAV.map((item) => (
            <a key={item.href} href={item.href} className="text-foreground-secondary hover:text-foreground">
              {item.label}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  )
}
