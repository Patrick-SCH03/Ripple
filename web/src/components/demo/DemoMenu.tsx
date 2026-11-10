// 위 막대 '시연' 단추: 누르면 시나리오 메뉴(이름 + 한 줄 설명), 고르면 화면이 스스로 진행한다(발표장에서 누르는 용도).
// 지금 지도에 시나리오가 쓰는 설계변경이 없으면 흐리게 + '기본 합성 지도에서만 가능'. 넓은 화면(목록·상세가 나란한
// 배치) 전용이라 위 막대가 그 배치에서만 이 단추를 그린다. 가정 계산·탭 이동·되돌리기만 하고 기록은 남기지 않는다.
import { Play } from 'lucide-react'
import { useMemo } from 'react'
import type { Sample } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { scenarioReady } from '@/lib/demo'
import { DEMO_SCENARIOS } from '@/lib/demoScenarios'
import { DemoBand } from './DemoBand'
import { DemoRing } from './DemoRing'
import { useDemoRunner } from './useDemoRunner'

interface Props {
  /** 지금 지도의 설계변경 목록(시나리오를 돌릴 수 있는지 본다). */
  samples: readonly Sample[]
}

export function DemoMenu({ samples }: Props) {
  const runner = useDemoRunner()
  const ids = useMemo(() => new Set(samples.map((sample) => sample.ecn_id)), [samples])
  const running = runner.state.phase === 'running'
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant={running ? 'secondary' : 'outline'}
            aria-label="시연"
            title="시나리오를 고르면 화면이 자동 진행"
            data-testid="demo-menu"
          >
            <Play aria-hidden />
            {/* 1280px 미만은 아이콘만 — 위 막대의 호선·기준일이 잘리지 않게 */}
            <span className="hidden xl:inline">시연</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-80">
          <DropdownMenuLabel>시연 시나리오</DropdownMenuLabel>
          {DEMO_SCENARIOS.map((scenario, index) => {
            const ready = scenarioReady(scenario, ids)
            return (
              <DropdownMenuItem
                key={scenario.id}
                disabled={!ready}
                onSelect={() => runner.start(scenario)}
                className="items-start"
                data-demo={scenario.id}
              >
                <span
                  aria-hidden
                  className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold tabular-nums"
                >
                  {index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block font-medium">{scenario.name}</span>
                  <span className="block text-xs text-foreground-secondary">
                    {ready ? scenario.summary : '기본 합성 지도에서만 가능'}
                  </span>
                </span>
              </DropdownMenuItem>
            )
          })}
          <DropdownMenuSeparator />
          <p className="px-2 py-1.5 text-xs text-foreground-secondary">
            분석 · 가정 계산 · 되돌리기만 — 기록 · 검토 요청 · 결재는 제외 · 화면 클릭 또는 Esc로 중지
          </p>
        </DropdownMenuContent>
      </DropdownMenu>
      <DemoBand state={runner.state} bandRef={runner.bandRef} onStop={runner.stop} />
      <DemoRing target={runner.state.spot} press={runner.state.press} />
    </>
  )
}
