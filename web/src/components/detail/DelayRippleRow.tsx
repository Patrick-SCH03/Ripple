// 비용 탭 합계 아래 '총액 밖' 줄(계약 1.32.0, 명세 4-11): 지연 파급 비용(가정). 총변경비용에 더하지 않는 참고 금액이라
// 합계 아래에 선을 긋고 따로 둔다. 0원이어도 숨기지 않고 이유를 적는다(이 판을 계산하지 않은 옛 기록이면 줄이 없음).
// 펼치면 발생 사유 · 계산(지연 일수 × 하루 비용) · 가정과 범위(하루 비용 근거) · 쓰지 않는 곳.
import { ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { AnalysisResult } from '@/api/client'
import { TermInfo } from '@/components/common/TermInfo'
import { FACTOR_STATUS_NAMES, factorText } from '@/lib/costDetail'
import { DELAY_RIPPLE_SCOPE, delayRippleView } from '@/lib/delayRipple'
import { cn } from '@/lib/utils'

const DETAIL_ID = 'delay-ripple-detail'

export function DelayRippleRow({ result }: { result: AnalysisResult }) {
  const [open, setOpen] = useState(false)
  const view = delayRippleView(result)
  if (!view) return null
  const amount = (
    <span className="shrink-0 text-right tabular-nums">
      <span className="block font-medium">{view.value}</span>
      {view.range && <span className="block text-sm text-foreground-secondary">{view.range}</span>}
    </span>
  )
  const label = (
    <span className="min-w-0 flex-1">
      지연 파급 비용
      <span className="ml-1.5 inline-flex h-6 items-center rounded-sm border border-border px-1.5 align-middle text-xs text-foreground-secondary">
        가정
      </span>
      {view.reason && <span className="block text-sm text-foreground-secondary">{view.reason}</span>}
    </span>
  )
  return (
    <section aria-label="총액 밖 금액" className="border-b border-border" data-testid="delay-ripple">
      {/* 어디에 더하지 않는지(DELAY_RIPPLE_SCOPE)는 ⓘ와 펼침 '쓰는 곳'에 — 머리는 '총액 밖' 한 마디 */}
      <div className="flex items-center gap-1 px-3 pt-2.5 text-sm text-foreground-secondary">
        <span className="shrink-0 font-medium whitespace-nowrap">총액 밖</span>
        <TermInfo term="delayRipple" />
      </div>
      {view.kind === 'zero' ? (
        <div className="flex min-h-9 items-center gap-3 px-3 py-2 pl-10">
          {label}
          {amount}
        </div>
      ) : (
        <>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={open ? DETAIL_ID : undefined}
            onClick={() => setOpen((v) => !v)}
            className="flex min-h-9 w-full items-center gap-3 px-3 py-2 text-left hover:bg-hover"
          >
            <ChevronRight
              aria-hidden
              className={cn('size-4 shrink-0 text-foreground-secondary transition-transform', open && 'rotate-90')}
            />
            {label}
            {amount}
          </button>
          {open && (
            <div id={DETAIL_ID} className="@container bg-muted px-3 py-3 pl-10 text-sm">
              <dl className="space-y-2.5">
                <Row title="발생 사유">
                  구역 출구 지연 → 그 일정에 묶인 작업반 대기·전환 간접비 · 공정 여유 안의 지연은 제외
                </Row>
                <Row title="계산">
                  <p className="tabular-nums">
                    {view.formula} = {view.value}
                  </p>
                  {view.overlap && <p className="text-foreground-secondary">{view.overlap}</p>}
                </Row>
                {view.factors.length > 0 && (
                  <Row title="가정과 범위">
                    {view.factors.map((factor) => {
                      const text = factorText(factor)
                      return (
                        <p key={factor.keys.join(' ')} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span>{factor.label}</span>
                          <span className="font-medium tabular-nums">{text.value}</span>
                          {text.range && <span className="text-foreground-secondary tabular-nums">범위 {text.range}</span>}
                          <span className="inline-flex h-6 items-center self-center rounded-sm border border-border px-1.5 text-xs text-foreground-secondary">
                            {FACTOR_STATUS_NAMES[factor.status]}
                          </span>
                        </p>
                      )
                    })}
                    {view.basis && <p className="text-foreground-secondary">{view.basis}</p>}
                  </Row>
                )}
                <Row title="쓰는 곳">{DELAY_RIPPLE_SCOPE} 공정 지연 크기를 금액으로 가늠하는 참고값</Row>
              </dl>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function Row({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 @md:grid-cols-[6.5rem_minmax(0,1fr)] @md:gap-3">
      <dt className="font-medium text-foreground-secondary">{title}</dt>
      <dd className="min-w-0 space-y-0.5">{children}</dd>
    </div>
  )
}
