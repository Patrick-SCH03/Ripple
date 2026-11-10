// 구성원 관리의 역할 고르기 값(담당자 · 팀장 · 결재선의 파트장·본부장)과 줄 배치.
import type { Account } from '@/api/client'
import { ROLE_LABEL } from '@/lib/account'

export type StaffRole = Account['role']

export const ROLE_OPTIONS: { value: StaffRole; label: string }[] = [
  { value: 'member', label: ROLE_LABEL.member },
  { value: 'admin', label: ROLE_LABEL.admin },
  // 결재선(docs/records.md(기록·결재) 14절): 파트장·본부장은 자기 단계 결재만(구성원 관리·지도는 팀장)
  { value: 'part_lead', label: ROLE_LABEL.part_lead },
  { value: 'executive', label: ROLE_LABEL.executive },
]

// 줄 배치(머리글과 같게): 768px부터 표, 그보다 좁으면 칸을 위아래로. 이름·아이디는 남는 폭을 다 쓰고 최소 7em,
// 동작 칸은 최대 21em(단추 셋이 한 줄, 좁으면 두 줄). 줄마다 따로 그리는 격자라 내용 폭(auto) 칸을 두지 않는다 — 머리글과
// 줄의 칸 위치가 어긋나지 않게. 폭은 em(글자 크기 기준)이라 큰 글자에서도 마지막 로그인 시각이 옆 칸과 겹치지 않는다
export const ROW_COLUMNS = 'md:grid-cols-[minmax(7em,1fr)_6.5em_4.5em_9.5em_minmax(0,21em)]'
