// 엑셀 파일 고르기·끌어 놓기(엑셀 가져오기 · 문서로 넣기 공통): 숨은 파일 입력 · 끌어 놓는 중 표시 · 고른 파일 넘기기.
import { useRef, useState, type ChangeEvent, type DragEvent, type RefObject } from 'react'

export interface FilePick {
  /** 숨은 파일 입력(type=file)에 붙인다. */
  input: RefObject<HTMLInputElement | null>
  /** 파일을 끌어 올리는 중인가(점선 상자를 강조). */
  dragging: boolean
  setDragging: (dragging: boolean) => void
  /** 점선 상자에 놓은 첫 파일을 넘긴다. */
  drop: (event: DragEvent<HTMLDivElement>) => void
  /** 파일 고르기 창을 연다(같은 파일을 다시 골라도 바뀜으로 잡히게 값을 비운다). */
  pick: () => void
  /** 숨은 파일 입력의 onChange: 고른 첫 파일을 넘긴다. */
  change: (event: ChangeEvent<HTMLInputElement>) => void
}

/** onFile = 고르거나 놓은 파일을 받는 쪽(부를 때의 최신 함수). */
export function useFilePick(onFile: (file: File) => void): FilePick {
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const pick = () => {
    if (input.current) {
      input.current.value = ''
      input.current.click()
    }
  }
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) onFile(file)
  }
  const change = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) onFile(file)
  }
  return { input, dragging, setDragging, drop, pick, change }
}
