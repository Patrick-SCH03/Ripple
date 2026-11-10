# Ripple API

전체 스키마는 [`openapi.json`](openapi.json)에 있고, 화면의 API 타입은 이 파일에서 생성합니다(`npm --prefix web run gen:api`).

주요 경로는 분석 `POST /api/analyses`, 영향 `POST /api/impacts`, AI 비서 `POST /api/assistant/turns`, 기록·결재 `POST /api/records` · `POST /api/ecns/{id}/actions`, 결정 도우미 `GET /api/ecns/{id}/brief`입니다. 결재 계획(결재선·결재 올릴 기한)은 분석 응답·상세·기록 조회·결재함에 함께 실립니다.

## 권한

| 권한 | 누구 | 할 수 있는 일 |
|---|---|---|
| **로⁠그⁠인** | 담당자 · 파트장 · 팀장 · 본부장 · 체험 | 지도 보기 · 분석 · 영향 · 대안 · 비서 · 문서로 넣기 · 엑셀 내려받기(체험 계정은 켰을 때만 있고 합성 데이터만 봄) |
| **담⁠당⁠자** | 담당자 | 기록 · 검토 요청 · 무비용 담당자 처리 · 실행 · 종료 · 상태 갱신 · 실적 · 통보 기록 |
| **결⁠재⁠자** | 파트장 · 팀장 · 본부장 | 결재선의 자기 단계 승인 · 반려 · 보류(팀장은 파트장·본부장 단계 전결) · 결재·현황 · 결정 도우미 · 감사 확인 |
| **팀⁠장** | 팀장 | 구성원 관리 · 지도 전환 · 엑셀 가져오기 · AI 호출 기록 |

## 전체 경로

| 메서드 | 경로 | 권한 | 설명 |
|---|---|:---:|---|
| `GET` | `/api/health` | — | 버전·데이터 모드·지도 ID·빌드 커밋·로그인 설정 |
| `POST` | `/api/auth/login` · `/api/auth/logout` · `/api/auth/demo` · `/api/auth/quick` | — | 로그인 · 로그아웃 · 체험 로그인·빠른 로그인(켰을 때만) |
| `GET` · `POST` | `/api/auth/me` · `/api/auth/password` | 로그인 | 내 정보 · 비밀번호 바꾸기(체험 제외) |
| `GET` · `POST` · `PATCH` | `/api/accounts…` | 팀장 | 구성원 목록·추가·역할(담당자·파트장·팀장·본부장)·사용 여부·비밀번호 초기화(빠른 로그인 고정 계정은 잠김) |
| `DELETE` | `/api/accounts/{id}` | 팀장 | 구성원 삭제(그 계정 세션 끊음, 아이디는 다시 쓰지 않음, 내 계정·고정 계정·마지막 팀장은 거절) |
| `GET` | `/api/samples` | 로그인 | 샘플 설계변경과 기본 분석 요약 |
| `POST` | `/api/analyses` | 로그인 | 분석 → 비용 줄·일정·추가손실 곡선·결정 기한·대안·판정·연결 추적·사전 점검·결재 계획 |
| `POST` | `/api/analyses/export` | 로그인 | 같은 요청의 분석 결과 엑셀(요약·영향 목록·비용 근거·가정값·확정 시점 곡선·대안 비교, 체험은 합성 데이터만) |
| `POST` | `/api/analyses/notices` | 로그인 | 같은 요청의 알림 초안(공식 메일·작업반 번역 초안) — 상세 사전 점검의 '통보문 보기' |
| `POST` | `/api/impacts` | 로그인 | 영향·근거 경로·계산 불가 이유·영향 그래프 |
| `GET` | `/api/graph/view` | 로그인 | 중심 엔터티에서 깊이 0~4 부분 그래프 |
| `POST` · `GET` | `/api/assistant/turns` · `/api/assistant/conversations/{id}` | 로그인 | AI 비서 한 차례 · 대화 기록 |
| `GET` | `/api/snapshots` · `/api/snapshots/{id}/export` | 로그인 | 지도 목록 · 지정 양식 엑셀 내려받기 |
| `POST` · `DELETE` | `/api/snapshots/{id}/activate` · `/api/imports…` | 팀장 | 지도 전환 · 엑셀 가져오기 · 열 매핑 기억 지우기 |
| `POST` | `/api/updates/preview` · `/api/updates` · `/api/status-imports…` | 담당자 | 현장 상태 확인·수정·갱신 |
| `GET` | `/api/updates` | 결재자 | 상태 갱신 기록 |
| `POST` | `/api/records` | 담당자 | 분석을 기록(개정)으로 — 서버가 다시 계산해 대조 |
| `GET` | `/api/ecns` · `/api/ecns/{ecn_id}` · `/api/records/{record_id}` | 로그인 | 기록된 ECN 상태 · 개정·감사 줄·결재 계획 · 기록 본문 |
| `POST` | `/api/ecns/{ecn_id}/actions` | 담당자 · 결재자 | 검토 요청·무비용 담당자 처리·실행·종료(담당자) · 승인·반려·보류(지금 단계 결재자, 팀장 전결) · 검토 취소(요청자·팀장) |
| `POST` | `/api/ecns/{ecn_id}/notices` | 담당자 | 통보 기록(보냄·수령 확인·회신 받음) |
| `GET` | `/api/ecns/{ecn_id}/brief` | 결재자 | 결정 도우미 — 진행 중 검토의 세 줄 요약·확인할 것·비슷한 과거 사례 |
| `GET` | `/api/ncrs/summary` | 결재자 | 반복 유형 — 사전 점검 유형별 합성 NCR 건수(합성 모드만) |
| `POST` | `/api/intake/proposals` · `/api/intake/proposals/xlsx` · `/api/intake/confirmations` | 로그인 | 문서 → 확인표 제안 · 항목별 결정 → 재검증 → 분석 |
| `GET` | `/api/manage/overview?days=` | 결재자 | 결재·현황(자기 결재 단계 결재함·팀장의 전결 묶음·현황·성과·예측 대비 실적) |
| `GET` | `/api/manage/export?days=` | 결재자 | 결재 대장 엑셀(결재함 줄·결재선·승인한 단계·남은 결재 올릴 기한·현황·상태별·블록별) |
| `GET` · `PUT` | `/api/ecns/{id}/outcome` | 로그인 · 담당자 | 실행한 설계변경의 실적 |
| `GET` | `/api/audit/verify` · `/api/corrections/summary` | 결재자 | 감사 사슬 확인 · AI 제안 수정 기록 |
| `GET` | `/api/llm/calls` | 팀장 | 외부 AI 호출 기록 |
