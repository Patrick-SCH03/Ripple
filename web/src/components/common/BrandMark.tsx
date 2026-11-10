// 서비스 마크(DESIGN.md 12절, 확정한 로고): 파란 R과 그 아래로 번지는 물결 고리.
// 그림 파일(public/brand/ripple-mark.png, 투명 배경)을 높이 size로 그린다 — 가로는 비율대로(약 1.29배).
// 파비콘(public/favicon.png)·홈 화면 아이콘(public/apple-touch-icon.png)은 같은 그림을 정사각에 넣은 것.
const MARK_SRC = '/brand/ripple-mark.png'
/** 그림 가로 ÷ 세로(여백을 잘라 낸 원본 1114×867). */
const MARK_ASPECT = 1114 / 867

export function BrandMark({ size, className, title }: { size: number; className?: string; title?: string }) {
  return (
    <img
      src={MARK_SRC}
      width={Math.round(size * MARK_ASPECT)}
      height={size}
      className={className}
      alt={title ?? ''}
      aria-hidden={title ? undefined : true}
      draggable={false}
      decoding="async"
    />
  )
}
