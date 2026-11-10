// 핵심 수치 카드(DESIGN.md 2·6절): 이름 · 큰 숫자 · 행동이 바뀌는 보조 한 줄까지(lib/summary cardLine). 0·해당 없음은 내지 않는다.
// 첫 줄(계약 1.35.0 구분이 있는 결과): 총변경비용(맨 앞 큰 숫자만, lib/costSplit costHead) → 추가 공수(큰 MH · 옆 작은
// ≈금액) → 추가 재료비(큰 금액 · '이미 발주 n건 · 단계') 세 카드(현직자: 추가 공수와 추가 재료비 중심으로, 총액은 맨 앞 큰 숫자로).
// 계산식·작업 구분·자재 차이 나열·범위는 카드에 싣지 않는다(비용 탭·검토서). 둘째 줄: 결정 기한(DeadlineCard) → 구역 출구 → 인도.
// 구분이 없는 옛 기록은 이전 순서(결정 기한 → 이미 발주된 품목 → 총변경비용 → 구역 출구 → 인도, lib/ordered detailNumbers).
// 배치(컨테이너 폭, keyNumbers.css): 72rem 이상이면 결정 기한 카드가 다른 카드 두 칸 폭(2fr : 카드 수 fr), 그보다 좁으면 결정 기한 카드가
// 맨 위 한 줄 전체이고 나머지 카드는 그 아래에서 폭대로 나눈다(휴대폰 두 칸).
import './keyNumbers.css'
import type { CSSProperties } from 'react'
import type { AnalysisResult } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { HEAD_CARD, VALUE_TONE } from '@/components/common/numberCard'
import type { SubmitLine } from '@/lib/approval'
import { costHead, type CostHead } from '@/lib/costSplit'
import { GLOSSARY } from '@/lib/glossary'
import { detailNumbers } from '@/lib/ordered'
import { cardLine, type KeyNumber } from '@/lib/summary'
import { CardLabel } from './CardLabel'
import { DeadlineCard } from './DeadlineCard'

interface Props {
  result: AnalysisResult
  /** 확정일을 바꿀 수 있는가(초안이 읽히고 표시 결과 = 초안). 아니면 결정 기한 단추를 숨긴다. */
  canEdit: boolean
  compact: boolean
  onConfirmOn: (date: string | null) => void
  /** 결정 기한 카드의 작은 곡선을 누르면: 추가손실 곡선 탭을 연다. */
  onOpenCurve: () => void
  /** 결정 기한 카드 아래 '결재 올릴 기한' 한 줄(서버 결재 계획, lib/approval submitLine). 없으면 그리지 않는다. */
  submit?: SubmitLine | null
}

export function KeyNumbers(props: Props) {
  const head = costHead(props.result)
  // 구분이 있으면 총변경비용·이미 발주된 품목은 첫 줄(공수·재료비 카드와 총액 한 줄)로 옮긴다
  const cards = head ? detailNumbers(props.result).filter((card) => card.id !== 'total' && card.id !== 'ordered') : detailNumbers(props.result)
  const deadline = cards.find((card) => card.id === 'deadline')
  const rest = cards.filter((card) => card.id !== 'deadline')
  // 넓으면 결정 기한 2fr : 나머지 카드 수 fr(카드 하나 = 1fr), 나머지 묶음 안은 카드 수만큼 같은 폭
  const layout = { '--rest': `${rest.length}fr`, '--n': rest.length } as CSSProperties
  return (
    <section aria-label="핵심 수치" className="@container space-y-3">
      {head && <CostHeadRow head={head} />}
      {/* 열 배치는 keyNumbers.css(큰 글자에서 보조 줄이 접히지 않게 72rem부터 나란히) */}
      <div className="kn-row grid items-start gap-3" style={layout}>
        {/* 설계변경이 바뀌면 카드를 새로 그려 되돌리기(단추 전 확정일)를 비운다 — 다른 건의 확정일로 되돌리지 않게 */}
        {deadline && <DeadlineCard key={props.result.request.change.ecn_id ?? ''} card={deadline} {...props} />}
        {rest.length > 0 && (
          <div className="kn-rest grid gap-3">
            {rest.map((card) => (
              <Card key={card.id} card={card} />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

/** 첫 줄 큰 카드 이름(총변경비용은 진하게). */
const HEAD_LABEL = 'text-base text-foreground-secondary'

/**
 * 첫 줄: 총변경비용(맨 앞, 큰 숫자만 — 계산식·범위는 비용 탭·검토서에만) → 추가 공수 → 추가 재료비 카드(카드 칸 60rem 이상이면 한 줄 셋,
 * 그보다 좁으면(1024px 화면 포함) 총변경비용이 한 줄 전체이고 두 카드가 그 아래). 줄이 없는 쪽은 카드 대신 낮은 한 줄('추가 공수 없음').
 */
function CostHeadRow({ head }: { head: CostHead }) {
  const { labor, material, total } = head
  return (
    <div data-cost-head>
      <div className="grid grid-cols-2 gap-3 @min-[60rem]:grid-cols-3">
        <div data-key-number="total" className={`${HEAD_CARD} col-span-2 border-border-strong @min-[60rem]:col-span-1`}>
          <CardLabel label="총변경비용" term="total" className="text-base font-medium text-foreground" />
          {/* 계산식('= 공수 + 재료비')은 싣지 않는다 — 옆 두 카드가 곧 그 둘(숫자 카드 보조 줄 원칙, DESIGN.md 6절) */}
          <p className="mt-1 text-key-lg font-bold tabular-nums text-foreground">{total.value}</p>
        </div>
        {labor ? (
          <div data-key-number="labor" className={`${HEAD_CARD} border-border`}>
            <CardLabel label="추가 공수" term="labor" className={HEAD_LABEL} />
            <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
              <span className="text-key-lg font-semibold tabular-nums text-foreground">{labor.hours}</span>
              <span className="text-md font-medium tabular-nums text-foreground-secondary">{labor.money}</span>
            </p>
          </div>
        ) : (
          <NoneCard id="labor" text="추가 공수 없음" />
        )}
        {material ? (
          <div data-key-number="material" className={`${HEAD_CARD} border-border`}>
            <CardLabel label="추가 재료비" term="material" className={HEAD_LABEL} />
            <p className="mt-1 text-key-lg font-semibold tabular-nums text-foreground">{material.value}</p>
            {/* 보조 한 줄 = 구매가 바로 움직일 '이미 발주 n건 · 단계'(+ 단계 판단 불가는 경고 색). 자재 차이·구매 나열은 비용 탭 */}
            {(material.ordered || material.caution) && (
              <p className="mt-1 text-sm font-medium tabular-nums">
                {material.ordered && (
                  <span data-ordered className="text-foreground">
                    {material.ordered}
                  </span>
                )}
                {material.ordered && material.caution && <span className="text-foreground-secondary"> · </span>}
                {material.caution && (
                  <span data-caution className="text-warning">
                    {material.caution}
                  </span>
                )}
              </p>
            )}
          </div>
        ) : (
          <NoneCard id="material" text="추가 재료비 없음" />
        )}
      </div>
    </div>
  )
}

/** 줄이 없는 쪽: 큰 숫자 없이 낮은 한 줄(카드 틀은 두어 두 칸 배치가 흔들리지 않게). */
function NoneCard({ id, text }: { id: string; text: string }) {
  return (
    <div data-key-number={id} className="flex items-center rounded-md border border-border bg-surface px-4 py-3">
      <p className="text-sm text-foreground-secondary">{text}</p>
    </div>
  )
}

/** 둘째 줄 결정 기한 밖 카드(구역 출구 · 인도 · 옛 기록의 총변경비용·이미 발주된 품목). */
function Card({ card }: { card: KeyNumber }) {
  const line = cardLine(card)
  return (
    <div data-key-number={card.id} className="rounded-md border border-border bg-surface px-4 py-3">
      <CardLabel label={card.label} term={card.id} />
      <p className="mt-1 flex flex-wrap items-baseline gap-x-3">
        {/* text-key는 cn으로 합치지 않는다(numberCard.ts) */}
        <span className={`text-key font-semibold tabular-nums ${VALUE_TONE[card.tone]}`}>{card.value}</span>
        {card.outside && (
          // 지연 파급 비용(가정 · 총액 밖)은 참고 금액이라 큰 숫자 옆 이름 단추 + ⓘ(금액은 펼침 첫 줄) — 줄을 늘리지 않게
          <span data-outside>
            <InfoPop title="지연 파급 비용(가정)" lines={[card.outside, ...GLOSSARY.delayRipple.body]} label="지연 파급 비용" />
          </span>
        )}
      </p>
      {line && (
        <p
          data-caution={line.tone === 'warning' ? '' : undefined}
          className={`mt-1 text-sm ${line.tone === 'warning' ? 'text-warning' : 'font-medium text-foreground'}`}
        >
          {line.text}
        </p>
      )}
    </div>
  )
}
