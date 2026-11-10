// 엑셀 가져오기 첫 단계: 파일을 끌어 놓거나 고른다. 상태 올리기는 읽는 시트 안내, 가져오기는 양식 예시 내려받기.
import { FileSpreadsheet, FileUp } from 'lucide-react'
import { api } from '@/api/client'
import type { FilePick } from '@/components/common/useFilePick'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Props {
  status: boolean
  /** 기본 합성 지도 ID(양식 예시로 내려받는다). */
  defaultId: string | null
  file: FilePick
}

export function ChooseFile({ status, defaultId, file }: Props) {
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        file.setDragging(true)
      }}
      onDragLeave={() => file.setDragging(false)}
      onDrop={file.drop}
      className={cn(
        'flex flex-col items-center gap-2 rounded-md border border-dashed border-border-strong px-4 py-8 text-center',
        file.dragging && 'border-primary bg-primary/8',
      )}
    >
      <FileSpreadsheet aria-hidden className="size-6 text-foreground-secondary" />
      <p>엑셀 파일을 여기에 끌어 놓거나</p>
      <Button onClick={file.pick}>
        <FileUp aria-hidden />
        파일 고르기
      </Button>
      {status && (
        <p className="text-sm text-foreground-secondary">
          발주(발주번호 + 납기·확인된 날짜) · 발주 관측 · 공정(공정ID + 실적 날짜) · 공정 확인 시트만 읽음 · 빈 칸은
          그대로
        </p>
      )}
      {!status && defaultId && (
        <a href={api.exportUrl(defaultId)} download className="text-sm text-primary underline-offset-4 hover:underline">
          양식 예시 내려받기(기본 합성 지도를 양식으로)
        </a>
      )}
    </div>
  )
}
