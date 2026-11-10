// API 호출 입구: 영역별 요청 파일을 api 하나로 묶고, 요청 규칙(http.ts: 오류·작업 공간 토큰·인증 세대)과
// 계약 타입(types.ts, docs/api/openapi.json에서 생성한 schema.d.ts)을 다시 내보낸다. 화면은 이 경로에서 import한다.
import { accountApi } from './account'
import { analysisApi } from './analysis'
import { assistantApi } from './assistant'
import { importsApi } from './imports'
import { intakeApi } from './intake'
import { manageApi } from './manage'
import { recordsApi } from './records'
import { workspaceApi } from './workspace'

export type * from './types'
export {
  ApiError,
  type Download,
  IMPORT_CHANGED,
  SESSION_CHANGED,
  WORKSPACE_CHANGED,
  WORKSPACE_HEADER,
  bumpAuthGeneration,
  currentAuthGeneration,
  expectedWorkspace,
  onUnauthorized,
  onWorkspaceChanged,
  setExpectedWorkspace,
  switchSession,
} from './http'

export const api = {
  ...accountApi,
  ...workspaceApi,
  ...importsApi,
  ...analysisApi,
  ...assistantApi,
  ...recordsApi,
  ...intakeApi,
  ...manageApi,
}
