// AI 비서 화면 계산(순수 함수, assistant.test.ts가 성질을 검사한다): 화면 맥락 → 차례 맥락, 질문 카드 모양,
// 근거 칩 → 그래프 노드, 블록 조각, 지난 분석 여부, 보내기 키.
import type {
  AssistantTurn,
  GraphNode,
  Notification,
  NotificationTarget,
  Question,
  QuestionOption,
  RenderedBlock,
  TextPart,
  TurnContext,
} from '@/api/client'
import type { RequestContext } from './request'

/** 확인 질문에서 제안을 받아들이는 선택지(계약 YES), '해당 없음'(계약 NONE_OPTION). */
export const YES = '__yes__'
export const NONE = '__none__'

/** 한 문장 최대 길이(계약 AssistantTurnRequest.message). */
export const MAX_MESSAGE = 1000

/** 탐색 기간을 정하지 않은 요청의 기본값(계약 TurnContext.horizon_days). */
export const DEFAULT_HORIZON_DAYS = 60

/** 비서 차례의 화면 맥락: 목록에서 고른 설계변경의 호선·기준일·확정일·탐색 기간. 호선·기준일이 없으면 물을 수 없다. */
export function turnContext(context: RequestContext): TurnContext | null {
  if (context.shipIds.length === 0 || !context.asOf) return null
  return {
    ship_ids: context.shipIds,
    as_of: context.asOf,
    confirm_on: context.confirmOn,
    horizon_days: context.horizonDays ?? DEFAULT_HORIZON_DAYS,
  }
}

export type CardMode = 'choose' | 'text' | 'value'

/** 질문 카드 모양: 선택지만(확인·고르기), 글만(다시 설명), 제안 값 + 직접 입력(값). */
export function cardMode(question: Question): CardMode {
  if (question.kind === 'restate') return 'text'
  if (question.kind === 'value') return 'value'
  return 'choose'
}

/** 앞에 크게 보일 선택지와 뒤로 물릴 '해당 없음·고치기'. */
export function splitOptions(question: Question): { main: QuestionOption[]; none: QuestionOption | null } {
  const none = question.options.find((option) => option.option_id === NONE) ?? null
  return { main: question.options.filter((option) => option.option_id !== NONE), none }
}

/** 기록에 남길 '내가 한 답' 글: 고른 선택지 이름(없으면 그대로). */
export function answerText(question: Question, optionId: string): string {
  return question.options.find((option) => option.option_id === optionId)?.label ?? optionId
}

/**
 * 근거 칩이 가리키는 그래프 노드. 엔터티 ID가 노드면 그대로, 발주 ID('PO-0130')는 그 발주의 첫 품목
 * ('PO-0130#1'), 그래프에 없으면 null(누를 수 없는 칩).
 */
export function nodeFor(entityId: string, nodes: readonly Pick<GraphNode, 'id'>[]): string | null {
  if (nodes.some((node) => node.id === entityId)) return entityId
  const lines = nodes
    .map((node) => node.id)
    .filter((id) => id.startsWith(`${entityId}#`))
    .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }))
  return lines[0] ?? null
}

/** 블록 조각(서버가 조각을 주지 않았으면 글 하나). */
export function partsOf(block: Pick<RenderedBlock, 'text' | 'parts'>): TextPart[] {
  return block.parts.length > 0 ? block.parts : [{ text: block.text, entity_id: null, value: false }]
}

/** 분석한 차례가 지금 상세에 보이는 분석인가(아니면 '지난 분석': 다시 계산했거나 다른 설계변경을 골랐다). */
export function isShown(turn: Pick<AssistantTurn, 'result'>, shownAnalysisId: string | null): boolean {
  return turn.result != null && turn.result.analysis_id === shownAnalysisId
}

/** 질문별 쓰던 답의 키: 대화가 만료돼 새 대화가 열리면 질문 번호가 다시 1부터라 대화 ID까지 묶는다. */
export function draftKey(turn: Pick<AssistantTurn, 'conversation_id' | 'questions'>): string | null {
  const question = turn.questions[0]
  return question ? `${turn.conversation_id}|${question.question_id}` : null
}

/** 서버에 쌓인 차례 중 화면이 아직 모르는 것(응답을 잃었을 때 이어 붙인다). */
export function missingTurns<T extends Pick<AssistantTurn, 'turn'>>(serverTurns: readonly T[], known: number): T[] {
  return serverTurns.filter((turn) => turn.turn > known)
}

type Analyzed = Pick<AssistantTurn, 'conversation_id' | 'state' | 'reason_recorded'> & {
  result?: { analysis_id: string } | null
}

/**
 * 원래 분석 차례를 다시 열 때 열 차례: 그 차례 바로 뒤에 이어진 사유 기록 차례(같은 대화·같은 분석)의 마지막.
 * 결과가 같은 다른 새 분석(사유만 다른 문장 등)은 따라가지 않는다.
 */
export function latestVersion<T extends Analyzed>(turn: T, turns: readonly T[]): T {
  let latest = turn
  for (const next of turns.slice(turns.indexOf(turn) + 1)) {
    const recordOfThis =
      next.reason_recorded &&
      next.conversation_id === turn.conversation_id &&
      next.result?.analysis_id != null &&
      next.result.analysis_id === turn.result?.analysis_id
    if (!recordOfThis) break
    latest = next
  }
  return latest
}

/** 입력창에서 보내기: Enter(Shift 없이), 한글 조합 중이 아닐 때. */
export function isSubmitKey(event: { key: string; shiftKey: boolean; isComposing: boolean }): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing
}

/** 알림 받는 쪽 이름(1.32.0 협력사 구분): 발주처는 기자재 공급사·사외 협력사, 작업반은 사내 협력사. */
export const NOTIFY_TARGETS: Record<NotificationTarget, string> = {
  supplier: '공급사·사외 협력사',
  fabricator: '재작업 블록 담당',
  drawing: '도면 담당',
  crew: '사내 협력사 작업반',
}

/** 메일 카드 머리의 짧은 수신 구분 칩(전체 이름은 NOTIFY_TARGETS — 칩의 title·읽기용 이름). */
export const NOTIFY_CHIPS: Record<NotificationTarget, string> = {
  supplier: '협력사',
  fabricator: '재작업 담당',
  drawing: '도면 담당',
  crew: '작업반',
}

/** 하도급법 안내가 필요한 받는 쪽(사외 협력사·공급사 발주, 재작업 블록, 사내 협력사 작업반). */
const SUBCONTRACT_TARGETS = new Set<NotificationTarget>(['supplier', 'fabricator', 'crew'])

/**
 * 알림 초안 묶음 위의 하도급법 안내 한 줄: 사내(작업반)·사외 협력사 모두 대상이라 둘을 함께 적는다
 * (하도급법 제8조 부당한 위탁취소 금지 — 서버 템플릿 po.consult와 같은 뜻). 그런 받는 쪽이 없으면 null.
 */
export function subcontractNote(notifications: readonly Pick<Notification, 'target'>[]): string | null {
  return notifications.some((n) => SUBCONTRACT_TARGETS.has(n.target))
    ? '사내 협력사(작업반)·사외 협력사 모두 하도급법 대상 · 맡긴 작업·발주 변경·취소 전 손실 보상 협의 필요'
    : null
}
