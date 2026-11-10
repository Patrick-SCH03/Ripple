// WebGL을 쓸 수 있는 브라우저인가(3D 배치 보기 전환 전에 확인 — 안 되면 2D 유지). 한 번만 재고 기억한다.
let cached: boolean | null = null

export function hasWebGL(): boolean {
  if (cached !== null) return cached
  try {
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl')
    cached = context !== null
    // 잰 뒤 바로 놓아 준다(브라우저마다 동시에 쓸 수 있는 WebGL 수가 정해져 있다)
    ;(context as WebGLRenderingContext | null)?.getExtension('WEBGL_lose_context')?.loseContext()
  } catch {
    cached = false
  }
  return cached
}

/** 영향 지도 보기. 고른 보기는 RipplePanel의 lastView로만 유지한다(새로 고침이면 2D). */
export type MapView = '2d' | '3d'
