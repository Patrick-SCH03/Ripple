// 작업 공간(지도) 요청(docs/operations.md(서비스) 6절): 샘플, 지도 목록·활성화·내려받기, 현장 상태 갱신.
import { call } from './http'
import type { Sample, SnapshotList, StatusUpdate, UpdateApplied } from './types'

export const workspaceApi = {
  samples: () => call<Sample[]>('/samples'),
  snapshots: (signal?: AbortSignal) => call<SnapshotList>('/snapshots', { signal }, 'sync'),
  activate: (snapshotId: string) =>
    call<SnapshotList>(`/snapshots/${encodeURIComponent(snapshotId)}/activate`, { method: 'POST' }, 'switch'),
  /** 지도를 지정 양식 엑셀로 내려받는 주소(기본 지도 = 양식 예시). */
  exportUrl: (snapshotId: string) => `/api/snapshots/${encodeURIComponent(snapshotId)}/export`,
  /** 상태 갱신(확인·수정): 지금 지도에 상태·날짜만 덮어써 새 작업 공간으로 바꾼다(전환 요청). */
  applyUpdate: (body: StatusUpdate) =>
    call<UpdateApplied>('/updates', { method: 'POST', body: JSON.stringify(body) }, 'switch'),
}
