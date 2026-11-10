// AI 비서 요청: 차례 보내기와 대화 다시 읽기(응답을 잃었을 때). 지금 지도에 묶인 요청이다.
import { call } from './http'
import type { AssistantTurn, AssistantTurnRequest, Conversation } from './types'

export const assistantApi = {
  assistantTurn: (request: AssistantTurnRequest, signal?: AbortSignal) =>
    call<AssistantTurn>('/assistant/turns', { method: 'POST', body: JSON.stringify(request), signal }),
  conversation: (conversationId: string, signal?: AbortSignal) =>
    call<Conversation>(`/assistant/conversations/${encodeURIComponent(conversationId)}`, { signal }),
}
