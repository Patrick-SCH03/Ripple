// 3D 배치 카메라 조작(camera-controls): 시점 단추·전체 화면 전환에 맞추고, 영향 목록·근거에서 엔터티를 고르면 그 블록으로
// 날아가 맞춘다(움직임 줄이기면 애니메이션 없이 바로). 사용자가 직접 돌리거나 옮겼으면 칸 크기가 바뀌어도 시점을 그대로 둔다.
import { CameraControls, type CameraControlsImpl } from '@react-three/drei'
import { useThree } from '@react-three/fiber'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { PerspectiveCamera } from 'three'
import { blockView, fitView, zoomLimits } from './camera'
import { blockShapes } from './geometry'
import { VIEWS, type ViewName } from './layout'
import { useReducedMotion } from './useTokens'

export interface ViewRequest {
  name: ViewName
  /** 단추를 누를 때마다 늘어남(같은 시점을 다시 눌러도 다시 맞춘다). 0 = 처음 그리기(애니메이션 없음). */
  seq: number
  /** 좌현 쪽에서 보기(방위를 x축에 대해 뒤집음 — blocks.ts portSide). */
  mirror: boolean
}

/** 블록으로 날아가기(목록·근거에서 고를 때마다 seq가 늘어남). */
export interface FlyRequest {
  code: string
  seq: number
  /** false면 바로 옮긴다(3D를 막 열었을 때 이미 고른 엔터티가 있으면). */
  animate: boolean
}

export function ShipControls({ view, full, fly }: { view: ViewRequest; full: boolean; fly: FlyRequest | null }) {
  const ref = useRef<CameraControlsImpl>(null)
  const camera = useThree((state) => state.camera) as PerspectiveCamera
  const get = useThree((state) => state.get)
  const width = useThree((state) => state.size.width)
  const height = useThree((state) => state.size.height)
  const reduced = useReducedMotion()
  const limits = useMemo(() => zoomLimits(camera.fov, width > 0 && height > 0 ? width / height : 1.6), [camera.fov, width, height])
  // 사용자가 직접 돌리거나 옮겼나(그랬으면 칸 크기가 바뀌어도 시점을 그대로 둔다 — 2D 지도와 같다)
  const moved = useRef(false)
  // 칸 크기가 아직 0이라 못 옮긴 날아가기(크기가 잡히면 이어서)
  const pending = useRef<FlyRequest | null>(null)

  const fit = useCallback(
    (animate: boolean) => {
      const controls = ref.current
      const target = VIEWS.find((v) => v.name === view.name)
      const { size } = get()
      if (!controls || !target || size.width <= 0 || size.height <= 0) return
      const facing = view.mirror ? { ...target, azimuth: Math.PI - target.azimuth } : target
      const { position, target: at } = fitView(facing, camera.fov, size.width / size.height)
      void controls.zoomTo(1, animate)
      void controls.setLookAt(...position, ...at, animate)
    },
    [view, camera, get],
  )

  /** 블록 하나에 맞춘다. 끝났으면(옮겼거나 옮길 수 없는 블록) true. */
  const flyTo = useCallback(
    (request: FlyRequest) => {
      const controls = ref.current
      const { size } = get()
      if (!controls || size.width <= 0 || size.height <= 0) return false
      const box = blockShapes().get(request.code)?.geometry.boundingBox
      const facing = box && blockView(request.code, [box.min.toArray(), box.max.toArray()], view.mirror)
      if (!facing) return true
      const { position, target } = fitView(facing, camera.fov, size.width / size.height)
      const animate = request.animate && !reduced
      void controls.zoomTo(1, animate)
      void controls.setLookAt(...position, ...target, animate)
      moved.current = true
      return true
    },
    [get, camera, view.mirror, reduced],
  )

  // 시점 단추·전체 화면 전환: 다시 맞춘다(단추로 고른 시점은 부드럽게, 움직임 줄이기면 바로)
  useEffect(() => {
    moved.current = false
    pending.current = null
    fit(view.seq > 0 && !reduced)
  }, [fit, view.seq, full, reduced])

  // 칸 크기가 바뀌면(경계 끌기·화면 회전) 직접 옮기지 않았을 때만 다시 맞춘다. 못 한 날아가기가 있으면 이어서
  useEffect(() => {
    if (pending.current) {
      if (flyTo(pending.current)) pending.current = null
    } else if (!moved.current) fit(false)
  }, [fit, flyTo, width, height])

  // 목록·근거에서 고른 블록으로(시점 맞춤 뒤에 — 같은 그리기에서 둘 다 오면 날아가기가 이긴다). 같은 요청(seq)은 한 번만 —
  // 움직임 줄이기·좌우 시점이 바뀌어도 다시 날아가지 않게
  const done = useRef(-1)
  useEffect(() => {
    if (!fly || done.current === fly.seq) return
    done.current = fly.seq
    pending.current = flyTo(fly) ? null : fly
  }, [fly, flyTo])

  return (
    <CameraControls
      ref={ref}
      makeDefault
      smoothTime={reduced ? 0 : 0.45}
      draggingSmoothTime={reduced ? 0 : 0.12}
      // 휠은 커서 쪽으로 확대·축소(dollyToCursor). 거리는 블록 하나 ~ 전체 시점 × 1.6(camera.ts zoomLimits), '시점 초기화'는 처음 거리로
      minDistance={limits.min}
      maxDistance={limits.max}
      minZoom={0.5}
      maxZoom={6}
      maxPolarAngle={Math.PI * 0.62}
      dollyToCursor
      onStart={() => {
        moved.current = true
        pending.current = null
      }}
    />
  )
}
