// 엑셀 가져오기 대화상자의 단계 전환(파일 읽기 · 열 고침 · 시트 다시 제안 · 이대로 읽기 · 전환/갱신).
// 가져오기 상태 버전: 서버는 덮어쓰기·읽기마다 버전을 올리고 지금 버전에서 오류 없이 읽은 결과만 확정한다. 화면은
// 마지막 응답의 버전을 들고 다닌다. 대화상자 세대: 닫거나 다른 파일을 고를 때마다 올리고, 응답은 보낸 때의 세대일
// 때만 반영한다(늦은 응답이 새 파일의 화면을 덮지 않게). 지도 전환 자체는 useWorkspace가 적용한다.
// 반환은 단계마다 묶는다: file = 파일 고르기·끌어 놓기, mapping = 열 확인, report = 품질 리포트.
import { useRef, useState } from 'react'
import {
  ApiError,
  api,
  type ConfirmedMapping,
  type ImportPreview,
  type MappingOverrides,
  type StatusImportPreview,
} from '@/api/client'
import { useFilePick } from '@/components/common/useFilePick'
import { ScreenGeneration } from '@/lib/generation'
import { initialChoices, toMapping, type ColumnChoice } from '@/lib/mapping'
import type { WorkspaceState } from '@/state/useWorkspace'
import type { ImportMode, Review, Step } from './steps'
import { FILE_BEFORE, STALE_PREVIEW, failureText } from './text'

/** 반환의 status = 상태 올리기인가(읽기·제안·이대로 읽기를 지금 지도 쪽 API로 보낸다). 대화상자도 이 값으로 안내를 가른다. */
export function useImportFlow(workspace: WorkspaceState, mode: ImportMode, onOpenChange: (open: boolean) => void) {
  const status = mode === 'status'
  const io = {
    stage: (file: File, signal?: AbortSignal) =>
      status ? api.stageStatusImport(file, file.name, signal) : workspace.stage(file, signal),
    propose: (importId: string, overrides: MappingOverrides) =>
      status ? api.proposeStatusImport(importId, overrides) : workspace.propose(importId, overrides),
  }
  const [step, setStep] = useState<Step>({ kind: 'choose' })
  const reading = useRef<AbortController | null>(null)
  const [session] = useState(() => new ScreenGeneration())

  // 닫으면 읽던 요청을 멈추고 처음 단계로(다시 열면 파일 고르기부터)
  const changeOpen = (next: boolean) => {
    if (!next) {
      session.bump()
      reading.current?.abort()
      setStep({ kind: 'choose' })
      file.setDragging(false)
    }
    onOpenChange(next)
  }

  const read = async (picked: File) => {
    session.bump()
    reading.current?.abort()
    const controller = new AbortController()
    reading.current = controller
    setStep({ kind: 'reading', name: picked.name })
    try {
      const proposal = await io.stage(picked, controller.signal)
      if (controller.signal.aborted) return
      const review = { proposal, choices: initialChoices(proposal), version: proposal.version }
      // 같은 모양의 파일로 전에 확정한 매핑이 있으면 열 확인 없이 그 매핑으로 바로 읽는다(열 매핑 기억)
      if (proposal.remembered) {
        void submit(review, { mapping: proposal.remembered, from: proposal.remembered_from ?? FILE_BEFORE })
        return
      }
      setStep({ kind: 'mapping', review, busy: false, error: null })
    } catch (caught) {
      if (controller.signal.aborted) return
      const error = caught instanceof ApiError ? caught : new ApiError(String(caught), 0)
      setStep({ kind: 'failed', name: picked.name, error })
    }
  }

  // 열 고침은 지금 열 확인 상태에만(다시 제안·읽기 중이면 받지 않는다 — 늦게 온 응답이 고친 것을 되돌리지 않게)
  const setColumn = (sheet: string, position: number, choice: ColumnChoice) => {
    setStep((current) => {
      if (current.kind !== 'mapping' || current.busy) return current
      const before = current.review.choices[sheet]
      if (!before) return current
      const choices = { ...current.review.choices, [sheet]: { ...before, columns: { ...before.columns, [position]: choice } } }
      return { ...current, review: { ...current.review, choices }, error: null }
    })
  }

  // 시트 상태·머리글 행을 바꾸면 서버가 그 시트를 다시 제안한다(다른 시트의 고침은 남김)
  const setSheet = async (review: Review, sheet: string, template: string | null, headerRows: number[] | null) => {
    const stamp = session.current
    setStep({ kind: 'mapping', review, busy: true, error: null })
    try {
      const proposal = await io.propose(review.proposal.import_id, {
        version: review.version,
        sheets: [{ file_sheet: sheet, template, header_rows: headerRows }],
      })
      if (!session.isCurrent(stamp)) return
      const next = { proposal, choices: initialChoices(proposal, review.choices), version: proposal.version }
      setStep({ kind: 'mapping', review: next, busy: false, error: null })
    } catch (caught) {
      if (!session.isCurrent(stamp)) return
      setStep({ kind: 'mapping', review, busy: false, error: failureText(caught) })
    }
  }

  const submit = async (review: Review, remembered?: { mapping: ConfirmedMapping; from: string }) => {
    const stamp = session.current
    setStep({ kind: 'mapping', review, busy: true, error: null })
    try {
      const mapping = remembered?.mapping ?? toMapping(review.proposal, review.choices)
      const from = remembered?.from ?? null
      if (status) {
        const result = await api.submitStatusImport(review.proposal.import_id, review.version, mapping)
        if (!session.isCurrent(stamp)) return
        const next = { ...review, version: result.version ?? review.version }
        setStep({ kind: 'status-report', review: next, result, failure: null, remembered: from })
        return
      }
      const preview = await workspace.submit(review.proposal.import_id, review.version, mapping)
      if (!session.isCurrent(stamp)) return
      const next = { ...review, version: preview.version ?? review.version }
      setStep({ kind: 'report', review: next, preview, failure: null, remembered: from })
    } catch (caught) {
      if (!session.isCurrent(stamp)) return
      setStep({ kind: 'mapping', review, busy: false, error: failureText(caught) })
    }
  }

  const confirm = async (review: Review, preview: ImportPreview) => {
    if (!preview.import_id || !preview.version) return
    const stamp = session.current
    const failure = await workspace.confirm(preview.import_id, preview.version)
    if (!session.isCurrent(stamp)) return // 그사이 닫았거나 다른 파일을 골랐다
    if (failure) setStep({ kind: 'report', review, preview, failure })
    else changeOpen(false)
  }

  const confirmStatus = async (review: Review, result: StatusImportPreview, remembered: string | null) => {
    if (!result.import_id || !result.version) return
    const stamp = session.current
    const { event, failure } = await workspace.confirmStatus(result.import_id, result.version)
    if (!session.isCurrent(stamp)) return
    if (event) {
      changeOpen(false)
      return
    }
    // 반영하지 않음: 실패, 또는 미리보기 뒤에 지도가 바뀜(409 — 모르는 변경을 덮어쓰지 않게). 다시 읽어 새 미리보기로
    const stale = new ApiError(STALE_PREVIEW, 409)
    setStep({ kind: 'status-report', review, result: { ...result, import_id: null }, failure: failure ?? stale, remembered })
  }

  /** 리포트에서 '열 확인으로 돌아가기'. */
  const backToMapping = (review: Review) => setStep({ kind: 'mapping', review, busy: false, error: null })

  // 고르거나 끌어 놓은 파일을 읽는다(read가 부르는 submit까지 정의된 뒤에 묶는다)
  const file = useFilePick((picked) => void read(picked))

  return {
    status,
    step,
    changeOpen,
    file,
    mapping: { setColumn, setSheet, submit },
    report: { back: backToMapping, confirm, confirmStatus },
  }
}
