import { describe, expect, it } from 'vitest'
import { callSummary, callTime, latencyLabel, outcomeLabel, taskLabel } from './llmCalls'

describe('AI 호출 기록 표시', () => {
  it('작업 이름: 아는 작업은 한국어, 모르는 작업은 그대로', () => {
    expect(taskLabel('rewrite')).toBe('해석 보조')
    expect(taskLabel('explain')).toBe('설명 고르기')
    expect(taskLabel('brief')).toBe('결정 도우미 고르기')
    expect(taskLabel('extract')).toBe('문서 항목 추출')
    expect(taskLabel('default')).toBe('default')
  })

  it('결과: 성공 / 실패 · 종류 / 종류 없는 실패', () => {
    expect(outcomeLabel({ ok: true, error: '' })).toBe('성공')
    expect(outcomeLabel({ ok: false, error: 'LlmUnavailable' })).toBe('실패 · LlmUnavailable')
    expect(outcomeLabel({ ok: false, error: '' })).toBe('실패')
  })

  it('걸린 시간: 1초 미만 ms, 그 위 소수 한 자리 초, 이상한 값은 —', () => {
    expect(latencyLabel(0)).toBe('0ms')
    expect(latencyLabel(999)).toBe('999ms')
    expect(latencyLabel(1000)).toBe('1.0초')
    expect(latencyLabel(4321)).toBe('4.3초')
    expect(latencyLabel(-1)).toBe('—')
    expect(latencyLabel(Number.NaN)).toBe('—')
  })

  it('시각은 KST(UTC+9)로, 자정을 넘기면 날짜도 바뀜', () => {
    expect(callTime('2026-10-09T16:31:59Z')).toBe('10월 10일 01:31:59')
    expect(callTime('2026-10-09T14:59:59+00:00')).toBe('10월 9일 23:59:59')
    expect(callTime('아님')).toBe('—')
  })

  it('요약: 건수·성공·실패, 비면 null', () => {
    expect(callSummary([])).toBeNull()
    expect(callSummary([{ ok: true }, { ok: false }, { ok: true }])).toBe('최근 3건 · 성공 2 · 실패 1')
  })
})
