// 업무 화면 목록 칸의 본문: 설계변경 목록이 없는 지도(엑셀로 가져온 지도)는 분석 기준과 결재 대기·기록된 설계변경을,
// 기본 지도는 설계변경 목록을 보인다.
import type { ComponentProps } from 'react'
import { MapBasisPanel } from '@/components/workspace/MapBasisPanel'
import { EcnList } from './EcnList'
import { PendingDecisions } from './PendingDecisions'
import { RecordedOthers } from './RecordedOthers'

/** 분석 기준 칸(지금 켜진 지도 · 분석 기준 · 바꾸기 · AI 비서 칸 열기). 좁은 화면 여부는 목록의 것을 쓴다. */
export type MapBasis = Omit<ComponentProps<typeof MapBasisPanel>, 'compact'>

interface Props {
  /** 설계변경 목록. 분석 기준을 보일 때도 결재 대기·기록된 설계변경은 이 값으로 그린다. */
  list: ComponentProps<typeof EcnList>
  /** 분석 기준(설계변경 목록이 없는 지도만). 있으면 목록 대신 기준과 기록된 설계변경을 보인다. */
  mapBasis: MapBasis | null
}

export function ListPaneBody({ list, mapBasis }: Props) {
  if (!mapBasis) return <EcnList {...list} />
  return (
    <>
      <MapBasisPanel {...mapBasis} compact={list.compact} />
      {list.approver && <PendingDecisions items={list.records} chosen={list.chosen} onOpen={list.onOpenRecord} />}
      <RecordedOthers items={list.records} chosen={list.chosen} onOpen={list.onOpenRecord} snapshotId={list.snapshotId} />
    </>
  )
}
