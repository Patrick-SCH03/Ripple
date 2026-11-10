import { describe, expect, it } from 'vitest'
import type { KeyNumber } from './summary'
import { GLOSSARY } from './glossary'

describe('용어 설명', () => {
  it('핵심 수치 카드마다 설명이 있음', () => {
    const ids: KeyNumber['id'][] = ['total', 'deadline', 'ordered', 'exit', 'delivery']
    for (const id of ids) expect(GLOSSARY[id].body.length).toBeGreaterThan(0)
  })

  it('날짜·조건 칸(기준일·확정일·적용 시작일·설계 승인)마다 짧은 설명 2~3줄', () => {
    for (const id of ['asOf', 'confirmOn', 'effectiveOn', 'designStatus'] as const) {
      expect(GLOSSARY[id].body.length).toBeGreaterThanOrEqual(2)
      expect(GLOSSARY[id].body.length).toBeLessThanOrEqual(3)
    }
    // 명세와 같은 뜻: 적용 시작일은 계산에 안 씀, 확정일을 비우면 기준일, 기준일 뒤는 계획으로 추정
    expect(GLOSSARY.effectiveOn.body.join(' ')).toContain('계산에는 쓰지 않고')
    expect(GLOSSARY.confirmOn.body.join(' ')).toContain('비우면 기준일')
    expect(GLOSSARY.asOf.body.join(' ')).toContain('추정')
    expect(GLOSSARY.deadline.body.join(' ')).toContain('D-n은 기준일부터')
  })

  it('설명은 명사형 개조식(해요체·합니다체 끝 없음)이고 숫자 문턱(바뀌는 설정값)을 적지 않음', () => {
    for (const term of Object.values(GLOSSARY)) {
      for (const line of term.body) {
        expect(line).not.toMatch(/(?<!필)요\.?$|니다\.?$/)
        expect(line).not.toMatch(/\.$/)
        expect(line).not.toMatch(/\d+\s*만\s*원/)
      }
    }
  })
})
