// 업무 절 본문(DESIGN.md 12절): 판단 요약 · 결정 기한 · 대안 비교 · 결재·검토서 · AI 비서. 홍보 페이지라 설명 문단 없이 실제 업무
// 화면 그림을 크게 두고, 볼 곳은 테두리로만 짚는다(번호 배지·줄표 설명 없음). 그림 판 머리는 '어느 화면 · 어느 칸'.
import {
  APPROVAL_MARKS,
  APPROVAL_SHOT,
  ASSISTANT_SHOT,
  COST_MARKS,
  COST_SHOT,
  CURVE_MARKS,
  CURVE_SHOT,
  DEADLINE_CARD_SHOT,
  OPTIONS_MARKS,
  OPTIONS_SHOT,
  REPORT_MARKS,
  REPORT_SHOT,
  REPORT_SIGN_SHOT,
  SUMMARY_MARKS,
  SUMMARY_SHOT,
  WEIGHT_SHOT,
} from './captures'
import { APPROVAL_CHIPS, type Chip, type Tone } from './content'
import { Reveal } from './Reveal'
import { Shot, ShotImage } from './Shot'
import { TONE_TEXT, TONE_TINT } from './tone'

/** 그림 아래 이름표 줄(아이콘 + 2~3단어). */
export function ChipRow({ chips, tone }: { chips: Chip[]; tone: Tone }) {
  return (
    <ul className="mt-10 flex flex-wrap justify-center gap-3 lg:mt-12">
      {chips.map((chip, i) => (
        <Reveal as="li" key={chip.text} delay={i * 60} className="rp-card flex items-center gap-2.5 rounded-full bg-surface py-2 pr-5 pl-2">
          <span className={`flex size-9 items-center justify-center rounded-full ${TONE_TINT[tone]}`}>
            <chip.icon aria-hidden className={`size-[18px] ${TONE_TEXT[tone]}`} />
          </span>
          <span className="text-md font-semibold">{chip.text}</span>
        </Reveal>
      ))}
    </ul>
  )
}

/** 판단 요약 절(가로 분할의 오른쪽): 상세 위쪽 그림. */
export function SummaryBody() {
  return (
    <Reveal>
      <Shot
        shot={SUMMARY_SHOT}
        title="설계변경 상세 · 판단 요약"
        sizes="(min-width: 1024px) 62vw, calc(100vw - 32px)"
        marks={[{ rect: SUMMARY_MARKS.keys }, { rect: SUMMARY_MARKS.timing }]}
      />
    </Reveal>
  )
}

/** 비용·중량 절: 비용 탭(공수 · 재료비 묶음)과 블록별 강재 중량 변화를 찍은 크기 그대로 나란히. */
export function CostBody() {
  return (
    <div className="mx-auto grid max-w-[1400px] items-start gap-6 lg:grid-cols-[minmax(0,605fr)_minmax(0,633fr)] lg:gap-10">
      <Reveal>
        <Shot
          shot={COST_SHOT}
          title="비용 탭 · 공수 · 재료비"
          sizes="(min-width: 1024px) 640px, calc(100vw - 32px)"
          marks={[{ rect: COST_MARKS.labor }, { rect: COST_MARKS.material }]}
        />
      </Reveal>
      <Reveal delay={100}>
        <Shot shot={WEIGHT_SHOT} title="블록별 강재 중량 변화" sizes="(min-width: 1024px) 660px, calc(100vw - 32px)" />
      </Reveal>
    </div>
  )
}

export function DeadlineFigure() {
  return (
    <Reveal>
      <div className="relative lg:pr-24">
        <Shot
          shot={CURVE_SHOT}
          title="추가손실 곡선"
          sizes="(min-width: 1024px) 56vw, calc(100vw - 32px)"
          marks={[{ rect: CURVE_MARKS.deadline }, { rect: CURVE_MARKS.stepRow }]}
        />
        {/* 판단 요약의 결정 기한 카드: 넓은 화면에서 곡선 판 오른쪽 위에 겹쳐 띄운다 */}
        <div className="mx-auto mt-5 max-w-[520px] lg:absolute lg:-top-24 lg:right-0 lg:mt-0 lg:w-[400px]">
          <div className="rp-float overflow-hidden rounded-[14px] border border-border bg-surface">
            <ShotImage shot={DEADLINE_CARD_SHOT} sizes="(min-width: 1024px) 400px, 520px" />
          </div>
        </div>
      </div>
    </Reveal>
  )
}

export function OptionsBody() {
  return (
    <Reveal>
      <Shot
        shot={OPTIONS_SHOT}
        title="대안 비교"
        sizes="(min-width: 1024px) 62vw, calc(100vw - 32px)"
        marks={[{ rect: OPTIONS_MARKS.best }]}
      />
    </Reveal>
  )
}

/** 결재·검토서 절: 팀장 결재함 → A4 검토서와 결재란 + 이름표. */
export function ApprovalBody() {
  return (
    <>
      <Reveal className="mx-auto max-w-[1200px]">
        <Shot
          shot={APPROVAL_SHOT}
          title="결재함 · 결재선 팀장 단계"
          sizes="(min-width: 1240px) 1200px, calc(100vw - 32px)"
          marks={[{ rect: APPROVAL_MARKS.due }, { rect: APPROVAL_MARKS.later }, { rect: APPROVAL_MARKS.line }]}
        />
      </Reveal>
      <Reveal className="relative mx-auto mt-12 max-w-[640px] pb-16 sm:pb-24 lg:mt-16">
        <Shot
          shot={REPORT_SHOT}
          title="설계변경 검토서 · A4"
          sizes="(min-width: 700px) 640px, calc(100vw - 32px)"
          marks={[{ rect: REPORT_MARKS.numbers }]}
        />
        {/* 같은 검토서의 결재란: 문서 아래쪽에 겹쳐 띄운다 */}
        <div className="absolute right-[-4%] bottom-0 left-[14%]">
          <div className="rp-float overflow-hidden rounded-[14px] border border-border bg-surface p-2 sm:p-3">
            <ShotImage shot={REPORT_SIGN_SHOT} sizes="(min-width: 700px) 560px, 86vw" />
          </div>
        </div>
      </Reveal>
      <ChipRow chips={APPROVAL_CHIPS} tone="success" />
    </>
  )
}

export function AssistantBody() {
  return (
    <Reveal className="mx-auto w-full max-w-[400px]">
      <Shot shot={ASSISTANT_SHOT} frame="none" sizes="400px" className="rp-card overflow-hidden rounded-[18px] border border-border" />
    </Reveal>
  )
}
