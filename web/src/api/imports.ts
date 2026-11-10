// 엑셀 가져오기 요청(docs/input.md(엑셀 양식)): 지도 전체 가져오기와 상태 올리기(바뀌는 시트만). 올리기 → 열 확인 → 읽기 →
// 확정 순서이고, 확정만 지도를 바꾸는 전환 요청이다.
import { call } from './http'
import type {
  ConfirmedMapping,
  ImportPreview,
  MappingOverrides,
  MappingProposal,
  SnapshotList,
  StatusImportPreview,
  UpdateApplied,
} from './types'

export const importsApi = {
  /** 엑셀 파일을 그대로 올린다 → 매핑 제안(열 확인). 아직 지도를 만들지 않는다. */
  stageImport: (file: Blob, name: string, signal?: AbortSignal) =>
    call<MappingProposal>(
      `/imports?file_name=${encodeURIComponent(name)}`,
      { method: 'POST', body: file, signal },
      'sync',
      'application/octet-stream',
    ),
  /** 시트 상태(양식 시트·읽지 않음)·머리글 행을 정해 다시 제안받는다(상태 버전 +1). */
  proposeImport: (importId: string, overrides: MappingOverrides, signal?: AbortSignal) =>
    call<MappingProposal>(
      `/imports/${encodeURIComponent(importId)}/proposal`,
      { method: 'POST', body: JSON.stringify(overrides), signal },
      'sync',
    ),
  /** 확정 매핑으로 읽어 품질 리포트를 받는다(상태 버전 +1, 오류가 없으면 그 버전으로 확정할 수 있음). */
  submitMapping: (importId: string, version: number, mapping: ConfirmedMapping, signal?: AbortSignal) =>
    call<ImportPreview>(
      `/imports/${encodeURIComponent(importId)}/mapping`,
      { method: 'POST', body: JSON.stringify({ version, mapping }), signal },
      'sync',
    ),
  confirmImport: (importId: string, version: number) =>
    call<SnapshotList>(
      `/imports/${encodeURIComponent(importId)}/confirm`,
      { method: 'POST', body: JSON.stringify({ version }) },
      'switch',
    ),
  /** 상태 올리기(바뀌는 시트만): 올리기 → 열 확인 → 읽기(미리보기) → 확정(지금 지도에 덮어씀, 전환 요청). */
  stageStatusImport: (file: Blob, name: string, signal?: AbortSignal) =>
    call<MappingProposal>(
      `/status-imports?file_name=${encodeURIComponent(name)}`,
      { method: 'POST', body: file, signal },
      'sync',
      'application/octet-stream',
    ),
  proposeStatusImport: (importId: string, overrides: MappingOverrides, signal?: AbortSignal) =>
    call<MappingProposal>(
      `/status-imports/${encodeURIComponent(importId)}/proposal`,
      { method: 'POST', body: JSON.stringify(overrides), signal },
      'sync',
    ),
  submitStatusImport: (importId: string, version: number, mapping: ConfirmedMapping, signal?: AbortSignal) =>
    call<StatusImportPreview>(
      `/status-imports/${encodeURIComponent(importId)}/mapping`,
      { method: 'POST', body: JSON.stringify({ version, mapping }), signal },
      'sync',
    ),
  confirmStatusImport: (importId: string, version: number) =>
    call<UpdateApplied>(
      `/status-imports/${encodeURIComponent(importId)}/confirm`,
      { method: 'POST', body: JSON.stringify({ version }) },
      'switch',
    ),
}
