// 숨은 엑셀 파일 입력(useFilePick과 짝): 화면에는 보이지 않고, '파일 고르기' 단추가 이 입력을 눌러 고르기 창을 연다.
import type { FilePick } from './useFilePick'

const XLSX = '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export function FileInput({ file, label, testId }: { file: FilePick; label: string; testId?: string }) {
  const { input, change } = file
  return (
    <input
      ref={input}
      type="file"
      accept={XLSX}
      className="sr-only"
      tabIndex={-1}
      aria-label={label}
      data-testid={testId}
      onChange={change}
    />
  )
}
