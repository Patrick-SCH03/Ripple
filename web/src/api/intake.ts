// 문서 접수 요청(docs/input.md(문서 접수)): 제안·확정은 지금 지도에 묶인 요청(지도가 바뀌면 제안이 없어져 409).
import { call } from './http'
import type { IntakeConfirmation, IntakeProposal, IntakeResult } from './types'

export const intakeApi = {
  /** 붙여 넣은 변경 문서 → 확인표 제안. 자동 진행은 없다. */
  intakePropose: (text: string, shipIds: string[], signal?: AbortSignal) =>
    call<IntakeProposal>('/intake/proposals', { method: 'POST', body: JSON.stringify({ text, ship_ids: shipIds }), signal }),
  /** 변경 리스트 엑셀(첫 시트, 첫 행 = 머리글) → 같은 확인표 제안. */
  intakeProposeXlsx: (file: Blob, shipIds: string[], signal?: AbortSignal) =>
    call<IntakeProposal>(
      `/intake/proposals/xlsx?${shipIds.map((s) => `ship_ids=${encodeURIComponent(s)}`).join('&')}`,
      { method: 'POST', body: file, signal },
      'bound',
      'application/octet-stream',
    ),
  /** 항목별 맞음·고침·뺌 → 서버가 다시 검증해 분석한다. 확정할 수 없으면 422(problems = '항목 ID: 이유'). */
  intakeConfirm: (body: IntakeConfirmation, signal?: AbortSignal) =>
    call<IntakeResult>('/intake/confirmations', { method: 'POST', body: JSON.stringify(body), signal }),
}
