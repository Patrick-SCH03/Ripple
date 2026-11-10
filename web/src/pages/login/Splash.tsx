// 기다림·연결 실패 화면(로그인 상태 확인, 업무 화면 묶음 불러오기).
import { RotateCw } from 'lucide-react'
import { BrandMark } from '@/components/common/BrandMark'
import { Button } from '@/components/ui/button'

/** 로그인 상태 확인 중: 로그인 전에도 보이는 화면이라 소개·로그인과 같은 합니다체(DESIGN.md 12절). */
export const SESSION_CHECK_TEXT = '로그인 상태를 확인하고 있습니다…'

export function Splash({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <main className="rp-fixed-type flex min-h-dvh flex-col items-center justify-center gap-3 bg-canvas p-6 text-sm text-foreground-secondary">
      <BrandMark size={40} />
      <p role="status">{text}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          <RotateCw aria-hidden />
          다시 확인하기
        </Button>
      )}
    </main>
  )
}
