// 엑셀 가져오기 대화상자의 단계(docs/input.md(엑셀 양식) 4절): 파일 고르기 → 읽는 중 → 열 확인 → 품질 리포트.
// 단계마다 보이는 문구와 오류 문장은 text.ts.
import type { ApiError, ImportPreview, MappingProposal, StatusImportPreview } from '@/api/client'
import type { Choices } from '@/lib/mapping'

/** 열 확인 상태: 마지막 제안, 사람의 고침, 서버의 지금 상태 버전(읽기·덮어쓰기마다 오름). */
export interface Review {
  proposal: MappingProposal
  choices: Choices
  version: number
}

export type Step =
  | { kind: 'choose' }
  | { kind: 'reading'; name: string }
  | { kind: 'mapping'; review: Review; busy: boolean; error: string | null }
  | { kind: 'report'; review: Review; preview: ImportPreview; failure: ApiError | null; remembered?: string | null }
  | {
      kind: 'status-report'
      review: Review
      result: StatusImportPreview
      failure: ApiError | null
      remembered?: string | null
    }
  | { kind: 'failed'; name: string; error: ApiError }

/** full = 엑셀 가져오기(새 지도, 관리자), status = 상태 올리기(바뀌는 시트만 지금 지도에 덮어씀, 담당자 이상). */
export type ImportMode = 'full' | 'status'
