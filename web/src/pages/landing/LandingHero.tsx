// 소개 화면 첫 화면: 대상·역할 한 줄 · 두 줄 제목(설계변경, 확정하기 전에 → 영향 범위부터 확인하세요) · 가치 한 줄 · 단추 짝 ·
// 흐름 장면(HeroScene — 흐름 띠 + 스크롤에 따라 단계가 바뀌는 실제 3D 배치 판).
import type { ReactNode } from 'react'
import { HERO } from './content'
import { HeroScene } from './HeroScene'
import { FULL, WIDTH } from './layout'
import { Rise } from './Reveal'

export function LandingHero({ actions }: { actions: ReactNode }) {
  return (
    <section aria-labelledby="hero-title" className="pt-12 pb-20 sm:pt-16 lg:pt-24 lg:pb-28">
      <div className={WIDTH}>
        <div className="mx-auto flex max-w-[1080px] flex-col items-center text-center">
          <Rise>
            <p className="text-md font-semibold text-primary lg:text-lg">{HERO.eyebrow}</p>
          </Rise>
          <Rise delay={80}>
            <h1 id="hero-title" className="mt-5 font-bold tracking-tight text-balance">
              <span className="block text-subhead text-foreground-secondary md:text-title-sm lg:text-title-md xl:text-title">
                {HERO.title[0]}
              </span>
              <span className="mt-2 block text-display-sm md:text-display-md lg:text-display xl:text-hero">{HERO.title[1]}</span>
            </h1>
          </Rise>
          <Rise delay={160}>
            <p className="mx-auto mt-7 max-w-[720px] text-lead text-balance text-foreground-secondary lg:text-lead-lg">{HERO.lead}</p>
          </Rise>
          <Rise delay={240} className="mt-9 w-full sm:w-auto">
            {actions}
          </Rise>
        </div>
      </div>
      {/* 흐름 장면은 화면 폭을 거의 다 쓴다(좌우 여백만) */}
      <div className={FULL}>
        <HeroScene />
      </div>
    </section>
  )
}
