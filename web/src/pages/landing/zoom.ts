// 고정 화면 확대 계산(영향 지도 둘러보기): 넓은 그림을 상자(가로세로 비율 고정)에 맞춰 넣고(contain), 강조 자리가 상자
// 가운데에 오도록 확대·이동한다. 값은 모두 상자 크기 비율이라 폭이 바뀌어도 같은 모양이다. 상자 밖으로는 밀지 않는다
// (그림 바탕이 흰색이라 위아래 여백도 화면의 일부처럼 보인다).
import type { Rect } from './captures'

export interface Fraction {
  left: number
  top: number
  width: number
  height: number
}

export interface View {
  /** 상자 안 그림 자리(상자 비율 0~1). */
  image: Fraction
  /** 강조 자리(상자 비율), 전체 보기면 null. */
  focus: Fraction | null
  /** 확대 배율(1 = 전체). */
  scale: number
  /** 확대 뒤 이동(상자 비율, 왼쪽 위 기준 변환: 점 p → scale·p + (x, y)). */
  x: number
  y: number
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

/**
 * size = 그림 크기, box = 상자 가로/세로 비율, focus = 그림 안 강조 자리(없으면 전체).
 * fill = 강조 자리가 상자에서 차지할 몫, maxZoom = 확대 상한(2배 그림이 흐려지지 않을 만큼).
 */
export function focusView(
  size: { width: number; height: number },
  box: number,
  focus: Rect | null,
  { fill = 0.78, maxZoom = 3.2 }: { fill?: number; maxZoom?: number } = {},
): View {
  const ratio = size.width / size.height
  const image: Fraction =
    ratio >= box
      ? { left: 0, top: (1 - box / ratio) / 2, width: 1, height: box / ratio }
      : { left: (1 - ratio / box) / 2, top: 0, width: ratio / box, height: 1 }
  if (!focus) return { image, focus: null, scale: 1, x: 0, y: 0 }
  const area: Fraction = {
    left: image.left + (focus.x / size.width) * image.width,
    top: image.top + (focus.y / size.height) * image.height,
    width: (focus.w / size.width) * image.width,
    height: (focus.h / size.height) * image.height,
  }
  const scale = clamp(Math.min(fill / area.width, fill / area.height), 1, maxZoom)
  const x = clamp(0.5 - scale * (area.left + area.width / 2), 1 - scale, 0)
  const y = clamp(0.5 - scale * (area.top + area.height / 2), 1 - scale, 0)
  return { image, focus: area, scale, x, y }
}
