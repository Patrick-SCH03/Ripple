// 엑셀 가져오기 대화상자(docs/input.md(엑셀 양식) 4절, DESIGN.md 6절): 파일 고르기(끌어 놓기) → 열 확인(시트마다 양식
// 시트·머리글 행, 열마다 양식 항목·원본 단위 — 지정 양식 그대로면 '모든 시트·열이 같아요') → 이대로 읽기 → 품질
// 리포트(오류·확인할 것을 시트·행·열로) → '이 지도로 전환'. 오류가 하나라도 있으면 지도를 만들지 않아 전환 단추가 없고,
// '열 확인으로 돌아가기'로 고쳐 다시 읽는다. 왼쪽 버튼은 '닫기'.
// 단계 전환·버전·대화상자 세대는 importDialog/useImportFlow, 단계마다 그리기는 importDialog/의 부품이 맡는다.
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
import { pending } from '@/lib/mapping'
import { cn } from '@/lib/utils'
import type { WorkspaceState } from '@/state/useWorkspace'
import { ColumnReview } from './ColumnReview'
import { ChooseFile } from './importDialog/ChooseFile'
import { ReportView, StatusReportView } from './importDialog/ImportReports'
import type { ImportMode } from './importDialog/steps'
import { TEXT } from './importDialog/text'
import { useImportFlow } from './importDialog/useImportFlow'

export type { ImportMode } from './importDialog/steps'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspace: WorkspaceState
  mode?: ImportMode
}

export function ImportDialog({ open, onOpenChange, workspace, mode = 'full' }: Props) {
  const { status, step, changeOpen, file, mapping, report } = useImportFlow(workspace, mode, onOpenChange)
  const defaultId = workspace.list?.items.find((item) => item.default)?.snapshot_id ?? null
  const activeId = workspace.list?.active_snapshot_id ?? null

  const blocking = step.kind === 'mapping' ? pending(step.review.proposal, step.review.choices).blocking : 0
  const wide = step.kind === 'mapping' || step.kind === 'report' || step.kind === 'status-report'
  const text = TEXT[mode]

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent
        className={cn('max-h-[92vh] gap-3 overflow-y-auto [scrollbar-gutter:stable]', wide ? 'sm:max-w-4xl' : 'sm:max-w-xl')}
        data-testid="import-dialog"
      >
        <DialogHeader>
          <DialogTitle>{step.kind === 'mapping' ? `${text.title} — 열 확인` : text.title}</DialogTitle>
          <DialogDescription>{text.description}</DialogDescription>
        </DialogHeader>
        <FileInput file={file} label="엑셀 파일" testId="import-file" />

        {step.kind === 'choose' && <ChooseFile status={status} defaultId={defaultId} file={file} />}

        {step.kind === 'reading' && (
          <p role="status" className="py-6 text-center text-foreground-secondary">
            <span className="font-medium text-foreground">{step.name}</span> 파일 읽는 중…
          </p>
        )}

        {step.kind === 'failed' && (
          <div role="alert" className="rounded-md border border-danger/40 bg-danger/8 px-3 py-2">
            <p className="font-semibold">{step.name} 파일 읽기 실패</p>
            <p className="mt-0.5 text-foreground-secondary">{step.error.message}</p>
          </div>
        )}

        {step.kind === 'mapping' && (
          <>
            {step.error && (
              <p role="alert" className="text-danger">
                {step.error}
              </p>
            )}
            <ColumnReview
              proposal={step.review.proposal}
              choices={step.review.choices}
              busy={step.busy}
              onColumn={(sheet, position, choice) => mapping.setColumn(sheet, position, choice)}
              onSheet={(sheet, template, rows) => void mapping.setSheet(step.review, sheet, template, rows)}
            />
          </>
        )}

        {(step.kind === 'report' || step.kind === 'status-report') && step.remembered && (
          <p className="rounded-sm border border-border bg-muted/40 px-3 py-2 text-sm" data-testid="import-remembered">
            지난번 '{step.remembered}'에서 확정한 열 확인 그대로 사용 · 다르게 읽으려면 '열 확인으로 돌아가기'
          </p>
        )}
        {step.kind === 'status-report' && <StatusReportView result={step.result} failure={step.failure} />}
        {step.kind === 'report' && (
          <ReportView
            preview={step.preview}
            failure={step.failure}
            active={!!step.preview.info && step.preview.info.snapshot_id === activeId}
          />
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
          {(step.kind === 'mapping' || step.kind === 'report' || step.kind === 'status-report' || step.kind === 'failed') && (
            <Button variant="outline" onClick={file.pick} disabled={workspace.switching}>
              다른 파일 고르기
            </Button>
          )}
          {(step.kind === 'report' || step.kind === 'status-report') && (
            <Button variant="outline" onClick={() => report.back(step.review)} disabled={workspace.switching}>
              열 확인으로 돌아가기
            </Button>
          )}
          {step.kind === 'mapping' && (
            <Button onClick={() => void mapping.submit(step.review)} disabled={step.busy || blocking > 0}>
              {step.busy ? '읽는 중…' : blocking > 0 ? `정할 것 ${blocking}개 남음` : '이대로 읽기'}
            </Button>
          )}
          {step.kind === 'report' && step.preview.import_id && step.preview.info?.snapshot_id !== activeId && (
            <Button onClick={() => void report.confirm(step.review, step.preview)} disabled={workspace.switching}>
              {workspace.switching ? '바꾸는 중…' : text.confirm}
            </Button>
          )}
          {step.kind === 'status-report' && step.result.import_id && (
            <Button
              onClick={() => void report.confirmStatus(step.review, step.result, step.remembered ?? null)}
              disabled={workspace.switching}
              data-testid="status-confirm"
            >
              {workspace.switching ? '갱신하는 중…' : text.confirm}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
