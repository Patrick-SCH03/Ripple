// 기록·승인 요청(docs/records.md): 저장·행동·통보는 작업 공간에 묶인 요청(서버가 그 세대로 다시 계산·지도 대조),
// 목록·상세·기록·감사 확인·실적은 지도와 무관한 동기화 요청이다.
import { call } from './http'
import type {
  ActionRequest,
  AuditCheck,
  AuditEntry,
  DecisionBrief,
  EcnDetail,
  EcnList,
  EcnRecord,
  EcnStatus,
  NoticeRequest,
  OutcomeEntry,
  OutcomeInput,
  RecordRequest,
  RecordSaved,
} from './types'

export const recordsApi = {
  saveRecord: (body: RecordRequest) => call<RecordSaved>('/records', { method: 'POST', body: JSON.stringify(body) }),
  ecns: (signal?: AbortSignal) => call<EcnList>('/ecns', { signal }, 'sync'),
  ecn: (ecnId: string, signal?: AbortSignal) =>
    call<EcnDetail>(`/ecns/${encodeURIComponent(ecnId)}`, { signal }, 'sync'),
  record: (recordId: string, signal?: AbortSignal) =>
    call<EcnRecord>(`/records/${encodeURIComponent(recordId)}`, { signal }, 'sync'),
  act: (ecnId: string, body: ActionRequest) =>
    call<EcnStatus>(`/ecns/${encodeURIComponent(ecnId)}/actions`, { method: 'POST', body: JSON.stringify(body) }),
  /** 1.28.0 통보 기록(보냄·수령 확인·회신): 감사 줄 한 줄, 상태·버전은 그대로. */
  notice: (ecnId: string, body: NoticeRequest) =>
    call<AuditEntry>(`/ecns/${encodeURIComponent(ecnId)}/notices`, { method: 'POST', body: JSON.stringify(body) }),
  /** 1.31.0 결정 도우미: 진행 중 검토(검토·보류) 개정의 세 줄 요약·서명 전 확인할 것. 아니면 409. */
  brief: (ecnId: string, signal?: AbortSignal) =>
    call<DecisionBrief>(`/ecns/${encodeURIComponent(ecnId)}/brief`, { signal }, 'sync'),
  verifyAudit: () => call<AuditCheck>('/audit/verify', {}, 'sync'),
  /** 실적(실행·종료한 설계변경의 실제 비용·지연): 없으면 404. */
  outcome: (ecnId: string, signal?: AbortSignal) =>
    call<OutcomeEntry>(`/ecns/${encodeURIComponent(ecnId)}/outcome`, { signal }, 'sync'),
  putOutcome: (ecnId: string, body: OutcomeInput) =>
    call<OutcomeEntry>(`/ecns/${encodeURIComponent(ecnId)}/outcome`, { method: 'PUT', body: JSON.stringify(body) }, 'sync'),
}
