// 문서로 넣기 대화상자의 단계 전환(붙여 넣기·엑셀 읽기 → 확인표 → 확정). 대화상자 세대: 닫거나 새 문서를 읽을 때마다
// 올리고, 응답은 보낸 때의 세대일 때만 반영한다(늦은 응답이 새 문서의 확인표를 덮지 않게).
// 반환은 단계마다 묶는다: entry = 붙여 넣기, table = 확인표(stop = 읽는 중 '멈추기').
import { useRef, useState } from 'react'
import {
  ApiError,
  api,
  type AnalysisRequest,
  type AnalysisResult,
  type IntakeProposal,
  type TurnContext,
} from '@/api/client'
import { useFilePick, type FilePick } from '@/components/common/useFilePick'
import { ScreenGeneration } from '@/lib/generation'
import { canConfirm, problemsByItem, readiness, type RowState } from '@/lib/intake'
import type { Review } from '../IntakeReview'

type Step =
  { kind: 'input'; error: string | null } | { kind: 'reading'; label: string } | { kind: 'review'; review: Review }

function failureText(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : '서버 연결 실패'
}

interface Options {
  context: TurnContext | null
  onOpenChange: (open: boolean) => void
  onAnalyzed: (request: AnalysisRequest, result: AnalysisResult) => void
}

/** 붙여 넣기 단계(DocumentInput · '항목 나누기'): 붙여 넣은 글과 변경 리스트 엑셀 고르기. */
export interface DocumentEntry {
  /** 붙여 넣은 글(닫아도 남고, 확정하면 비운다). */
  text: string
  setText: (text: string) => void
  /** 변경 리스트 엑셀 고르기·끌어 놓기. */
  file: FilePick
  /** 지도 대조 맥락(호선·기준일)이 있나(없으면 엑셀을 고를 수 없다). */
  ready: boolean
  /** '항목 나누기'를 누를 수 있나(맥락과 글이 있어야). */
  canRead: boolean
  /** 붙여 넣은 글을 나눈다. */
  read: () => void
}

export function useIntakeFlow({ context, onOpenChange, onAnalyzed }: Options) {
  const [step, setStep] = useState<Step>({ kind: 'input', error: null })
  const [text, setText] = useState('')
  const reading = useRef<AbortController | null>(null)
  const [session] = useState(() => new ScreenGeneration())

  // 닫으면 읽던 요청을 멈추고 처음 단계로(붙여 넣은 글은 남겨 다시 열면 이어서). 확정을 보내는 중에는 닫지 않는다 —
  // 서버는 분석을 끝내는데 화면이 결과를 버려 무엇이 됐는지 모르게 되지 않게. done = 확정이 끝나 닫음
  const changeOpen = (next: boolean, done = false) => {
    if (!next && !done && step.kind === 'review' && step.review.busy) return
    if (!next) {
      session.bump()
      reading.current?.abort()
      setStep({ kind: 'input', error: null })
      file.setDragging(false)
    }
    onOpenChange(next)
  }

  const propose = async (label: string, send: (signal: AbortSignal) => Promise<IntakeProposal>) => {
    session.bump()
    reading.current?.abort()
    const controller = new AbortController()
    reading.current = controller
    setStep({ kind: 'reading', label })
    try {
      const proposal = await send(controller.signal)
      if (controller.signal.aborted) return
      const review: Review = {
        proposal,
        rows: {},
        header: proposal.header,
        continueEcn: false,
        busy: false,
        error: null,
        problems: {},
      }
      setStep({ kind: 'review', review })
    } catch (caught) {
      if (controller.signal.aborted) return
      setStep({ kind: 'input', error: failureText(caught) })
    }
  }

  const readText = () => {
    if (!context || !text.trim()) return
    void propose('붙여 넣은 문서', (signal) => api.intakePropose(text, context.ship_ids, signal))
  }
  const readFile = (picked: File) => {
    if (!context) return
    void propose(picked.name, (signal) => api.intakeProposeXlsx(picked, context.ship_ids, signal))
  }
  const file = useFilePick(readFile)
  const stop = () => {
    session.bump()
    reading.current?.abort()
    setStep({ kind: 'input', error: null })
  }
  /** '다른 문서 넣기': 붙여 넣기 단계로(붙여 넣은 글은 남김). */
  const restart = () => setStep({ kind: 'input', error: null })

  const update = (patch: Partial<Review>) =>
    setStep((current) =>
      current.kind === 'review' ? { kind: 'review', review: { ...current.review, ...patch } } : current,
    )
  const setRow = (itemId: string, row: RowState) =>
    setStep((current) => {
      if (current.kind !== 'review' || current.review.busy) return current
      const problems = { ...current.review.problems }
      delete problems[itemId] // 고치면 그 항목의 서버 이유는 지운다(다시 확정할 때 새로 받는다)
      return {
        kind: 'review',
        review: {
          ...current.review,
          rows: { ...current.review.rows, [itemId]: row },
          problems,
        },
      }
    })

  const confirm = async (review: Review) => {
    if (!context) return
    const state = readiness(review.proposal.items, review.rows)
    if (!canConfirm(state)) return
    const stamp = session.current
    update({ busy: true, error: null, problems: {} })
    try {
      const result = await api.intakeConfirm({
        proposal_id: review.proposal.proposal_id,
        context,
        header: review.header,
        decisions: state.decisions,
        continue_ecn: review.continueEcn,
      })
      if (!session.isCurrent(stamp)) return
      onAnalyzed(result.request, result.result)
      setText('') // 확정한 문서는 비운다(같은 문서를 모르고 다시 넣지 않게)
      changeOpen(false, true)
    } catch (caught) {
      if (!session.isCurrent(stamp)) return
      const problems = caught instanceof ApiError ? problemsByItem(caught.problems, review.proposal.items) : {}
      const general = problems[''] ?? []
      delete problems['']
      const message = failureText(caught)
      update({
        busy: false,
        error: general.length > 0 ? `${message}: ${general.join(' / ')}` : message,
        problems,
      })
    }
  }

  const entry: DocumentEntry = {
    text,
    setText,
    file,
    ready: !!context,
    canRead: !!context && !!text.trim(),
    read: readText,
  }
  return {
    step,
    changeOpen,
    entry,
    stop,
    table: { setRow, update, restart, confirm },
  }
}
