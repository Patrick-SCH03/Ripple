// '엑셀로 내보내기' 단추(상세 판정 줄 · 결재·현황 머리): 서버가 만든 엑셀(숫자는 분석·결재 결과 그대로)을 받아 파일로
// 저장한다. 받는 동안 단추를 막고 도는 아이콘, 결과는 단추 옆에 알린다(성공은 잠깐, 실패는 다시 누를 때까지).
import { FileDown, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, type Download } from '@/api/client'
import { Button } from '@/components/ui/button'
import { saveBlob } from '@/lib/download'

type Status = { kind: 'idle' | 'busy' | 'done' } | { kind: 'failed'; message: string }

interface Props {
  /** 파일을 받아 온다(서버 요청). */
  load: () => Promise<Download>
  /** 서버가 이름을 주지 않을 때의 파일 이름. */
  fallbackName: string
  /** 좁은 화면·태블릿이면 터치 높이(44px). */
  compact?: boolean
  disabled?: boolean
  testId?: string
}

export function ExcelExportButton({ load, fallbackName, compact = false, disabled = false, testId }: Props) {
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  useEffect(() => {
    if (status.kind !== 'done') return
    const timer = window.setTimeout(() => setStatus({ kind: 'idle' }), 2500)
    return () => window.clearTimeout(timer)
  }, [status])
  const busy = status.kind === 'busy'
  const run = async () => {
    setStatus({ kind: 'busy' })
    try {
      const { blob, filename } = await load()
      saveBlob(blob, filename ?? fallbackName)
      setStatus({ kind: 'done' })
    } catch (caught) {
      setStatus({ kind: 'failed', message: caught instanceof ApiError ? caught.message : String(caught) })
    }
  }
  return (
    <div className="flex items-center gap-2">
      <span role="status" aria-live="polite" className="text-sm">
        {status.kind === 'done' && <span className="text-foreground-secondary">엑셀 파일 내려받음</span>}
        {status.kind === 'failed' && <span className="text-danger">내보내기 실패 · {status.message}</span>}
      </span>
      <Button
        size="sm"
        variant="outline"
        className={compact ? 'h-11 px-3' : undefined}
        disabled={disabled || busy}
        onClick={() => void run()}
        data-testid={testId}
      >
        {busy ? <LoaderCircle aria-hidden className="animate-spin" /> : <FileDown aria-hidden />}
        엑셀로 내보내기
      </Button>
    </div>
  )
}
