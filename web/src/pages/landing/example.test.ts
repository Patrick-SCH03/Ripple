import { describe, expect, it } from 'vitest'
import {
  SHOWCASE,
  SHOWCASE_DAY,
  SHOWCASE_TODAY,
  changeText,
  costText,
  deadlineExit,
  laterText,
  laterWhy,
  nodeText,
  onDay,
  problemTitle,
  rings,
  verdictText,
  weightText,
} from './example'
import { mapSteps } from './mapSteps'

describe('소개 화면 예시(엔진 출력 example.json)', () => {
  it('첫 고리는 부재 → 블록 → 발주 → 도면 순, 두 번째 고리는 테이퍼 카드를 거쳐 번진 곳', () => {
    const { first, second } = rings(SHOWCASE.nodes)
    expect(first.map((n) => nodeText(n).action)).toEqual([
      '테이퍼 가공',
      '용접 재검토',
      '블록 재작업',
      '발주 변경·재발주',
      '도면 개정',
    ])
    expect(second.every((n) => n.parent === 'taper')).toBe(true)
    expect(second.map((n) => nodeText(n).action)).toEqual(['블록 재작업', '도면 개정'])
  })

  it('카드 문구는 JSON 값으로(개수·종류·단계·이름·금액)', () => {
    const byKey = Object.fromEntries(SHOWCASE.nodes.map((n) => [n.key, nodeText(n)]))
    expect(byKey.taper).toEqual({ subject: '맞대기 용접한 판 8개', action: '테이퍼 가공', amount: '80만원' })
    expect(byKey.weld_recheck.subject).toBe('필릿 용접한 보강재·브라켓 5개')
    expect(byKey['S-001:B31P']).toEqual({ subject: 'B31P 블록 · 선행의장 중', action: '블록 재작업', amount: '3,487만원' })
    expect(byKey['PO-0037#1']).toEqual({
      subject: '발주 PO-0037 #1 · 가공 단계',
      action: '발주 변경·재발주',
      amount: '264만원',
    })
  })

  it('바뀐 부재 + 카드 금액 = 총변경비용(그림이 빠뜨린 비용이 없음)', () => {
    const parted = SHOWCASE.change.amount + SHOWCASE.nodes.reduce((sum, n) => sum + n.amount, 0)
    expect(parted).toBe(SHOWCASE.total.value)
  })

  it('판정 상자: 총액·범위·결정 기한·D-n·구역 출구·다음 날 늘어나는 금액(총 추가손실)', () => {
    expect(changeText(SHOWCASE)).toEqual({ subject: '설계변경 ECN-D-0119', action: 'B31P 판 3장 두께 17→20mm' })
    const text = verdictText(SHOWCASE)
    expect(text).toMatchObject({
      label: '경고',
      total: '4,334만원',
      range: '1,236만~1억 250만원',
      deadline: '10월 27일(화)',
      dDay: 'D-7',
      exit: '화물탱크 구역 9일',
    })
    expect(text.later).toBe('10월 28일(수)부터 확정하면 1,867만원 늘어납니다(B31P 블록 재작업, 선행의장 → 선행도장)')
    expect(text.asOf).toBe('10월 20일(화)')
  })

  it('오늘 기준으로 옮기면 날짜만 같은 만큼 밀리고 D-n·금액은 그대로(실시간 시연 세계와 같은 달력)', () => {
    const moved = onDay(SHOWCASE, '2026-10-25')
    const text = verdictText(moved)
    expect(text).toMatchObject({ asOf: '10월 25일(일)', deadline: '11월 1일(일)', dDay: 'D-7', total: '4,334만원' })
    expect(text.later).toBe('11월 2일(월)부터 확정하면 1,867만원 늘어납니다(B31P 블록 재작업, 선행의장 → 선행도장)')
    expect(moved.horizon_end).toBe('2026-12-24')
    expect(moved.nodes).toBe(SHOWCASE.nodes)
    expect(onDay(SHOWCASE, SHOWCASE.as_of)).toBe(SHOWCASE)
  })

  it('결정 기한 다음 날: 총 추가손실(결재함 미루면·결정 기한 카드와 같은 값)과 이유 줄(블록 줄 하나의 증가분이 아님)', () => {
    const later = laterText(SHOWCASE)
    expect(later).toEqual({ on: '10월 28일(수)', amount: '1,867만원', cause: 'B31P 블록 재작업', note: '선행의장 → 선행도장' })
    const step = SHOWCASE.step_up
    expect(SHOWCASE.delay?.loss).toBeGreaterThan((step?.after ?? 0) - (step?.before ?? 0))
    expect(SHOWCASE.delay?.on).toBe(step?.on)
    expect(laterText({ ...SHOWCASE, delay: null })).toBeNull()
    const bare = laterText({ ...SHOWCASE, step_up: null })
    expect(bare && laterWhy(bare)).toBe('')
  })

  it('출구 지연 변화: 기준일 값(zone_exit)과 결정 기한 값(곡선), 결정 기한 값이 없으면 null', () => {
    expect(deadlineExit(SHOWCASE)).toEqual({ asOf: 9, atDeadline: 16 })
    expect(deadlineExit({ ...SHOWCASE, zone_exit: null })).toEqual({ asOf: 0, atDeadline: 16 })
    expect(deadlineExit({ ...SHOWCASE, deadline_exit_days: null })).toBeNull()
  })

  it('문제 절 제목: 바꾼 판 수와 찾은 영향 수는 JSON 값(두께 변경이 아니면 설계변경 한 건)', () => {
    expect(problemTitle(SHOWCASE)).toEqual(['판 3장 두께 변경 하나에', '영향 24건'])
    expect(problemTitle({ ...SHOWCASE, impact_count: 7 })[1]).toBe('영향 7건')
    const other = { ...SHOWCASE, change: { ...SHOWCASE.change, op: 'material' } }
    expect(problemTitle(other)).toEqual(['설계변경 한 건에', '영향 24건'])
  })

  it('예시 기준일은 그림을 찍은 날로 고정(불러온 날과 상관없이 그림 속 날짜와 같은 달력)', () => {
    expect(SHOWCASE_TODAY.as_of).toBe(SHOWCASE_DAY)
    expect(verdictText(SHOWCASE_TODAY)).toMatchObject({ asOf: '11월 4일(수)', deadline: '11월 11일(수)', dDay: 'D-7' })
    expect(laterText(SHOWCASE_TODAY)?.on).toBe('11월 12일(목)')
  })

  it('판단 요약 첫 줄(추가 공수·추가 재료비)과 중량 변화: 업무 화면과 같은 포맷, 공수 + 재료비 = 총변경비용', () => {
    expect(costText(SHOWCASE)).toEqual({
      hours: '807 MH',
      laborMoney: '4,007만원',
      works: '재작업 · 용접 · 가공 · 도면',
      material: '327만원',
      materialParts: '자재 차이 63만원 · 구매 264만원',
      ordered: 1,
      total: '4,334만원',
    })
    expect(SHOWCASE.cost.labor.value + SHOWCASE.cost.material.value + SHOWCASE.cost.damages).toBe(SHOWCASE.total.value)
    expect(weightText(SHOWCASE)).toBe('+0.69t')
    expect(weightText({ ...SHOWCASE, weight: null })).toBeNull()
    const noOrders = { ...SHOWCASE, cost: { ...SHOWCASE.cost, ordered: 0, purchase: null, purchases: [] } }
    expect(costText(noOrders)).toMatchObject({ ordered: null, materialParts: '자재 차이 63만원' })
  })


  it('영향 지도 단계: 바뀐 판 → 용접한 판 → 블록 → 이웃 블록 → 도면 → 발주 → 탑재, 이름·금액은 JSON 값', () => {
    const steps = mapSteps(SHOWCASE)
    expect(steps.map((s) => s.key)).toEqual(['change', 'weld', 'block', 'neighbor', 'drawings', 'po', 'erection'])
    expect(steps.map((s) => s.title)).toEqual([
      '바뀐 판 3장',
      '맞대기 용접한 판 8개',
      'B31P 블록 재작업',
      '이웃 L31C 블록',
      '도면 개정 2장',
      '발주 PO-0037 #1',
      'B31P 탑재 일정',
    ])
    expect(steps.map((s) => s.body)).toEqual([
      'B31P(No.3 COT 이중저 좌) 블록의 판, 두께 17→20mm',
      '테이퍼 가공 80만원 · 필릿 용접한 보강재·브라켓 5개는 용접 재검토 11만원',
      '선행의장 중인 블록이라 재작업비 3,487만원',
      '맞대기 용접으로 이어진 중심선 종격벽 블록(대조립 중)도 재작업 294만원',
      'DWG-B31P-H01 · DWG-L31C-H01, 장마다 67만원',
      '가공 단계에 들어간 발주라 발주 변경·재발주 264만원',
      '화물탱크 구역 출구가 최대 9일 늦어질 수 있습니다',
    ])
  })

  it('영향 지도 단계: 값이 없는 단계는 빠진다(이웃 블록·발주·구역 출구 지연 없음)', () => {
    const nodes = SHOWCASE.nodes.filter((n) => n.key !== 'S-001:L31C' && n.entity_type !== 'po_line')
    const keys = mapSteps({ ...SHOWCASE, nodes, zone_exit: null }).map((s) => s.key)
    expect(keys).toEqual(['change', 'weld', 'block', 'drawings'])
  })
})
