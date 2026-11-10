// 3D 밖(영향 목록·근거 패널·명령 팔레트)에서 고른 엔터티 → 3D 이동·강조 요청(대상 규칙은 focus.ts).
// 3D 안(블록·라벨·배치 밖 블록 단추)에서 고른 것은 pick으로 받아 카메라를 그대로 둔다 — 누른 블록이 이미 보이므로.
import { useEffect, useRef, useState } from 'react'
import type { ImpactView } from '@/api/client'
import { focusNotice, focusOf } from './focus'
import type { FlashRequest, FlyRequest } from './ShipScene'
import { FLASH_SECONDS } from './wave'

/** 강조 외곽선을 보이는 시간(ms) — 강조 맥동(FLASH_SECONDS)이 끝난 뒤 조금 더. */
const FLASH_MS = FLASH_SECONDS * 1000 + 600
/** 안내를 보이는 시간(ms). */
const NOTICE_MS = 2600
/** 3D를 연 직후(이 시간 안)에 이미 고른 엔터티로 옮길 때는 애니메이션 없이 바로. */
const SETTLE_MS = 500

export function useOutsidePick(report: ImpactView, selected: string | null, onSelect: (id: string | null) => void) {
  const [fly, setFly] = useState<FlyRequest | null>(null)
  const [flash, setFlash] = useState<FlashRequest | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  /** 3D 안에서 고른 엔터티(이 값으로 selected가 바뀌면 이동하지 않는다). */
  const local = useRef<string | null>(null)
  const seq = useRef(0)
  const [born] = useState(() => performance.now())

  /** 마지막으로 처리한 고른 엔터티(결과 객체만 새로 와도 다시 날아가지 않게 — 사용자가 돌려 둔 시점을 지킨다). */
  const handled = useRef<string | null>(null)

  useEffect(() => {
    if (selected === handled.current) return
    handled.current = selected
    if (!selected) {
      local.current = null
      return
    }
    if (local.current === selected) {
      local.current = null
      return
    }
    local.current = null
    const target = focusOf(report, selected)
    seq.current += 1
    setNotice(focusNotice(target))
    if (target.kind === 'block') setFly({ code: target.code, seq: seq.current, animate: performance.now() - born > SETTLE_MS })
    setFlash(target.kind === 'none' ? null : { codes: target.kind === 'block' ? [target.code] : target.codes, seq: seq.current })
  }, [selected, report, born])

  useEffect(() => {
    if (!flash) return
    const timer = window.setTimeout(() => setFlash(null), FLASH_MS)
    return () => window.clearTimeout(timer)
  }, [flash])
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), NOTICE_MS)
    return () => window.clearTimeout(timer)
  }, [notice])

  const pick = (id: string) => {
    // 이미 고른 엔터티를 다시 누르면 selected가 그대로라 표시를 남기지 않는다(다음 바깥 고르기를 막지 않게)
    local.current = id === selected ? null : id
    setNotice(null)
    onSelect(id)
  }
  return { fly, flash, notice, pick }
}
