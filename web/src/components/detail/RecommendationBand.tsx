// 권고 대안 띠(검토 요청 전 상세 핵심 수치 위): 더 저렴한 대안이 있으면 담당자가 결재를 올리기 전에 본다 — 결재자는 결정 도우미의
// '권고'로 같은 내용을 본다. 계산은 대안 탭과 같은 것(alternatives/useAlternatives, 같은 기억)이라 탭을 열어도 다시 계산하지 않는다.
// 요청안이 최저가이거나 대안 계산이 끝나지 않았거나 실패하면 그리지 않는다(대안 탭이 그 상태를 보인다).
import { Lightbulb } from 'lucide-react'
import type { AnalysisRequest, AnalysisResult } from '@/api/client'
import { Button } from '@/components/ui/button'
import { REQUEST_ALT, mayHaveAlternatives, recommendationHeadline } from '@/lib/alternatives'
import { cn } from '@/lib/utils'
import { EligibilityBadge, OpenAlternative } from './alternatives/AlternativeRow'
import { useAlternatives } from './alternatives/useAlternatives'

interface Props {
  result: AnalysisResult
  compact: boolean
  /** '이 대안으로 분석 보기'(대안 탭과 같은 길). */
  onOpen: (request: AnalysisRequest, label: string) => void
  /** '대안 비교': 대안 탭을 연다. */
  onCompare: () => void
}

export function RecommendationBand({ result, compact, onOpen, onCompare }: Props) {
  // 대안이 생길 수 없는 요청(배관·장비·삭제 등)은 대안 포함 분석을 보내지 않는다
  const loaded = useAlternatives(result, mayHaveAlternatives(result.request))
  if (!loaded || 'error' in loaded) return null
  const data = loaded.data
  const chosen = data.alternatives.find((a) => a.alt_id === data.recommendation?.alt_id)
  const headline = recommendationHeadline(data)
  if (!chosen || chosen.alt_id === REQUEST_ALT || !headline) return null
  return (
    <section
      aria-label="권고 대안"
      data-testid="recommendation-band"
      className="flex flex-wrap items-start gap-x-4 gap-y-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2.5"
    >
      <Lightbulb aria-hidden className="mt-1 size-4 shrink-0 text-primary" />
      <div className="min-w-0 flex-1 basis-64">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold">더 저렴한 대안 · {headline.title}</span>
          <EligibilityBadge alternative={chosen} />
        </p>
        <p className="mt-0.5 text-sm text-foreground-secondary">{headline.detail}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" className={cn(compact && 'h-11 px-3')} onClick={onCompare}>
          대안 비교
        </Button>
        <OpenAlternative alternative={chosen} request={result.request} compact={compact} onOpen={onOpen} />
      </div>
    </section>
  )
}
