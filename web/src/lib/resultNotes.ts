// 결과 안내 문장(분석 결과 notes)을 핵심이 먼저 보이게 나눈다: 사람이 확인할 것(위, 눈에 띄게) · 참고(모르는 문장) ·
// 이 계산의 가정(늘 붙는 가정·한계). 서버 문장은 고치지 않고 그대로 쓰며, 여기서는 짧은 굵은 라벨과 묶음만 정한다.
// 문장을 빼지 않는다: 한 안내의 문장들을 이어 붙이면 원문과 같다(resultNotes.test.ts가 검사).
export type NoteKind = 'check' | 'other' | 'assumption'

export interface NoteItem {
  kind: NoteKind
  /** 짧은 굵은 라벨(명사형) — 접어도 첫 화면에 보이는 핵심. */
  label: string
  /** 서버 문장 그대로(한 문장 또는 이어진 문장들). */
  text: string
}

interface Rule {
  test: RegExp
  kind: Exclude<NoteKind, 'other'>
  label: string
}

/**
 * 문장 → 라벨. 서버 문구(ripple/engine/analyze.py · propagate.py · cost/material.py · cost/demand.py ·
 * alternatives/compare.py)를 문장 단위로 알아본다. 위에서부터 처음 맞는 것.
 */
const RULES: readonly Rule[] = [
  // 사람이 확인할 것: 입력 날짜·지도 단가·단위·연결이 모자라 계산을 줄이거나 바꿨다
  // (서버 문구는 명사형 — 해요체로 저장된 옛 기록도 알아보게 두 꼴을 함께 받는다)
  { test: /^적용 시작일.*확정일.*앞(서요|섬)/, kind: 'check', label: '날짜 확인' },
  { test: /단위가 t(가 아니라| 이외)/, kind: 'check', label: '단위 확인' },
  { test: /단가 비율이 파라미터에 없/, kind: 'check', label: '강종 단가 비율 없음' },
  { test: /단가가 지도에 없/, kind: 'check', label: '단가 없음' },
  { test: /일정 제약(을 두지 않았| 미적용)/, kind: 'check', label: '일정 제약 빠짐' },
  { test: /지도와 맞지 않아 (뺐|제외)/, kind: 'check', label: '대안 제외' },
  // 이 계산의 가정·한계(일정·비용·연결 찾기)
  { test: /^일정은 파라미터 대표값/, kind: 'assumption', label: '일정은 대표값' },
  { test: /^진수·인도는 구역 경계 조건/, kind: 'assumption', label: '진수·인도는 경계 조건' },
  { test: /자원 제약.*(반영하지 않은|미반영)/, kind: 'assumption', label: '자원 제약 미반영' },
  { test: /간접비.*(넣지 않았|총변경비용 제외)/, kind: 'assumption', label: '간접비 제외' },
  { test: /^같은 종류 연결 중 일부만 빠진/, kind: 'assumption', label: '일부 연결 누락 미탐지' },
  { test: /^확정일이 기준일 뒤/, kind: 'assumption', label: '확정일 단계는 추정' },
  { test: /^대안 판정은 요청안 대비 예비 비교/, kind: 'assumption', label: '대안은 예비 비교' },
  { test: /공수는 비용에만/, kind: 'assumption', label: '새 부재 공수는 비용만' },
]
/**
 * 안내 하나를 조각으로 나눈다: 마침표 뒤 공백(옛 해요체 문장) 또는 ' · '(명사형 개조식). 소수점(1.2)·'진수·인도'처럼
 * 공백 없는 점은 나뉘지 않는다. 조각마다 앞 구분자(첫 조각은 '')를 함께 돌려, 이어 붙일 때 원문 그대로 되게 한다.
 */
function sentences(note: string): { sep: string; text: string }[] {
  const parts = note.trim().split(/((?<=[.!?])\s+|\s+·\s+)/)
  const out: { sep: string; text: string }[] = []
  for (let i = 0; i < parts.length; i += 2) {
    if (parts[i] !== '') out.push({ sep: i === 0 ? '' : parts[i - 1], text: parts[i] })
  }
  return out
}

/**
 * 안내 문장들을 항목으로. 문장마다 라벨을 찾고, 라벨이 없는 문장은 같은 안내의 앞 항목에 이어 붙인다
 * ('…앞섬 — 날짜 확인 필요'·'…앞서요. 날짜를 확인해 주세요.'가 한 항목). 첫 문장부터 모르면 그 안내 전체가 '참고' 한 항목.
 */
export function noteItems(notes: readonly string[]): NoteItem[] {
  const items: NoteItem[] = []
  for (const note of notes) {
    let current: NoteItem | null = null
    for (const { sep, text: sentence } of sentences(note)) {
      const rule = RULES.find((candidate) => candidate.test.test(sentence))
      if (rule) {
        current = { kind: rule.kind, label: rule.label, text: sentence }
        items.push(current)
      } else if (current) {
        current.text = `${current.text}${sep}${sentence}`
      } else {
        current = { kind: 'other', label: '참고', text: sentence }
        items.push(current)
      }
    }
  }
  return items
}

/** 화면 묶음: 확인할 것(위) · 참고 · 이 계산의 가정(접어도 라벨은 보임). 묶음 안 순서는 서버 순서 그대로. */
export function groupNotes(notes: readonly string[]): Record<NoteKind, NoteItem[]> {
  const groups: Record<NoteKind, NoteItem[]> = { check: [], other: [], assumption: [] }
  for (const item of noteItems(notes)) groups[item.kind].push(item)
  return groups
}
