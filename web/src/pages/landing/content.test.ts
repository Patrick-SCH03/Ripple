// 소개 목차: 위 막대는 첫 화면 흐름 순서 6개, 바닥 목차는 모든 절. 결재 절은 결재선(파트장 → 팀장 → 본부장)과 검토서를
// 다루므로 이름은 '결재·검토서'(절 꼬리표도 같은 이름) — '팀장 결재'가 아니다. 목차가 가리키는 절은 흐름 띠 단계와 같은 순서.
import { describe, expect, it } from 'vitest'
import indexHtml from '../../../index.html?raw'
import { FLOW, FOOTER_NAV, HERO, NAV } from './content'

describe('첫 화면 제목(사용자가 고른 문장)', () => {
  it("두 줄 '설계변경, 확정하기 전에 / 영향 범위부터 확인하세요' = 링크 미리보기 제목", () => {
    expect(HERO.title).toEqual(['설계변경, 확정하기 전에', '영향 범위부터 확인하세요'])
    expect(indexHtml).toContain(`<meta property="og:title" content="Ripple · ${HERO.title.join(' ')}" />`)
  })
})

describe('소개 목차', () => {
  it("위 막대 목차 6개, 결재 절 이름은 '결재·검토서'이고 '팀장 결재'가 없음", () => {
    expect(NAV.find((item) => item.href === '#approval')?.label).toBe('결재·검토서')
    expect([...NAV, ...FOOTER_NAV].map((item) => item.label)).not.toContain('팀장 결재')
    expect(NAV.map((item) => item.label)).toEqual(['3D 배치', '영향 지도', '판단 요약', '결정 기한', '결재·검토서', '운영 조건'])
  })

  it('바닥 목차는 위 막대 목차를 모두 담고, 흐름 띠 단계의 절도 모두 담음(같은 순서)', () => {
    const footer = FOOTER_NAV.map((item) => item.href)
    for (const item of NAV) expect(footer).toContain(item.href)
    const flow = FLOW.map((step) => footer.indexOf(step.href))
    expect(flow.every((at) => at >= 0)).toBe(true)
    expect([...flow].sort((a, b) => a - b)).toEqual(flow)
  })
})
