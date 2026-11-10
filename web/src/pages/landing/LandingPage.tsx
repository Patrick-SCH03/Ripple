// 소개 화면(공개, docs/operations.md(서비스) 3절 · DESIGN.md 12절): 서비스를 홍보·소개하는 페이지 — 절마다 짧고 힘 있는 제목,
// 가치 한 줄(필요한 곳만), 큰 그림·영상·스크롤 연출. 기능 계산·구현 설명 문단은 두지 않는다.
// 순서는 첫 화면 흐름 띠와 같다 — 첫 화면(제목 + 흐름 장면) → 설계변경 한 건의 영향(움직이는 파급 그림) → 3D 배치(물결 전파
// 반복 영상) → 2D 영향 지도(고정 그림 둘러보기) → 판단 요약 → 결정 기한 → 대안 비교 → 결재·검토서 → AI 비서 → 운영 조건·잰 값
// → 마지막 단추. 숫자는 엔진 출력(example.json)과 잰 값(content.ts MEASURED)만, 그림·영상은 그 예시를 찍은 실제 화면(captures.ts).
// 밝게만 보인다(고른 밝기와 상관없이).
import { useLightOnly } from '@/lib/theme'
import type { Session } from '@/state/useSession'
import { VALUE } from './content'
import { SHOWCASE, problemTitle } from './example'
import { EndCall, MeasuredList, TrustBand } from './LandingBlocks'
import { LandingActions } from './LandingActions'
import { LandingFooter, LandingHeader } from './LandingChrome'
import { LandingHero } from './LandingHero'
import { LandingSection, Wide } from './LandingSection'
import { MapTour } from './MapTour'
import { useScrolled } from './motion'
import { ProductPreview } from './ProductPreview'
import { Reveal } from './Reveal'
import { ShipBody } from './ShipSection'
import { ApprovalBody, AssistantBody, CostBody, DeadlineFigure, OptionsBody, SummaryBody } from './WorkSections'
import './landing.css'

interface Props {
  session: Session
  onLogin: () => void
  onEnter: () => void
}

const [PROBLEM_LEAD, PROBLEM_COUNT] = problemTitle(SHOWCASE)

export function LandingPage({ session, onLogin, onEnter }: Props) {
  const signedIn = session.state.status === 'signed-in'
  const [topRef, scrolled] = useScrolled()
  useLightOnly()

  const actions = (where: 'hero' | 'end') => (
    <LandingActions where={where} signedIn={signedIn} onEnter={onEnter} onLogin={onLogin} />
  )

  return (
    <div className="rp-landing min-h-dvh bg-surface text-foreground" data-testid="landing">
      {/* 이 표지가 화면 밖으로 나가면(조금이라도 내리면) 위 막대 아래에 선을 긋는다 */}
      <div ref={topRef} aria-hidden className="h-px" />
      <LandingHeader scrolled={scrolled} signedIn={signedIn} onEnter={onEnter} onLogin={onLogin} />

      <main>
        <LandingHero actions={actions('hero')} />

        <LandingSection
          id="problem"
          background="canvas"
          eyebrow="영향 검토"
          title={
            <>
              {PROBLEM_LEAD}
              <Wide /> {PROBLEM_COUNT}
            </>
          }
          lead={VALUE.problem}
        >
          <Reveal>
            <div id="demo" className="mx-auto max-w-[1440px] scroll-mt-24">
              <ProductPreview />
            </div>
          </Reveal>
        </LandingSection>

        <LandingSection
          id="ship3d"
          tag={{ label: '3D 배치', tone: 'primary' }}
          title={
            <>
              영향이 번진 블록을
              <Wide /> 선체 위에 그대로
            </>
          }
          lead={VALUE.ship3d}
        >
          <ShipBody />
        </LandingSection>

        <LandingSection
          id="map"
          background="canvas"
          tag={{ label: '2D 영향 지도', tone: 'primary' }}
          title={
            <>
              용접으로 이어진 이웃 블록과
              <Wide /> 진행 중인 발주까지
            </>
          }
          lead={VALUE.map}
        >
          <MapTour />
        </LandingSection>

        <LandingSection
          id="summary"
          layout="split"
          tag={{ label: '판단 요약', tone: 'primary' }}
          title={
            <>
              추가 공수와 추가 재료비를
              <Wide /> 판단 요약 첫 줄에
            </>
          }
        >
          <SummaryBody />
        </LandingSection>

        <LandingSection
          id="cost"
          background="canvas"
          tag={{ label: '비용 · 중량', tone: 'primary' }}
          title={
            <>
              공수와 재료비는 묶음별 소계로,
              <Wide /> 강재 중량은 블록별로
            </>
          }
        >
          <CostBody />
        </LandingSection>

        <LandingSection
          id="deadline"
          layout="split"
          background="surface"
          tag={{ label: '결정 기한', tone: 'warning' }}
          title={
            <>
              언제 확정하느냐에 따라
              <Wide /> 달라지는 금액을 날짜별로
            </>
          }
          lead={VALUE.deadline}
        >
          <DeadlineFigure />
        </LandingSection>

        <LandingSection
          id="options"
          background="canvas"
          layout="split"
          tag={{ label: '대안 비교', tone: 'primary' }}
          title={
            <>
              요청안보다 저렴한 방법을
              <Wide /> 먼저 비교합니다
            </>
          }
        >
          <OptionsBody />
        </LandingSection>

        <LandingSection
          id="approval"
          background="surface"
          tag={{ label: '결재·검토서', tone: 'success' }}
          title={
            <>
              결재선 그대로 올리고
              <Wide /> A4 검토서로 남깁니다
            </>
          }
          lead={VALUE.approval}
        >
          <ApprovalBody />
        </LandingSection>

        <LandingSection
          id="assistant"
          background="canvas"
          layout="split"
          tag={{ label: 'AI 비서', tone: 'agent' }}
          title={
            <>
              현장에서 쓰는 말 그대로,
              <Wide /> 설계변경을 접수합니다
            </>
          }
          lead={VALUE.assistant}
        >
          <AssistantBody />
        </LandingSection>

        <LandingSection
          id="trust"
          background="night"
          title={
            <>
              현장 자료는 사내에,
              <Wide /> 성능은 측정값으로
            </>
          }
        >
          <TrustBand />
          <div id="measured" className="rp-night-line mt-14 scroll-mt-24 border-t pt-14 lg:mt-16 lg:pt-16">
            <MeasuredList />
          </div>
        </LandingSection>

        <EndCall actions={actions('end')} />
      </main>

      <LandingFooter />
    </div>
  )
}
