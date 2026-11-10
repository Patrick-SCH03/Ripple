// 좁은 폭에서 넓은 표(결재·현황 성과 탭): 표를 가로 스크롤 칸에 담고, 표가 칸보다 넓을 때만 위에 안내 한 줄을 둔다
// — 375 폭에서 머리글이 칸 끝에 걸려 잘린 글자('반')로만 보이고 뒤 칸이 있는 줄 모르는 일이 없게. 칸은 키보드로도 민다
// (초점을 받는 영역 + 이름). 머리글은 부르는 쪽이 줄을 바꾸지 않게 둔다(whitespace-nowrap).
import { useEffect, useRef, useState, type ReactNode } from 'react'

interface Props {
  /** 스크롤 영역 이름(화면 낭독기): '담당자별 업무량 표'. */
  label: string
  children: ReactNode
}

export function WideTable({ label, children }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [overflowing, setOverflowing] = useState(false)

  useEffect(() => {
    const element = box.current
    if (!element) return
    const measure = () => setOverflowing(element.scrollWidth > element.clientWidth + 1)
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    if (element.firstElementChild) observer.observe(element.firstElementChild)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="mt-3">
      {overflowing && (
        <p className="mb-1 text-xs text-foreground-secondary print:hidden" data-testid="scroll-hint">
          옆으로 스크롤 · 나머지 열 →
        </p>
      )}
      {/* 넘칠 때 키보드로 밀 수 있게 초점을 받는 영역(초점 테두리는 index.css의 [tabindex] 공통 규칙) */}
      <div ref={box} role="region" aria-label={label} tabIndex={0} className="overflow-x-auto" data-testid="wide-table">
        {children}
      </div>
    </div>
  )
}
