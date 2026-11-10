// 여러 곳이 같은 요소를 가리키는 DOM id: 화면(위 막대·비서 칸)과 초점 이동(useAssistantDock)·시연 시나리오(demoScenarios)가
// 같은 값을 쓰도록 한 곳에 둔다(값을 바꾸면 모두 따라간다).

/** AI 비서 입력창. 칸을 열면 여기로 초점. */
export const ASSISTANT_INPUT_ID = 'assistant-input'
/** 위 막대 'AI 비서' 단추: 넓은 화면에서 칸을 닫으면 초점을 여기로 돌려준다. */
export const ASSISTANT_TOGGLE_ID = 'assistant-toggle'
/** 상세 근거 탭 줄(비용 · 일정 · 추가손실 곡선 …): 마감일 카드의 작은 곡선을 누르면 여기로 내려 곡선 탭을 연다. */
export const DETAIL_TABS_ID = 'detail-tabs'
