// 엑셀 가져오기 대화상자의 문구: 방식(가져오기 · 상태 올리기)마다 제목·설명·확정 단추, 기억한 매핑의 출처, 오류 문장.
import { ApiError, IMPORT_CHANGED } from '@/api/client'
import type { ImportMode } from './steps'

export const TEXT: Record<ImportMode, { title: string; description: string; confirm: string }> = {
  full: {
    title: '엑셀 가져오기',
    description:
      'BOM·발주대장·공정표 엑셀 → 시트·열을 Ripple 양식에 맞춰 연결 지도 생성 · 올린 파일은 실제 데이터(AI 외부 호출 없음)',
    confirm: '이 지도로 전환',
  },
  status: {
    title: '상태 올리기',
    description:
      '매일 바뀌는 발주 현황·납기·공정 실적 엑셀 → 지금 지도의 상태·날짜만 갱신 · 부재·블록·공정 구조는 그대로',
    confirm: '이 내용으로 갱신',
  },
}

export const FILE_BEFORE = '이전 파일'
export const STALE_PREVIEW =
  '미리 본 뒤 지도가 바뀌어 미반영 · 열 확인 → ‘이대로 읽기’로 새 미리보기 후 다시 갱신'

export function failureText(caught: unknown): string {
  if (caught instanceof ApiError && caught.code === IMPORT_CHANGED) {
    return `${caught.message} · 다른 창에서 같은 가져오기를 고쳤다면 파일을 다시 올리기`
  }
  return caught instanceof ApiError ? caught.message : String(caught)
}
