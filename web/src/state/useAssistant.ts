// AI 비서 대화 상태: 기록(보낸 문장 · 한 답 · 비서 차례 · 알림), 대화 ID, 보내는 중, 오류, 쓰던 글.
// - 최신 요청의 응답만 반영하고(LatestGate), 분석한 차례는 보낼 때 잡은 화면 세대가 그대로일 때만 상세에 연다
//   (응답을 기다리는 동안 사용자가 다른 설계변경을 고르거나 확정일을 바꿨으면 그 화면을 덮지 않는다).
// - 쓰던 문장·답은 칸이 닫혀도(태블릿 탭 전환·시트 닫기) 남도록 이 훅(App)에 둔다. 답은 대화·질문마다 따로다.
// - 작업 공간(지도)마다 따로다: Workbench가 작업 공간 토큰을 key로 다시 그려 새 대화가 되고(서버의 대화도 세대마다
//   따로), 사라질 때 기다리던 응답을 멈춘다. 바뀜 거절(409 workspace_changed)은 대화를 다시 읽지 않는다.
// - 실패: 연결이 끊겼으면 서버가 이 요청을 처리했을 수 있으니 대화를 다시 읽어 모르는 차례를 이 요청의 응답으로
//   이어 붙인다. 거절(409)이면 이 요청은 반영되지 않았다: 앞서 응답을 잃은 요청의 차례만 이어 붙이고, 거절된 답은
//   한 답으로 남기지 않는다(그 자리에 안내). 처리되지 않았으면 답은 기록에서 빼 질문 카드를 되살리고, 문장은
//   '보내기 실패'로 남긴다.
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  WORKSPACE_CHANGED,
  api,
  type AnalysisRequest,
  type AnalysisResult,
  type Answer,
  type AssistantTurn,
  type Question,
  type TurnContext,
} from '@/api/client'
import { answerText, draftKey, missingTurns } from '@/lib/assistant'
import type { ScreenGeneration } from '@/lib/generation'
import { LatestGate, type Ticket } from '@/lib/latest'

export type Entry =
  /** failed: 서버에 닿지 않았거나 거절돼 처리되지 않은 문장(다시 보낼 수 있다). */
  | { kind: 'said'; id: number; text: string; failed: boolean }
  | { kind: 'answered'; id: number; text: string }
  /** opened: 도착했을 때 상세에 열었는가(화면이 바뀌어 열지 않았으면 false). */
  | { kind: 'turn'; id: number; turn: AssistantTurn; opened: boolean }
  | { kind: 'notice'; id: number; text: string }

export type Reply = { optionId: string } | { text: string }

/** 사용자가 보낸 말(문장 또는 한 답). */
type Said = Extract<Entry, { kind: 'said' | 'answered' }>

/** 보낸 말의 끝: 응답을 받음(또는 서버에서 이어 붙임) · 실패 · 새 대화 등으로 버려짐. */
type Outcome = 'ok' | 'failed' | 'superseded'

export interface AssistantState {
  entries: Entry[]
  /** 기록의 마지막이 비서 차례면 그 차례(질문에 답할 수 있는 것은 이 차례뿐), 아니면 null. */
  latest: AssistantTurn | null
  busy: boolean
  error: ApiError | null
  /** 입력창에 쓰던 문장. */
  draft: string
  setDraft: (text: string) => void
  /** 차례의 첫 질문에 쓰던 답. */
  answerDraft: (turn: AssistantTurn) => string
  setAnswerDraft: (turn: AssistantTurn, text: string) => void
  send: (text: string) => void
  /** '보내기 실패'로 남은 문장을 다시 보낸다. */
  retry: (entryId: number) => void
  /** 차례의 질문에 답한다(분석 전 질문, 또는 분석 뒤 변경 사유 질문). */
  answer: (turn: AssistantTurn, question: Question, reply: Reply) => void
  /** 새 대화: 기록·쓰던 답을 비우고 기다리는 응답은 버린다. */
  reset: () => void
}

interface Options {
  /** 화면 맥락(호선·기준일·확정일). 없으면 보내지 않는다. */
  context: TurnContext | null
  generation: ScreenGeneration
  onAnalyzed: (request: AnalysisRequest, result: AnalysisResult, manual: boolean) => void
  /** 같은 분석에 변경 사유를 기록한 차례. basis는 답한 차례의 요청(기록 전)이다: 상세가 그 요청일 때만 반영한다. */
  onRecorded: (basis: AnalysisRequest, request: AnalysisRequest, result: AnalysisResult) => void
}

export function useAssistant({ context, generation, onAnalyzed, onRecorded }: Options): AssistantState {
  const [entries, setEntries] = useState<Entry[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [draft, setDraft] = useState('')
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({})
  const gate = useRef(new LatestGate())
  const conversation = useRef<string | null>(null)
  /** 화면이 아는 마지막 차례 번호(대화가 바뀌면 다시 0부터). */
  const lastTurn = useRef(0)
  const nextId = useRef(0)
  const id = () => (nextId.current += 1)

  /**
   * 받은 차례들을 기록에 붙이고, 마지막이 분석이면 화면 세대가 그대로일 때만 상세에 연다.
   * basis: 사유 질문에 답했을 때 그 차례의 요청(사유를 기록하기 전). 사유 기록 차례는 이것과 같은 상세에만 반영한다.
   */
  const receive = useCallback(
    (turns: AssistantTurn[], stamp: number, basis: AnalysisRequest | null) => {
      const last = turns.at(-1)
      if (!last) return
      if (conversation.current !== null && conversation.current !== last.conversation_id) {
        lastTurn.current = 0
        setEntries((list) => [...list, { kind: 'notice', id: id(), text: '이전 대화 끝남 · 새 대화로 이어짐' }])
      }
      conversation.current = last.conversation_id
      lastTurn.current = last.turn
      // 사유 기록 차례는 서버가 표시한다(같은 결과의 새 분석과 가르려고: 사유는 분석 ID에 들지 않는다)
      const restated = last.reason_recorded
      const open =
        !restated && last.state === 'analyzed' && last.request != null && last.result != null && generation.isCurrent(stamp)
      setEntries((list) => [
        ...list,
        ...turns.map((turn) => ({ kind: 'turn' as const, id: id(), turn, opened: turn === last && (open || restated) })),
      ])
      if (!last.request || !last.result) return
      // 사유 기록은 같은 분석이다: 상세가 기록 전 그 요청일 때만 사유를 반영하고, 새 분석이면 화면 세대가 그대로일 때만 연다
      if (restated) {
        if (basis) onRecorded(basis, last.request, last.result)
      } else if (open) onAnalyzed(last.request, last.result, false)
    },
    [generation, onAnalyzed, onRecorded],
  )

  /** 응답을 잃었을 때: 서버 대화에 화면이 모르는 차례가 있으면 이어 붙이고 참. */
  const catchUp = useCallback(
    async (ticket: Ticket, stamp: number, basis: AnalysisRequest | null): Promise<boolean> => {
      if (!conversation.current) return false
      try {
        const known = await api.conversation(conversation.current, ticket.signal)
        if (!gate.current.isLatest(ticket)) return false
        const fresh = missingTurns(known.turns, lastTurn.current)
        if (fresh.length === 0) return false
        receive(fresh, stamp, basis)
        return true
      } catch {
        return false
      }
    },
    [receive],
  )

  const post = useCallback(
    async (
      body: { message: string } | { answer: Answer },
      said: Said,
      basis: AnalysisRequest | null = null,
    ): Promise<Outcome> => {
      if (!context) return 'failed'
      const ticket = gate.current.begin()
      const stamp = generation.current
      setEntries((list) => [...list, said])
      setBusy(true)
      setError(null)
      try {
        const turn = await api.assistantTurn(
          { ...body, context, conversation_id: conversation.current, draft_only: false },
          ticket.signal,
        )
        if (!gate.current.isLatest(ticket)) return 'superseded'
        receive([turn], stamp, basis)
        return 'ok'
      } catch (caught) {
        if (!gate.current.isLatest(ticket)) return 'superseded'
        const failure = caught instanceof ApiError ? caught : new ApiError(String(caught), 0)
        if (failure.status === 0 && (await catchUp(ticket, stamp, basis))) return 'ok'
        // 거절이면 이 요청은 반영되지 않았다: 앞서 응답을 잃은 요청의 차례가 서버에 있으면 그것만 이어 붙인다
        // (작업 공간이 바뀐 거절은 그 대화가 이미 끝났으니 다시 읽지 않는다)
        const changed = failure.code === WORKSPACE_CHANGED
        const recovered = failure.status === 409 && !changed && (await catchUp(ticket, stamp, basis))
        if (!gate.current.isLatest(ticket)) return 'superseded'
        // 처리되지 않았다: 문장은 다시 보낼 수 있게 남기고, 답은 빼서 질문 카드를 되살린다(앞의 답이 반영돼 있었으면 안내로)
        const rejected =
          said.kind === 'answered' && recovered
            ? ({
                kind: 'notice',
                id: said.id,
                text: `고른 답(${said.text}) 미반영 — 앞서 보낸 답이 이미 반영돼 그 결과를 이어 붙임`,
              } as const)
            : null
        setEntries((list) => {
          if (said.kind === 'said') return list.map((entry) => (entry.id === said.id ? { ...said, failed: true } : entry))
          if (rejected) return list.map((entry) => (entry.id === said.id ? rejected : entry))
          return list.filter((entry) => entry.id !== said.id)
        })
        if (!rejected) setError(failure)
        return 'failed'
      } finally {
        if (gate.current.isLatest(ticket)) setBusy(false)
      }
    },
    [context, generation, catchUp, receive],
  )

  const send = useCallback(
    (text: string) => {
      const message = text.trim()
      if (!message) return
      setDraft('')
      void post({ message }, { kind: 'said', id: id(), text: message, failed: false })
    },
    [post],
  )

  const retry = useCallback(
    (entryId: number) => {
      const failed = entries.find((entry) => entry.id === entryId)
      if (failed?.kind !== 'said' || !failed.failed) return
      setEntries((list) => list.filter((entry) => entry.id !== entryId))
      void post({ message: failed.text }, { kind: 'said', id: id(), text: failed.text, failed: false })
    },
    [entries, post],
  )

  const answer = useCallback(
    (turn: AssistantTurn, question: Question, reply: Reply) => {
      const key = draftKey(turn)
      const forget = (outcome: Outcome) => {
        if (outcome !== 'ok' || !key) return
        setAnswerDrafts((drafts) => {
          const next = { ...drafts }
          delete next[key]
          return next
        })
      }
      // 분석 뒤 질문(변경 사유)이면 그 차례의 요청이 사유를 기록할 바탕이다
      const basis = turn.follow_ups.some((asked) => asked.question_id === question.question_id) ? turn.request : null
      if ('optionId' in reply) {
        const said = answerText(question, reply.optionId)
        const body = { answer: { question_id: question.question_id, option_id: reply.optionId } }
        void post(body, { kind: 'answered', id: id(), text: said }, basis).then(forget)
        return
      }
      const text = reply.text.trim()
      if (!text) return
      const body = { answer: { question_id: question.question_id, text } }
      void post(body, { kind: 'answered', id: id(), text }, basis).then(forget)
    },
    [post],
  )

  const answerDraft = useCallback((turn: AssistantTurn) => answerDrafts[draftKey(turn) ?? ''] ?? '', [answerDrafts])
  const setAnswerDraft = useCallback((turn: AssistantTurn, text: string) => {
    const key = draftKey(turn)
    if (key) setAnswerDrafts((drafts) => ({ ...drafts, [key]: text }))
  }, [])

  const reset = useCallback(() => {
    gate.current.begin()
    generation.bump()
    conversation.current = null
    lastTurn.current = 0
    setEntries([])
    setAnswerDrafts({})
    setBusy(false)
    setError(null)
  }, [generation])

  // 이 화면이 사라지면(작업 공간이 바뀜) 기다리던 응답을 멈춘다
  useEffect(() => {
    const requests = gate.current
    return () => {
      requests.begin()
    }
  }, [])

  // 비서 차례 뒤에 사용자가 새로 말했으면(기다리는 중이거나 보내지 못했으면) 그 차례의 질문은 끝난 것이다
  const last = entries.at(-1)
  return {
    entries,
    latest: last?.kind === 'turn' ? last.turn : null,
    busy,
    error,
    draft,
    setDraft,
    answerDraft,
    setAnswerDraft,
    send,
    retry,
    answer,
    reset,
  }
}
