import { describe, expect, it } from 'vitest'
import type { Question } from '@/api/client'
import {
  DEFAULT_HORIZON_DAYS,
  NONE,
  YES,
  answerText,
  cardMode,
  draftKey,
  isShown,
  isSubmitKey,
  latestVersion,
  missingTurns,
  nodeFor,
  partsOf,
  splitOptions,
  turnContext,
} from './assistant'
import { ScreenGeneration } from './generation'

function question(kind: Question['kind'], options: [string, string][] = []): Question {
  return {
    question_id: `q@1`,
    kind,
    target: 'summary',
    prompt: '맞나요?',
    options: options.map(([option_id, label]) => ({ option_id, label })),
  }
}

describe('비서 차례 맥락', () => {
  it('호선·기준일이 있어야 물을 수 있고, 확정일·탐색 기간은 그대로 넘김', () => {
    const base = {
      ecnId: 'E1',
      title: null,
      shipIds: ['S-001'],
      asOf: '2026-10-20',
      confirmOn: '2026-11-01',
      horizonDays: 90,
    }
    expect(turnContext(base)).toEqual({
      ship_ids: ['S-001'],
      as_of: '2026-10-20',
      confirm_on: '2026-11-01',
      horizon_days: 90,
    })
    expect(turnContext({ ...base, horizonDays: null })?.horizon_days).toBe(DEFAULT_HORIZON_DAYS)
    expect(turnContext({ ...base, shipIds: [] })).toBeNull()
    expect(turnContext({ ...base, asOf: null })).toBeNull()
  })
})

describe('질문 카드', () => {
  it('종류마다 카드 모양: 확인·고르기는 선택지, 다시 설명은 글, 값은 제안 + 입력', () => {
    expect(cardMode(question('confirm'))).toBe('choose')
    expect(cardMode(question('choose'))).toBe('choose')
    expect(cardMode(question('restate'))).toBe('text')
    expect(cardMode(question('value'))).toBe('value')
  })

  it("'해당 없음'은 뒤로 물리고 나머지 순서는 그대로", () => {
    const q = question('choose', [
      ['a', '판 7'],
      [NONE, '해당 없음'],
      ['b', '판 9'],
    ])
    const { main, none } = splitOptions(q)
    expect(main.map((o) => o.option_id)).toEqual(['a', 'b'])
    expect(none?.label).toBe('해당 없음')
    expect(splitOptions(question('choose', [['a', '판 7']])).none).toBeNull()
  })

  it('기록에 남는 답은 고른 선택지 이름', () => {
    const q = question('confirm', [
      [YES, '맞아요, 분석해 주세요'],
      [NONE, '고칠게요'],
    ])
    expect(answerText(q, YES)).toBe('맞아요, 분석해 주세요')
    expect(answerText(q, 'unknown')).toBe('unknown')
  })
})

describe('근거 칩 → 그래프 노드', () => {
  const nodes = [{ id: 'S-001:T31C' }, { id: 'PO-0130#3' }, { id: 'PO-0130#12' }, { id: 'PO-0130#2' }]

  it('노드면 그대로, 발주는 첫 품목(번호 순), 없으면 누를 수 없음', () => {
    expect(nodeFor('S-001:T31C', nodes)).toBe('S-001:T31C')
    expect(nodeFor('PO-0130', nodes)).toBe('PO-0130#2')
    expect(nodeFor('PO-9999', nodes)).toBeNull()
    expect(nodeFor('PO-013', nodes)).toBeNull()
  })
})

describe('블록 조각', () => {
  it('조각이 있으면 그대로, 없으면 글 하나', () => {
    const parts = [{ text: 'T31C', entity_id: 'S-001:T31C', value: false }]
    expect(partsOf({ text: 'T31C', parts })).toBe(parts)
    expect(partsOf({ text: '총변경비용은 378만원이에요.', parts: [] })).toEqual([
      { text: '총변경비용은 378만원이에요.', entity_id: null, value: false },
    ])
  })
})

describe('지난 분석', () => {
  it('상세에 보이는 분석과 ID가 같을 때만 지금 분석', () => {
    const turn = { result: { analysis_id: 'A1' } } as Parameters<typeof isShown>[0]
    expect(isShown(turn, 'A1')).toBe(true)
    expect(isShown(turn, 'A2')).toBe(false)
    expect(isShown(turn, null)).toBe(false)
    expect(isShown({ result: null }, 'A1')).toBe(false)
  })
})

describe('보내기 키', () => {
  it('Enter만 보내고, Shift+Enter·한글 조합 중 Enter는 보내지 않음', () => {
    expect(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: false })).toBe(true)
    expect(isSubmitKey({ key: 'Enter', shiftKey: true, isComposing: false })).toBe(false)
    expect(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: true })).toBe(false)
    expect(isSubmitKey({ key: 'a', shiftKey: false, isComposing: false })).toBe(false)
  })
})

describe('화면 세대', () => {
  it('보낸 뒤 화면을 바꾸면(고르기·확정일·새 대화·지난 분석 열기) 늦은 응답은 상세를 바꾸지 않음', () => {
    const generation = new ScreenGeneration()
    const sentB = generation.current // 비서에 B를 보냄
    generation.bump() // 기다리는 동안 지난 분석 A를 직접 열었다
    expect(generation.isCurrent(sentB)).toBe(false) // B가 도착해도 A를 덮지 않는다
    const sentC = generation.current
    expect(generation.isCurrent(sentC)).toBe(true) // 그 뒤 보낸 C는 그대로 연다
  })

  it('응답 순서가 뒤집혀도 마지막으로 보낸 뒤 화면이 그대로일 때만 연다', () => {
    const generation = new ScreenGeneration()
    const first = generation.current
    generation.bump() // 목록에서 다른 설계변경을 골랐다
    const second = generation.current
    expect([generation.isCurrent(second), generation.isCurrent(first)]).toEqual([true, false])
  })
})

describe('쓰던 답·응답을 잃었을 때', () => {
  it('쓰던 답의 키는 대화와 질문을 함께 묶음(새 대화의 같은 질문 번호에 섞이지 않음)', () => {
    const q = question('value')
    expect(draftKey({ conversation_id: 'C1', questions: [q] })).toBe('C1|q@1')
    expect(draftKey({ conversation_id: 'C2', questions: [q] })).not.toBe(draftKey({ conversation_id: 'C1', questions: [q] }))
    expect(draftKey({ conversation_id: 'C1', questions: [] })).toBeNull()
  })

  it('서버 대화에서 화면이 모르는 차례만 이어 붙임', () => {
    const turns = [{ turn: 1 }, { turn: 2 }, { turn: 3 }]
    expect(missingTurns(turns, 1)).toEqual([{ turn: 2 }, { turn: 3 }])
    expect(missingTurns(turns, 3)).toEqual([])
  })
})

describe('변경 사유 기록 차례', () => {
  const turn = (conversation_id: string, analysis: string | null, reason_recorded = false) => ({
    conversation_id,
    state: 'analyzed' as const,
    reason_recorded,
    result: analysis ? { analysis_id: analysis } : null,
  })

  it('원래 차례를 다시 열면 바로 뒤에 이어진 사유 기록 차례의 마지막(결과가 같은 다른 새 분석은 따라가지 않음)', () => {
    const first = turn('C1', 'A1')
    const recorded = turn('C1', 'A1', true)
    const again = turn('C1', 'A1', true)
    const sameResultNewRequest = turn('C1', 'A1')
    const laterRecord = turn('C1', 'A1', true)
    const turns = [first, recorded, again, sameResultNewRequest, laterRecord]
    expect(latestVersion(first, turns)).toBe(again)
    expect(latestVersion(sameResultNewRequest, turns)).toBe(laterRecord)
    expect(latestVersion(turn('C1', 'A2'), turns)).toEqual(turn('C1', 'A2'))
  })
})
