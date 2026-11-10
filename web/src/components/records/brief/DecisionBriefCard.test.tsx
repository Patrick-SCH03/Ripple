// 결정 도우미 카드의 상태(뼈대 · 실패 · AI/기본 칩 · 사례 없음 · 합성 칩)를 정적 렌더로 본다.
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { DecisionBrief, PastCase } from '@/api/client'
import { DecisionBriefCard, type BriefGlance } from './DecisionBriefCard'
import { PastCasesList } from './PastCasesList'

const CASE: PastCase = {
  case_id: 'C-1',
  title: 'B31P 판 두께 증가(지난 호선)',
  same: ['같은 블록 B31P', '같은 변경 종류 판 두께'],
  decision: 'approve',
  chosen: '대안으로 진행',
  predicted: { value: 2_980_000, low: 2_000_000, high: 4_000_000 },
  actual_krw: 3_300_000,
  predicted_delay_days: 0,
  actual_delay_days: 0,
  days_before_deadline: 3,
  note: '',
  synthetic: true,
}

function brief(over: Partial<DecisionBrief> = {}): DecisionBrief {
  return {
    ecn_id: 'ECN-D-0119',
    revision: 2,
    record_id: 'R-0000000000000002',
    data_mode: 'synthetic',
    lines: [
      { kind: 'change', text: '두께 변경 — 영향 20곳 · 총변경비용 3,421만원이에요.', template_id: 'change.summary' },
      { kind: 'loss', text: '10월 27일(화)까지(D-7) 확정하면 비용이 그대로예요.', template_id: 'loss.by_date' },
      { kind: 'advice', text: '판정 경고 — 구역 출구 일정 지연 가능 · 담당자 근거 확인 후 결정', template_id: 'advice.review' },
    ],
    checks: [
      {
        key: 'assume:lead_time',
        text: '새 자재 리드타임을 대표값으로 잡은 계산이에요.',
        why: '범위 끝(판재 × 1.2)으로 오면 구역 출구 지연 7일 → 24일이에요.',
        computed: true,
        entity_id: null,
      },
      {
        key: 'state:PO-0037',
        text: 'PO-0037 발주 단계를 알 수 없어요.',
        why: '단계를 몰라 비용을 가능한 범위 전체로 잡았어요.',
        computed: false,
        entity_id: 'PO-0037',
      },
    ],
    cases: { items: [], summary: null, library_size: 0, synthetic: false, status: 'ready' },
    picked_by: 'rule',
    ...over,
  }
}

const render = (view: Parameters<typeof DecisionBriefCard>[0]['view']) => renderToStaticMarkup(<DecisionBriefCard view={view} />)

describe('결정 도우미 카드', () => {
  it('불러오는 중: 머리와 자리만 잡은 뼈대(칩·문장 없음)', () => {
    const html = render({ status: 'loading' })
    expect(html).toContain('결정 도우미')
    // 되풀이 안내('숫자는 엔진 계산')는 두지 않는다(보조 한 줄 원칙 — 숫자 출처는 판정·핵심 수치와 같음)
    expect(html).not.toContain('숫자는 엔진 계산')
    expect(html).toContain('data-testid="decision-brief-skeleton"')
    expect(html).toContain('aria-busy="true"')
    expect(html).not.toContain('data-testid="decision-brief-picked"')
    expect(html).not.toContain('decision-brief-lines')
  })

  it('실패: 조용한 한 줄(결재는 그대로)', () => {
    const html = render({ status: 'error' })
    expect(html).toContain('도우미 불러오기 실패 — 결재는 그대로 가능')
    expect(html).not.toContain('decision-brief-skeleton')
  })

  it('기본 순서: 세 줄 문장은 펼침 안(기본 화면은 확인할 것 제목만) · 다시 계산함 칩은 늘 보임', () => {
    const html = render({ status: 'ready', brief: brief() })
    expect(html).toContain('data-picked="rule"')
    expect(html).toContain('기본 순서')
    // 세 줄 요약 문장은 지우지 않고 '요약 문장 보기' 펼침으로(기본은 접힘)
    expect(html).toContain('요약 문장 보기')
    expect(html).not.toContain('data-testid="decision-brief-lines"')
    expect(html).not.toContain('10월 27일(화)까지(D-7) 확정하면 비용이 그대로예요.')
    expect(html).toContain('서명 전 확인할 것 2')
    expect(html).toContain('새 자재 리드타임을 대표값으로 잡은 계산이에요.')
    // '틀리면 · …' 위험 설명은 항목별 펼침
    expect(html).not.toContain('범위 끝(판재 × 1.2)으로 오면 구역 출구 지연 7일 → 24일이에요.')
    expect(html.match(/data-testid="decision-brief-check-toggle"/g)).toHaveLength(2)
    expect(html.match(/data-testid="decision-brief-computed"/g)).toHaveLength(1)
    // 개정 요약이 없으면 큰 숫자 카드도 없음(문장만)
    expect(html).not.toContain('decision-brief-head')
  })

  it('큰 숫자 카드 셋: 총변경비용 · 결정 기한 · 권고 대안 절감(이름 · 큰 숫자 · 한 줄), 바뀌는 것 한 줄 + 블록 칩', () => {
    const glance: BriefGlance = {
      head: {
        total: { label: '총변경비용', value: '4,334만원', line: null, tone: 'neutral' },
        deadline: { label: '결정 기한', value: 'D-7', line: '11월 11일(수)까지 · 다음 날부터 +1,867만원', tone: 'neutral' },
        advice: { label: '권고 대안 절감', value: '3,614만원', line: '판 두께 대신 보강재 추가 · 720만원', tone: 'success' },
      },
      change: { title: 'B31P 판 두께 17.0→20.0mm (3장)', impacts: 20, blocks: ['B31P', 'L31C'], moreBlocks: 0 },
    }
    const html = renderToStaticMarkup(<DecisionBriefCard view={{ status: 'ready', brief: brief() }} glance={glance} />)
    expect(html).toContain('data-testid="decision-brief-head"')
    for (const text of ['총변경비용', '4,334만원', 'D-7', '권고 대안 절감', '3,614만원']) expect(html).toContain(text)
    // 한 줄은 ' · ' 마디마다 한 줄씩(가운뎃점 없이 — 금액이 홀로 떨어지거나 줄이 '·'로 시작하지 않게)
    expect(html).toContain('<span class="block">11월 11일(수)까지</span><span class="block">다음 날부터 +1,867만원</span>')
    expect(html).toContain('바뀌는 것')
    expect(html).toContain('· 영향 20곳')
    expect(html).toContain('>B31P<')
    expect(html).toContain('>L31C<')
  })
  it('AI가 고르면 그 범위(확인할 것)를 칩으로, 사례가 없으면 사례 절이 없음', () => {
    const html = render({ status: 'ready', brief: brief({ picked_by: 'ai' }) })
    expect(html).toContain('data-picked="ai"')
    expect(html).toContain('확인 항목 AI 선택')
    expect(html).not.toContain('decision-brief-cases')
  })

  it('확인할 것이 없으면 그 절을 그리지 않음', () => {
    expect(render({ status: 'ready', brief: brief({ checks: [] }) })).not.toContain('decision-brief-checks')
  })

  it('합성 과거 사례: 칩을 늘 보이고 사례마다 번호·같은 점·결정·진행·예측 → 실적·마감 전 결정, 요약 한 줄', () => {
    const cases = {
      items: [CASE],
      summary: '비슷한 1건은 실적이 예측보다 컸어요',
      library_size: 12,
      synthetic: false,
      status: 'ready' as const,
    }
    const html = render({ status: 'ready', brief: brief({ cases }) })
    expect(html).toContain('비슷한 과거 사례')
    expect(html).toContain('data-testid="decision-brief-synthetic"')
    expect(html).toContain('비슷한 1건은 실적이 예측보다 컸어요')
    // 접어서 시작: 요약과 '사례 n건 보기'만, 사례 줄은 펼쳐야 보인다(카드가 핵심 수치를 밀어내지 않게)
    expect(html).toContain('사례 1건 보기')
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('B31P 판 두께 증가(지난 호선)')
    const opened = renderToStaticMarkup(<PastCasesList cases={cases} defaultOpen />)
    expect(opened).toContain('사례 접기')
    expect(opened).toContain('aria-expanded="true"')
    expect(opened).toContain('B31P 판 두께 증가(지난 호선)')
    expect(opened).toContain('같은 블록 B31P')
    expect(opened).toContain('승인')
    expect(opened).toContain('대안으로 진행 · 예측 298만원 → 실적 330만원(+11%) · 결정 기한 3일 전 결정')
  })

  it('과거 사례를 만드는 중이면 한 줄, 이 지도에 묶음이 없으면(unavailable) 절 없음', () => {
    const building = render({
      status: 'ready',
      brief: brief({ cases: { items: [], summary: null, library_size: 0, synthetic: false, status: 'building' } }),
    })
    expect(building).toContain('과거 사례 준비 중')
    expect(building).not.toContain('decision-brief-cases"')
    const unavailable = render({
      status: 'ready',
      brief: brief({ cases: { items: [CASE], summary: null, library_size: 1, synthetic: true, status: 'unavailable' } }),
    })
    expect(unavailable).not.toContain('decision-brief-cases')
    expect(unavailable).not.toContain('과거 사례 준비 중')
  })
})