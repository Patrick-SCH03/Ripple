// 요약 복사: 판정·비용·마감일·할 일을 메신저용 몇 줄로 복사한다(글은 lib/briefing.ts). 결과는 단추 옆에 잠깐 알린다.
import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { AnalysisResult } from '@/api/client'
import { Button } from '@/components/ui/button'
import { briefingText } from '@/lib/briefing'
import { copyText } from '@/state/useMailer'

/** compact: 좁은 화면·태블릿이면 터치 높이(44px, DESIGN.md 9절). */
export function BriefingCopy({ result, compact = false }: { result: AnalysisResult; compact?: boolean }) {
  const [status, setStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  useEffect(() => {
    if (status === 'idle') return
    const timer = window.setTimeout(() => setStatus('idle'), 2500)
    return () => window.clearTimeout(timer)
  }, [status])
  return (
    <div className="flex items-center gap-2">
      <span role="status" aria-live="polite" className="text-sm text-foreground-secondary">
        {status === 'copied' && '복사됨 · 메신저에 붙여 넣기'}
        {status === 'failed' && '복사 실패'}
      </span>
      <Button
        size="sm"
        variant="outline"
        className={compact ? 'h-11 px-3' : undefined}
        onClick={() => void copyText(briefingText(result)).then((ok) => setStatus(ok ? 'copied' : 'failed'))}
      >
        {status === 'copied' ? <Check aria-hidden /> : <Copy aria-hidden />}
        요약 복사
      </Button>
    </div>
  )
}
