// 소개 화면 그림의 심각도 색·말(DESIGN.md 3절: 높음 = danger, 보통 = warning, 낮음 = primary). 색만으로 전하지 않게 말도 함께.
import type { ShowcaseNode } from './example'

export const SEVERITY_COLOR: Record<ShowcaseNode['severity'], string> = {
  high: 'var(--danger)',
  medium: 'var(--warning)',
  low: 'var(--primary)',
  info: 'var(--border-strong)',
}

export const SEVERITY_WORD: Record<ShowcaseNode['severity'], string> = {
  high: '높음',
  medium: '보통',
  low: '낮음',
  info: '정보',
}
