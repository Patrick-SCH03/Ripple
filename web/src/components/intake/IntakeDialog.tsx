// 문서로 넣기(docs/input.md(문서 접수), DESIGN.md 6절): 설계변경 문서(붙여 넣기)나 변경 리스트 엑셀 → AI·규칙이 항목을 뽑아 지도와
// 대조한 확인표 → 사람이 항목마다 맞음·고침·비서로·뺌 → 서버가 다시 검증해 여러 항목짜리 변경 하나로 분석한다.
// 자동 진행은 없다(항상 사람 확인). 대화상자 세대: 닫거나 새 문서를 읽을 때마다 올리고, 응답은 보낸 때의 세대일 때만
// 반영한다(늦은 응답이 새 문서의 확인표를 덮지 않게). 확정하면 상세가 그 분석으로 바뀐다. 왼쪽 버튼은 '닫기'.
// 단계 전환은 intakeDialog/useIntakeFlow, 앞 단계 그리기는 intakeDialog/IntakeSteps.
import type { AnalysisRequest, AnalysisResult, TurnContext } from '@/api/client'
import { FileInput } from '@/components/common/FileInput'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { acceptClean, canConfirm, readiness } from '@/lib/intake'
import { cn } from '@/lib/utils'
import { ContextLine, DocumentInput, ReadingStatus } from './intakeDialog/IntakeSteps'
import { useIntakeFlow } from './intakeDialog/useIntakeFlow'
import { IntakeReview } from './IntakeReview'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 지도 대조 맥락(호선·기준일). 없으면 넣을 수 없다. */
  context: TurnContext | null
  dataMode: 'synthetic' | 'real' | null
  /** 외부 AI 호출이 켜져 있는가(꺼져 있으면 규칙으로만 나눈다고 안내). */
  aiOn: boolean
  compact: boolean
  onAnalyzed: (request: AnalysisRequest, result: AnalysisResult) => void
}

export function IntakeDialog({ open, onOpenChange, context, dataMode, aiOn, compact, onAnalyzed }: Props) {
  const { step, changeOpen, entry, stop, table } = useIntakeFlow({ context, onOpenChange, onAnalyzed })

  const review = step.kind === 'review' ? step.review : null
  const state = review ? readiness(review.proposal.items, review.rows) : null
  const ready = state ? canConfirm(state) : false

  return (
    <Dialog open={open} onOpenChange={(next) => changeOpen(next)}>
      <DialogContent
        className={cn(
          'max-h-[92vh] gap-3 overflow-y-auto [scrollbar-gutter:stable]',
          review ? 'sm:max-w-4xl' : 'sm:max-w-2xl',
        )}
        data-testid="intake-dialog"
      >
        <DialogHeader>
          <DialogTitle>{review ? '문서로 넣기 — 확인표' : '문서로 넣기'}</DialogTitle>
          <DialogDescription>
            설계변경 문서·변경 리스트 → 항목별로 지도와 대조 · 항목마다 확인 후 한 번에 분석
          </DialogDescription>
        </DialogHeader>
        <FileInput file={entry.file} label="변경 리스트 엑셀" />

        <ContextLine context={context} dataMode={dataMode} aiOn={aiOn} />

        {step.kind === 'input' && <DocumentInput error={step.error} compact={compact} entry={entry} />}

        {step.kind === 'reading' && <ReadingStatus label={step.label} />}

        {review && state && (
          <IntakeReview
            review={review}
            context={context}
            compact={compact}
            onRow={table.setRow}
            onHeader={(header) => table.update({ header })}
            onContinue={(continueEcn) => table.update({ continueEcn })}
            onAcceptClean={() => table.update({ rows: acceptClean(review.proposal.items, review.rows) })}
            reasons={state.reasons}
          />
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
          {step.kind === 'reading' && (
            <Button variant="outline" onClick={stop}>
              멈추기
            </Button>
          )}
          {step.kind === 'input' && (
            <Button onClick={entry.read} disabled={!entry.canRead} data-testid="intake-read">
              항목 나누기
            </Button>
          )}
          {review && (
            <>
              <Button variant="outline" onClick={table.restart} disabled={review.busy}>
                다른 문서 넣기
              </Button>
              <Button
                onClick={() => void table.confirm(review)}
                disabled={!ready || review.busy || !context}
                data-testid="intake-confirm"
              >
                {review.busy
                  ? '분석하는 중…'
                  : ready
                    ? `${state?.kept ?? 0}개 항목으로 분석`
                    : `정할 것 ${state?.reasons.length ?? 0}개 남음`}
              </Button>
            </>
          )}
        </DialogFooter>
        {review?.error && (
          <p role="alert" className="text-right text-sm text-danger">
            {review.error}
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
