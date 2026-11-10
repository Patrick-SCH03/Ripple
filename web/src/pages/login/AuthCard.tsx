// 로그인·비밀번호 정하기·기다림 화면의 공통 틀: 캔버스 가운데 400px 카드, 위에 로고(DESIGN.md 12절).
import type { ReactNode } from 'react'
import { BrandMark } from '@/components/common/BrandMark'

interface Props {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  testId?: string
}

export function AuthCard({ title, description, children, footer, testId }: Props) {
  return (
    <main className="rp-fixed-type flex min-h-dvh flex-col items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-[400px]">
        <a href="/" className="mb-6 flex items-center justify-center gap-2 rounded-sm text-foreground no-underline">
          <BrandMark size={30} className="shrink-0" />
          <span className="text-lg font-semibold tracking-tight">Ripple</span>
        </a>
        <section
          className="rounded-md border border-border bg-surface p-6 sm:p-8"
          aria-labelledby="auth-title"
          data-testid={testId}
        >
          <h1 id="auth-title" className="text-lg font-semibold">
            {title}
          </h1>
          {description && <div className="mt-1 text-sm text-foreground-secondary">{description}</div>}
          <div className="mt-6">{children}</div>
        </section>
        {footer && <div className="mt-4 text-center text-sm text-foreground-secondary">{footer}</div>}
      </div>
    </main>
  )
}

/** 카드 안 알림 상자(정보·주의·오류). 글자는 대비 4.5:1 토큰만. */
export function Notice({ tone, children }: { tone: 'primary' | 'warning' | 'danger'; children: ReactNode }) {
  const color = {
    primary: 'border-primary/40 text-primary',
    warning: 'border-warning/50 text-warning',
    danger: 'border-danger/50 text-danger',
  }[tone]
  return (
    <p role={tone === 'danger' ? 'alert' : 'status'} className={`mb-4 rounded-sm border px-3 py-2 text-sm ${color}`}>
      {children}
    </p>
  )
}
