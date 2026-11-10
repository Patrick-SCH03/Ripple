// 소개 화면 문구(DESIGN.md 12절): 서비스를 홍보·소개하는 페이지다. 절마다 짧고 힘 있는 제목(합니다체) + 사용자가 얻는 가치
// 한 줄(필요한 곳만) + 큰 그림·영상·스크롤 연출. 기능이 어떻게 계산·구현됐는지 설명하는 문단, 데이터 출처·측정 방법·경위
// 설명은 두지 않는다(11-03 사용자 방향). 숫자는 MEASURED(잰 값)와 example.json(엔진 출력)에서만 온다.
import { Award, Box, Crosshair, FileText, Lock, Network, Radar, Server, ShieldCheck, type LucideIcon } from 'lucide-react'

export interface NavItem {
  href: string
  label: string
}

// 위 막대 목차(6개): 첫 화면 흐름 순서. 대안 비교·AI 비서는 바닥 목차에만 더 둔다.
export const NAV: NavItem[] = [
  { href: '#ship3d', label: '3D 배치' },
  { href: '#map', label: '영향 지도' },
  { href: '#summary', label: '판단 요약' },
  { href: '#deadline', label: '결정 기한' },
  { href: '#approval', label: '결재·검토서' },
  { href: '#trust', label: '운영 조건' },
]

/** 바닥 목차: 모든 절. */
export const FOOTER_NAV: NavItem[] = [
  { href: '#problem', label: '영향 검토' },
  { href: '#ship3d', label: '3D 배치' },
  { href: '#map', label: '영향 지도' },
  { href: '#summary', label: '판단 요약' },
  { href: '#cost', label: '비용·중량' },
  { href: '#deadline', label: '결정 기한' },
  { href: '#options', label: '대안 비교' },
  { href: '#approval', label: '결재·검토서' },
  { href: '#assistant', label: 'AI 비서' },
  { href: '#trust', label: '운영 조건' },
]

/** 첫 화면 문구(합니다체): 대상·역할 한 줄, 사용자가 고른 제목(11-03), 가치 한 줄. */
export const HERO = {
  eyebrow: '조선소 설계변경 영향도 분석 및 의사결정 지원 솔루션',
  title: ['설계변경, 확정하기 전에', '영향 범위부터 확인하세요'] as const,
  lead: '영향 범위, 추가 공수·재료비, 결정 기한까지 확정 전에 한눈에 확인합니다.',
}

/** 첫 화면 흐름 띠의 단계(절 순서와 같음). 값 줄은 HeroScene이 example.json으로 채운다. */
export type FlowKey = 'change' | 'scope' | 'cost' | 'deadline' | 'approval'

export const FLOW: { key: FlowKey; title: string; href: string }[] = [
  { key: 'change', title: '설계변경 한 건', href: '#problem' },
  { key: 'scope', title: '영향 범위 2D·3D', href: '#ship3d' },
  { key: 'cost', title: '총변경비용', href: '#summary' },
  { key: 'deadline', title: '결정 기한', href: '#deadline' },
  { key: 'approval', title: '결재·검토서', href: '#approval' },
]

/** 절마다 가치 한 줄(무엇을 얻는가 — 기능 설명이 아님). 없는 절은 제목만. */
export const VALUE = {
  problem: 'BOM 조회로는 보이지 않는 2차 영향까지 찾아냅니다.',
  ship3d: '변경 영향을 선체 위에서 한눈에 확인합니다.',
  map: '바뀐 판에서 탑재 공정까지 한 줄로 이어 봅니다.',
  deadline: '확정을 미루면 늘어나는 금액을 미리 봅니다.',
  approval: '같은 근거로 결재하고 검토서로 남깁니다.',
  assistant: '현장 말 그대로 적으면 분석까지 이어집니다.',
}

/** 단추: 행동 + 대상. 첫 화면과 마지막 판에서 같은 짝을 쓴다. */
export const CTA = { start: '시작하기', enter: '업무 화면으로', map: '영향 지도 보기' }

/** 절 머리의 알약 꼬리표 색(DESIGN.md 3절 뜻: primary = 정보, warning = 기한, success = 결재, agent = AI). */
export type Tone = 'primary' | 'success' | 'warning' | 'agent'

export interface Chip {
  icon: LucideIcon
  text: string
}

/** 3D 배치 절 아래 이름표(2~3단어). */
export const SHIP_CHIPS: Chip[] = [
  { icon: Radar, text: '물결 전파' },
  { icon: Crosshair, text: '목록에서 블록으로' },
  { icon: Network, text: '2D 지도와 전환' },
  { icon: Box, text: '선체 블록 배치' },
]

/** 결재·검토서 절 아래 이름표. */
export const APPROVAL_CHIPS: Chip[] = [
  { icon: FileText, text: 'A4 검토서 · PDF 저장' },
  { icon: ShieldCheck, text: '고칠 수 없는 감사 기록' },
]

export const TRUST: Chip[] = [
  { icon: Server, text: '사내 서버에 설치' },
  { icon: Lock, text: '실데이터는 밖으로 내보내지 않음' },
  { icon: Award, text: '2026 K-조선 해커톤 본선 출품' },
]

export interface Measured {
  value: string
  label: string
}

// 잰 값(README '측정된 결과'와 같은 값). 바꾸면 그 문서와 함께 바꾼다.
export const MEASURED: Measured[] = [
  { value: '0.1초', label: '설계변경 1건 분석' },
  { value: '98.3%', label: '엑셀 열 자동 맞춤 정확도' },
  { value: '136/136', label: '영향 찾기' },
]
