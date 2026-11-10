import { describe, expect, it } from 'vitest'
import { groupNotes, noteItems } from './resultNotes'

// 서버 문구 그대로(ripple/engine/analyze.py · propagate.py · cost/material.py · cost/demand.py)
const SCHEDULE =
  '일정은 파라미터 대표값으로 계산하고, 새 자재가 리드타임 범위 끝에 오는 경우는 일정 위험으로 따로 보여요. ' +
  '진수·인도는 구역 경계 조건(여유)으로 계산해요. ' +
  '인력·정반·크레인 같은 자원 제약과 납기 변동은 반영하지 않은 추정이에요.'
const COST = '지체상금 말고 일정 지연 자체의 간접비는 넣지 않았어요.'
const LIMITATION = '같은 종류 연결 중 일부만 빠진 경우(예: 격자 이웃 하나 누락)는 입력에 완전성 정보가 없어 찾지 못해요.'
const ESTIMATE = '확정일이 기준일 뒤라 그날 단계는 기준일까지의 근거와 계획으로 추정했어요.'
const EFFECTIVE = '적용 시작일(2026-10-18)이 확정일(2026-10-20)보다 앞서요. 날짜를 확인해 주세요.'
const PRICE = '새 규격 PL-AH36-17 단가가 지도에 없어 원래 단가로 계산했어요'
const UNIT = 'PIPE-150 단위가 t가 아니라 두께 변경 수량을 그대로 두었어요'
const RATIO = '강종 EH40의 단가 비율이 파라미터에 없어 강종 단가 차이를 0으로 봤어요'
const CONSUMER = '공급 발주 품목의 소비 공정이 지도에 없어 일정 제약을 두지 않았어요'
const UNKNOWN = '처음 보는 안내예요. 두 문장이에요.'
// 명사형 개조식 서버 문구: ' · '로 이은 한 안내
const SCHEDULE_NOUN =
  '일정은 파라미터 대표값 기준 · 새 자재가 리드타임 범위 끝에 오는 경우는 일정 위험으로 별도 표시 · ' +
  '진수·인도는 구역 경계 조건(여유)으로 계산 · 인력·정반·크레인 등 자원 제약과 납기 변동 미반영'
const COST_NOUN =
  '일정 지연 자체의 간접비(작업반 대기·재배치)는 총변경비용 제외 — 지연 파급 비용(가정)으로 별도 표시 · ' +
  '공정 여유로 흡수되는 지연은 빼고 구역 출구가 실제로 밀리는 날만 산입 · 인도 지연으로 지체상금에 넣은 날도 제외'
const PRICE_NOUN = '새 규격 PL-AH36-17 단가가 지도에 없음 — 원래 단가로 계산'
const RATIO_NOUN = '강종 EH40의 단가 비율이 파라미터에 없음 — 강종 단가 차이 0으로 처리'
const LIMITATION_NOUN = '같은 종류 연결 중 일부만 빠진 경우(예: 격자 이웃 하나 누락)는 입력에 완전성 정보가 없어 탐지 불가'
const ESTIMATE_NOUN = '확정일이 기준일 뒤라 그날 단계는 기준일까지의 근거와 계획으로 추정'
const INVALID_NOUN = 'T2 강종 상향: 지도와 맞지 않아 제외(PL-1 규격 불일치 — 지도 A · 요청 B)'
const NEW_WORK_NOUN = '새 부재 제작 공수는 비용에만 반영 · 공정 기간 미반영'
const EFFECTIVE_NOUN = '적용 시작일(2026-10-18)이 확정일(2026-10-20)보다 앞섬 — 날짜 확인 필요'
const UNIT_NOUN = 'PIPE-150 단위가 t 이외 — 두께 변경 수량 그대로 유지'
const CONSUMER_NOUN = '공급 발주 품목의 소비 공정이 지도에 없음 — 일정 제약 미적용'
const ALT_NOUN = '대안 판정은 요청안 대비 예비 비교 · 선급 판정 아님 — 좌굴·선체 거더 강도·피로 미검토'

const KNOWN = [LIMITATION, ESTIMATE, PRICE, UNIT, RATIO, CONSUMER, SCHEDULE, COST, EFFECTIVE]
// 항목 사이 구분자(문장 끝 공백 · ' · ')는 항목 경계에서 빠지므로 공백 하나로 맞춰 견준다
const normalize = (text: string) => text.trim().replace(/\s+·\s+/g, ' ').replace(/\s+/g, ' ')

describe('결과 안내 묶음', () => {
  it('사람이 확인할 것(날짜·단가·단위·연결)과 늘 붙는 가정·한계를 가름', () => {
    const groups = groupNotes(KNOWN)
    expect(groups.check.map((item) => item.label)).toEqual([
      '단가 없음',
      '단위 확인',
      '강종 단가 비율 없음',
      '일정 제약 빠짐',
      '날짜 확인',
    ])
    expect(groups.assumption.map((item) => item.label)).toEqual([
      '일부 연결 누락 미탐지',
      '확정일 단계는 추정',
      '일정은 대표값',
      '진수·인도는 경계 조건',
      '자원 제약 미반영',
      '간접비 제외',
    ])
    expect(groups.other).toEqual([])
  })

  it('라벨 없는 뒷문장은 앞 항목에 이어 붙이고(날짜 확인 한 항목), 모르는 안내는 통째로 참고', () => {
    expect(noteItems([EFFECTIVE])).toEqual([{ kind: 'check', label: '날짜 확인', text: EFFECTIVE }])
    expect(noteItems([UNKNOWN])).toEqual([{ kind: 'other', label: '참고', text: UNKNOWN }])
  })

  it('성질: 문장을 빼거나 바꾸지 않음 — 안내마다 항목 글을 이으면 원문, 묶음 합은 전체 항목 수', () => {
    const pool = [...KNOWN, UNKNOWN, '숫자 1.2배는 나뉘지 않아요. 끝.', SCHEDULE_NOUN, ALT_NOUN, '모르는 조각 · 둘째 조각']
    for (let seed = 1; seed <= 50; seed += 1) {
      // 고정 씨앗으로 안내 몇 개를 고른다(순서·중복 섞임)
      const picked = Array.from({ length: (seed % 6) + 1 }, (_, i) => pool[(seed * 7 + i * 3) % pool.length])
      const items = noteItems(picked)
      const perNote = picked.map((note) => noteItems([note]))
      expect(items).toEqual(perNote.flat())
      perNote.forEach((noteList, i) => {
        expect(noteList.length).toBeGreaterThan(0)
        expect(normalize(noteList.map((item) => item.text).join(' '))).toBe(normalize(picked[i]))
        for (const item of noteList) expect(item.label.length).toBeGreaterThan(0)
      })
      const groups = groupNotes(picked)
      expect(groups.check.length + groups.other.length + groups.assumption.length).toBe(items.length)
    }
  })

  it('명사형 서버 문구도 같은 라벨 — 가운뎃점으로 이은 가정은 항목마다 나뉘고, 라벨 없는 조각은 앞 항목에 구분자째 이어짐', () => {
    const groups = groupNotes([UNIT_NOUN, CONSUMER_NOUN, SCHEDULE_NOUN, COST_NOUN, EFFECTIVE_NOUN, ALT_NOUN])
    expect(groups.check.map((item) => item.label)).toEqual(['단위 확인', '일정 제약 빠짐', '날짜 확인'])
    expect(groups.assumption.map((item) => item.label)).toEqual([
      '일정은 대표값',
      '진수·인도는 경계 조건',
      '자원 제약 미반영',
      '간접비 제외',
      '대안은 예비 비교',
    ])
    expect(groups.assumption[0].text).toBe(
      '일정은 파라미터 대표값 기준 · 새 자재가 리드타임 범위 끝에 오는 경우는 일정 위험으로 별도 표시',
    )
    expect(groups.assumption[4].text).toBe(ALT_NOUN)
    expect(groups.assumption[3].text).toBe(COST_NOUN)
    expect(groups.other).toEqual([])
  })

  it('지금 서버의 명사형 문구 전부가 라벨을 얻음 — 문제 목록 안의 가운뎃점은 앞 항목에 이어짐', () => {
    const notes = [PRICE_NOUN, RATIO_NOUN, LIMITATION_NOUN, ESTIMATE_NOUN, INVALID_NOUN, NEW_WORK_NOUN]
    const items = noteItems(notes)
    expect(items.map((item) => item.label)).toEqual([
      '단가 없음',
      '강종 단가 비율 없음',
      '일부 연결 누락 미탐지',
      '확정일 단계는 추정',
      '대안 제외',
      '새 부재 공수는 비용만',
    ])
    expect(items[4].text).toBe(INVALID_NOUN)
    expect(items[5].text).toBe(NEW_WORK_NOUN)
  })

  it('빈 안내는 빈 묶음', () => {
    expect(groupNotes([])).toEqual({ check: [], other: [], assumption: [] })
  })
})
