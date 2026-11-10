// 근거 상세 구역의 탭(DESIGN.md 2절 5): 비용 · 일정 · 추가손실 곡선 · 대안 · 이력. 고른 탭은 바깥(Workbench)이 든다.
import type { AnalysisResult } from '@/api/client'
import { HistoryTab } from '@/components/records/HistoryTab'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DETAIL_TABS_ID } from '@/lib/domIds'
import { cn } from '@/lib/utils'
import type { AnalysisSession } from '@/state/useAnalysisSession'
import type { RecordsState } from '@/state/useRecords'
import { AlternativesTab } from './AlternativesTab'
import { CostTable } from './CostTable'
import { CurveTab } from './CurveTab'
import { PoActions } from './PoActions'
import { ScheduleView } from './ScheduleView'

export type DetailTab = 'cost' | 'schedule' | 'curve' | 'alternatives' | 'history'

const TABS: readonly { id: DetailTab; label: string }[] = [
  { id: 'cost', label: '비용' },
  { id: 'schedule', label: '일정' },
  { id: 'curve', label: '추가손실 곡선' },
  { id: 'alternatives', label: '대안' },
  { id: 'history', label: '이력' },
]

interface Props {
  result: AnalysisResult
  session: AnalysisSession
  records: RecordsState
  compact: boolean
  tab: DetailTab
  onTab: (tab: DetailTab) => void
  onEvidence: (entityId: string) => void
}

export function EvidenceTabs({ result, session, records, compact, tab, onTab, onEvidence }: Props) {
  return (
    <Tabs value={tab} onValueChange={(value) => onTab(value as DetailTab)} className="gap-3">
      <TabsList
        id={DETAIL_TABS_ID}
        variant="line"
        // 구역 이동 막대(고정)에 탭 줄이 가리지 않게. 좁은 화면·큰 글자에서도 카드 밖으로 넘치지 않게 가로로 밀어 보기
        className={cn('no-scrollbar w-full scroll-mt-14 justify-start overflow-x-auto border-b border-border', compact && 'h-11 gap-0')}
      >
        {TABS.map(({ id, label }) => (
          <TabsTrigger
            key={id}
            value={id}
            className={cn(
              'flex-none text-foreground-secondary data-active:text-foreground dark:text-foreground-secondary',
              compact ? 'px-2' : 'px-3',
            )}
          >
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="cost">
        <PoActions result={result} />
        <CostTable result={result} compact={compact} onEvidence={onEvidence} />
      </TabsContent>
      <TabsContent value="schedule">
        <ScheduleView result={result} />
      </TabsContent>
      <TabsContent value="curve">
        <CurveTab key={result.analysis_id} result={result} />
      </TabsContent>
      <TabsContent value="alternatives">
        <AlternativesTab
          result={result}
          compact={compact}
          onOpen={(request, label) => {
            session.open(request, label)
            onTab('cost')
          }}
        />
      </TabsContent>
      <TabsContent value="history">
        {/* 다른 설계변경을 고른 직후(새 분석 전)에는 아래 결과와 다른 설계변경의 이력을 섞어 보이지 않는다 */}
        <HistoryTab
          detail={records.detail}
          waiting={records.ecnId !== result.request.change.ecn_id || !records.detailReady}
        />
      </TabsContent>
    </Tabs>
  )
}
