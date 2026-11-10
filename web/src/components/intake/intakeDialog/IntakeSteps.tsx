// 문서로 넣기의 앞 단계 그리기: 지도 대조 맥락 한 줄 · 붙여 넣기(12,000자 세기) · 변경 리스트 엑셀 끌어 놓기 · 읽는 중.
import { FileSpreadsheet, FileUp, LoaderCircle } from 'lucide-react'
import type { TurnContext } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { formatDay } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DocumentEntry } from './useIntakeFlow'

const MAX_CHARS = 12_000

/** 호선·기준일이 없으면 넣을 수 없다는 경고, 있으면 대조할 지도와 읽는 길(AI·규칙). */
export function ContextLine({
  context,
  dataMode,
  aiOn,
}: {
  context: TurnContext | null
  dataMode: 'synthetic' | 'real' | null
  aiOn: boolean
}) {
  return (
    <>
      {!context && (
        <p role="alert" className="rounded-md border border-warning/40 bg-warning/8 px-3 py-2">
          호선·기준일 미정 · 목록에서 설계변경을 고르거나 분석 기준을 정한 뒤 넣기
        </p>
      )}
      {context && (
        <p className="text-sm text-foreground-secondary">
          {context.ship_ids.join(', ')} · 기준일 {formatDay(context.as_of)} 지도와 대조{' '}
          {dataMode === 'real'
            ? '실제 데이터 지도 — 외부 AI 없이 규칙으로만'
            : aiOn
              ? 'AI가 항목 추출 → 규칙 해석기로 재확인 · 확정은 사람'
              : 'AI 외부 호출 꺼짐 — 규칙으로만 · 확정은 사람'}
        </p>
      )}
    </>
  )
}

interface InputProps {
  error: string | null
  compact: boolean
  entry: DocumentEntry
}

export function DocumentInput({ error, compact, entry }: InputProps) {
  const { text, file } = entry
  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      <label className="block space-y-1" htmlFor="intake-text">
        <span className="text-sm font-medium">문서 붙여 넣기</span>
        <Textarea
          id="intake-text"
          value={text}
          maxLength={MAX_CHARS}
          rows={compact ? 6 : 9}
          placeholder={'예) ECN No. 2026-034 Rev.B\n1. B31P 갑판 PL-002 두께 17mm → 20mm\n2. 밸브 V-12 사양 변경'}
          onChange={(event) => entry.setText(event.target.value)}
          className="max-h-[40vh] min-h-32 font-sans"
          data-testid="intake-text"
        />
        <span className="block text-right text-xs text-foreground-secondary tabular-nums">
          {text.length.toLocaleString('ko-KR')} / {MAX_CHARS.toLocaleString('ko-KR')}자
        </span>
      </label>
      <div
        onDragOver={(event) => {
          event.preventDefault()
          file.setDragging(true)
        }}
        onDragLeave={() => file.setDragging(false)}
        onDrop={file.drop}
        className={cn(
          'flex flex-wrap items-center gap-2 rounded-md border border-dashed border-border-strong px-3 py-3 text-sm',
          file.dragging && 'border-primary bg-primary/8',
        )}
      >
        <FileSpreadsheet aria-hidden className="size-4 text-foreground-secondary" />
        <span className="text-foreground-secondary">변경 리스트 엑셀(첫 행 = 머리글)을 끌어 놓거나</span>
        <Button
          variant="outline"
          size="sm"
          onClick={file.pick}
          disabled={!entry.ready}
          className={compact ? 'h-11' : undefined}
        >
          <FileUp aria-hidden />
          엑셀 고르기
        </Button>
      </div>
    </div>
  )
}

export function ReadingStatus({ label }: { label: string }) {
  return (
    <div role="status" className="flex flex-col items-center gap-2 py-6 text-center text-foreground-secondary">
      <LoaderCircle aria-hidden className="size-5 animate-spin text-agent" />
      <p>
        <span className="font-medium text-foreground">{label}</span>
        에서 항목을 나누고 지도와 대조하는 중…
      </p>
      <p className="text-xs">AI 읽기 최대 45초 · 넘으면 규칙으로만</p>
    </div>
  )
}
