import { Braces, FileText, PanelRightClose } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  onIntake: () => void
  /** 비서 맥락이 있어 문서로 넣을 수 있나. */
  intakeReady: boolean
  /** 새 대화(대화 기록이 있을 때만). */
  onReset: (() => void) | null
  /** 요청 JSON 고치기(개발 모드에서만). */
  onJson: (() => void) | null
  /** 칸 닫기(넓은 화면에서만). */
  onClose: (() => void) | null
}

/** AI 비서 칸 머리의 단추들: 문서로 넣기 · 새 대화 · 요청 JSON(개발용) · 칸 닫기. */
export function AsideActions({ onIntake, intakeReady, onReset, onJson, onClose }: Props) {
  return (
    <>
      <Button variant="ghost" size="sm" onClick={onIntake} disabled={!intakeReady} data-testid="intake-open">
        <FileText aria-hidden />
        문서로 넣기
      </Button>
      {onReset && (
        <Button variant="ghost" size="sm" onClick={onReset}>
          새 대화
        </Button>
      )}
      {onJson && (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="요청 JSON 고치기(개발용)"
          title="요청 JSON 고치기(개발용)"
          onClick={onJson}
        >
          <Braces aria-hidden />
        </Button>
      )}
      {onClose && (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="AI 비서 닫기"
          title="AI 비서 닫기"
          onClick={onClose}
          data-testid="assistant-close"
        >
          <PanelRightClose aria-hidden />
        </Button>
      )}
    </>
  )
}
