// 변경 원인 안내(상세 머리, DESIGN.md 6절 '변경 원인', docs/domain.md 14절): 제목 한 줄 + 굵은 핵심 구절로 시작하는 짧은 항목.
// 계산이 바뀌는 선주 요청(허용 지연, docs/engine.md(비용·일정) 4-6)과 지체상금을 그대로 두는 선급·규정에만 낸다.
// 조문 안내는 법률 판단이 아니라 조문 그대로다 — 사실·숫자·조항·'어디를 보라'는 줄이지 않는다.
import type { ChangeCause } from './request'

export interface CauseNote {
  title: string
  items: readonly { lead: string; text: string }[]
}

export function causeNote(cause: ChangeCause | null | undefined): CauseNote | null {
  if (cause === 'owner_request') {
    return {
      title: '선주 요청 변경 — 늘어난 인도 지연은 지체상금 대신 인도일 조정으로 계산',
      items: [
        { lead: '건조계약 표준 서식 기준', text: '선주 요청 변경 = 가격·인도일 조정 대상' },
        { lead: '합의 불발 시 지체상금', text: '붙을 수 있는 지체상금은 인도 지연 카드에 따로' },
        { lead: '변경비용은 조정안 근거', text: '이 분석의 변경비용 = 선주 조정 근거' },
        {
          lead: '협력사 대금도 조정(하도급법 제16조)',
          text: '선주 증액 시 사내·사외 협력사 대금도 그 비율로 — 받은 날부터 15일 안 통지 · 30일 안 조정 · 증액 여부와 날짜 기록',
        },
      ],
    }
  }
  if (cause === 'class_rule') {
    return {
      title: '선급·규정 변경 — 지체상금 그대로 계산',
      items: [
        { lead: '계약 조항마다 다름', text: '인도일 조정 대상 여부는 계약 조항별' },
        { lead: '조정 조항이 있으면', text: '지체상금 = 합의 전 최대 노출' },
      ],
    }
  }
  return null
}
