// 소개 화면 단추 짝(첫 화면 · 마지막 판): 주 단추 '시작하기'(로그인 화면, 로그인했으면 '업무 화면으로') + 보조 단추
// '영향 지도 보기'(아래 영향 지도 절로). 마지막 판은 파란 바탕이라 흰 단추(rp-cta-solid · rp-cta-soft, landing.css)로 칠한다.
import { ArrowDown, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CTA } from './content'
import { BIG_BUTTON } from './layout'

interface Props {
  where: 'hero' | 'end'
  signedIn: boolean
  onEnter: () => void
  onLogin: () => void
}

export function LandingActions({ where, signedIn, onEnter, onLogin }: Props) {
  const end = where === 'end'
  return (
    <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:flex-wrap sm:items-center sm:justify-center">
      <Button
        size="lg"
        className={end ? `${BIG_BUTTON} rp-cta-solid` : BIG_BUTTON}
        onClick={signedIn ? onEnter : onLogin}
        data-testid={`${where}-${signedIn ? 'enter' : 'start'}`}
      >
        {signedIn ? CTA.enter : CTA.start}
        <ArrowRight aria-hidden />
      </Button>
      <Button asChild size="lg" variant="secondary" className={end ? `${BIG_BUTTON} rp-cta-soft` : BIG_BUTTON}>
        <a href="#map" data-testid={`${where}-map`}>
          {CTA.map}
          <ArrowDown aria-hidden />
        </a>
      </Button>
    </div>
  )
}
