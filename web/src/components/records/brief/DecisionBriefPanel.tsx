// 결재 띠 안의 결정 도우미 자리: 팀장이고 진행 중 검토(검토·보류)가 있을 때만 불러와 그린다(lib/brief briefTarget).
// 맨 위 큰 숫자 카드의 재료: 그 개정의 요약(총변경비용·결정 기한) + 화면의 분석이 그 개정과 같을 때만 그 결과(다음 날 금액·
// 영향 곳·블록)와 대안 포함 계산(권고 대안 절감 — 대안 탭·권고 대안 띠와 같은 기억, 권고가 더 저렴한 대안일 때만 부름).
import type { AnalysisResult, EcnDetail, Me } from '@/api/client'
import { hasAlternatives, mayHaveAlternatives } from '@/lib/alternatives'
import { briefHead, briefTarget, changeHead, cheaperOf, wantsCheaper } from '@/lib/brief'
import { useAlternatives } from '@/components/detail/alternatives/useAlternatives'
import { DecisionBriefCard, type BriefGlance } from './DecisionBriefCard'
import { useDecisionBrief } from './useDecisionBrief'

interface Props {
  me: Me
  detail: EcnDetail | null
  /** 화면의 분석(결재 띠가 그릴 때 늘 있음). */
  result: AnalysisResult
  /** 화면의 분석 = 마지막 기록(그 개정의 결과로 숫자를 읽어도 되는가). */
  shownMatches: boolean
  /** 업무상 오늘(결재함 D-n과 같은 기준). */
  today: string
}

export function DecisionBriefPanel({ me, detail, result, shownMatches, today }: Props) {
  const target = briefTarget(me, detail)
  const view = useDecisionBrief(target)
  const brief = view?.status === 'ready' ? view.brief : null
  const shown = shownMatches ? result : null
  // 기록에 대안이 이미 있으면 그 결과, 없으면 대안 포함 계산(권고가 더 저렴한 대안일 때만 보냄)
  const own = shown !== null && hasAlternatives(shown)
  const need = brief !== null && shown !== null && !own && wantsCheaper(brief) && mayHaveAlternatives(shown.request)
  const loaded = useAlternatives(result, need)
  if (!view) return null
  const revision = detail?.revisions.find((r) => r.record_id === target?.recordId) ?? null
  let glance: BriefGlance | null = null
  if (brief && revision) {
    const source = own ? shown : loaded && 'data' in loaded ? loaded.data : null
    const changeLine = brief.lines.find((line) => line.kind === 'change')?.text ?? ''
    glance = {
      head: briefHead(brief, revision, today, shown, source ? cheaperOf(source) : null),
      change: changeHead(revision.title, shown, changeLine),
    }
  }
  return <DecisionBriefCard view={view} glance={glance} />
}
