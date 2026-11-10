// 변경 입력(오른쪽 칸): 목록에서 고른 설계변경의 분석 요청 JSON을 고쳐 다시 계산한다.
// C5에서 AI 비서(자연어 입력)가 이 칸을 맡고, JSON은 개발용 펼침으로 내려간다.
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { parseRequest } from '@/lib/request'

interface Props {
  draft: string
  busy: boolean
  onEdit: (text: string) => void
  onRun: () => void
}

const REQUEST_EDITOR_ID = 'request-json'

export function RequestEditor({ draft, busy, onEdit, onRun }: Props) {
  const parsed = parseRequest(draft)
  return (
    <div className="flex h-full min-h-80 flex-col gap-2 p-4">
      <p className="text-sm text-foreground-secondary">고른 설계변경의 분석 요청 · 고쳐서 다시 계산 가능</p>
      <label htmlFor={REQUEST_EDITOR_ID} className="mt-1 text-sm font-medium">
        요청 JSON
      </label>
      <Textarea
        id={REQUEST_EDITOR_ID}
        spellCheck={false}
        value={draft}
        onChange={(event) => onEdit(event.target.value)}
        aria-invalid={parsed.ok ? undefined : true}
        aria-describedby={parsed.ok ? undefined : `${REQUEST_EDITOR_ID}-problem`}
        className="min-h-48 flex-1 resize-none rounded-sm bg-muted font-mono text-xs leading-[1.45] field-sizing-fixed md:text-xs"
      />
      {!parsed.ok && (
        <p id={`${REQUEST_EDITOR_ID}-problem`} className="text-sm text-danger">
          {parsed.reason}
        </p>
      )}
      <Button className="h-9" disabled={!parsed.ok || busy} onClick={onRun}>
        {busy ? '계산하는 중…' : '분석 보기'}
      </Button>
    </div>
  )
}
