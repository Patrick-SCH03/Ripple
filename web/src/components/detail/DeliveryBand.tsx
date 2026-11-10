// 인도 임박 띠(lib/deliveryImminent): 상세 핵심 수치 위와 대안 탭 맨 위. 표시만 — 순위·계산은 바꾸지 않는다.
import { CalendarClock } from 'lucide-react'
import type { AnalysisResult } from '@/api/client'
import { InfoPop } from '@/components/common/InfoPop'
import { deliveryImminent } from '@/lib/deliveryImminent'

export function DeliveryBand({ result }: { result: Pick<AnalysisResult, 'schedule'> }) {
  const band = deliveryImminent(result)
  if (!band) return null
  // 보조 한 줄은 첫 조각(인도 n일 지연)만, 계산 범위 안내('대안 순위·금액 계산은 그대로')는 ⓘ
  const [lead, ...rest] = band.detail.split(' · ')
  return (
    <div
      role="note"
      className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/8 px-3 py-2"
      data-testid="delivery-imminent"
    >
      <CalendarClock aria-hidden className="mt-1 size-4 shrink-0 text-warning" />
      <p>
        <span className="font-semibold">{band.title}</span>
        <span className="flex items-center gap-1.5 text-sm text-foreground-secondary">
          {lead}
          {rest.length > 0 && <InfoPop title="인도 임박" lines={rest} />}
        </span>
      </p>
    </div>
  )
}
