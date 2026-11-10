# 개발 컨벤션

5인 팀 Ripple의 저장소입니다. 구현은 팀장이 맡고, 팀원은 현장 VOC 수집과 발표를 맡습니다. 변경 이력이 그 자체로 문서가 되도록 규칙을 정해 지킵니다.

## 코드 구조

레이어와 의존 방향은 한쪽으로만 흐릅니다. 안쪽 레이어는 바깥을 모릅니다(`tests/checks/layers.py`가 검사).

```
contracts ← engine · decide · nl · explain · records · intake(순수 계산, I/O 없음) ← config · graph · llm · ingest · store · auth(어댑터) ← agent · brief · cases ← api
```

| 패키지 | 책임 |
|---|---|
| `ripple/contracts` | Pydantic 계약(도메인·변경·분석·결과·설명·판단·규칙표·파라미터). 다른 레이어를 모름 |
| `ripple/engine` | 영향 전파·상태·비용·일정·확정 시점·대안·사전 점검. 순수 계산 |
| `ripple/decide` | 판단 계층: 온도 보정·되묻지 않는 문턱·되묻기 집합·점수기·경로. 순수 계산 |
| `ripple/nl` · `explain` | 규칙 기반 자연어 해석(값 정규화·참조·후보), 설명·알림 렌더러(글 템플릿 + 수치 블록). 순수 계산 |
| `ripple/config` | 환경 변수 설정, YAML 로더(파일 I/O는 여기서만) |
| `ripple/records` | 결재 상태 기계·결재선·결재 소요(결재 올릴 기한)·감사 사슬. 순수 계산 |
| `ripple/graph` · `llm` · `ingest` · `store` · `auth` | Neo4j·메모리 그래프, 외부 모델 Claude(실데이터 모드 차단), 엑셀 가져오기, 지도·계정·기록 저장소(파일·SQLite), 로그인·세션 |
| `ripple/generator` · `eval` | 합성 지도·문장 생성기와 숨긴 실제 비용 모델(엔진을 보지 않음), 평가 도구 |
| `ripple/intake` | 문서 접수: 분할·항목·확정 검증. 순수 계산 |
| `ripple/brief` · `cases` | 결정 도우미(세 줄 요약·서명 전 확인할 것), 비슷한 과거 사례·합성 NCR 묶음 |
| `ripple/agent` · `api` | AI 비서 대화 흐름(상태 기계), FastAPI |

- 모듈 하나는 책임 하나. 외부 서비스는 인터페이스 뒤에 두고 가짜 구현으로 테스트합니다.
- 숫자 상수는 코드 대신 `params/`·`rules/` YAML에 둡니다.
- 타입 힌트는 전부 쓰고 mypy strict를 통과해야 합니다.

## 계약을 바꿀 때

1. `ripple/contracts/base.py`의 `CONTRACT_VERSION`을 올립니다.
2. `docs/domain.md`를 함께 고칩니다.
3. API에 보이는 계약이면 `uv run python scripts/export_openapi.py`로 `docs/api/openapi.json`을 다시 만듭니다. 화면 타입은 이 파일에서 생성합니다.

## 화면을 바꿀 때

1. 루트의 `DESIGN.md`(디자인 규칙·토큰)를 먼저 읽고, 정의된 토큰과 규칙만 씁니다.
2. 첫 화면에는 결정에 필요한 것만 둡니다. 규칙 ID·해시·판단 확률은 펼침 안에 둡니다.
3. 업무 화면(로그인 뒤) 문구는 명사형·개조식, 소개·로그인·첫 비밀번호 화면과 밖으로 보내는 메일·알림 초안 본문은 합니다체로 씁니다. 대화상자 왼쪽 버튼은 '닫기'입니다(`DESIGN.md` 8절).
4. 바꾼 뒤 브라우저에서 1440 · 1024 · 768 · 375px, 밝게 · 어둡게로 업무 흐름을 눌러 보고 `DESIGN.md` 11절 확인 목록을 채웁니다.

## 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/) 형식을 따릅니다. 제목은 **한국어 명사형**('추가', '수정', '제거', '개편')으로 끝내고, 50자 이내, 마침표 없이 씁니다.

```
<type>(<scope>): <무엇을 왜 바꿨는지 한 줄>

<본문 — 무엇을·왜. 개조식 불릿. 버그 수정은 증상 → 원인 → 조치 순>
```

| type | 용도 | 예시 |
|---|---|---|
| `feat` | 새 기능 | `feat(engine): 발주 단계 추정 함수 추가` |
| `fix` | 버그 수정 | `fix(decide): 집합 보정 표본 필터 수정` |
| `refactor` | 동작 변화 없는 구조 개선 | `refactor(api): 의존성 주입 분리` |
| `perf` | 성능·비용 개선 | `perf(engine): 전파 탐색 캐시 추가` |
| `docs` | 문서 | `docs(plan): 단계별 관문 보강` |
| `test` | 테스트 추가·수정 | `test(contracts): 발주 관측 반례 추가` |
| `chore` | 설정·의존성 | `chore: uv.lock 갱신` |
| `ci` | CI 설정 | `ci: 타입 검사 단계 추가` |

기능·수정·문서를 한 커밋에 섞지 않습니다. 커밋 메시지·PR 본문에 AI 도구 서명 줄을 넣지 않습니다.

## 브랜치

- `main` — 개발 기준 브랜치. 검사를 통과한 커밋만 push합니다.
- `release` — 라이브 배포 브랜치. 고칠 것을 모아 한 번에 옮깁니다.
- 같은 트리를 두 작업이 동시에 고치지 않습니다. 파일 3개 이상을 바꾼 push 전에는 교차 리뷰를 한 번 거칩니다.

## CI

`.github/workflows/ci.yml` — `main`·`release` push와 PR마다 실행됩니다.

| 단계 | 내용 |
|---|---|
| 의존성 | `uv sync --locked`(uv.lock 그대로) |
| 린트·포맷 | `ruff check`, `ruff format --check` |
| 타입 검사 | `mypy`(strict, pydantic 플러그인) |
| 성질 검사 | `tests/check_all.py` — 서버·API 키 없이 |
| 관문 회귀 | `scripts/gate_cases.py score --stage 1·2·3` — 손 계산 정답(영향 30건·비용·일정 13건·대안 5건)과 엔진이 같은지 |
| 화면 | `npm ci`, API 타입이 `docs/api/openapi.json`과 같은지, oxlint·`tsc`, vitest, 빌드 |
| 배포 이미지 | API·화면 이미지 빌드, 컨테이너 스모크(화면·로그인·권한·볼륨·다시 만들기) |

테스트는 **서버·API 키 없이 동작**하므로 CI에 시크릿이 필요 없습니다.

## 라이선스·데이터 제약

- 이 저장소의 코드는 [MIT 라이선스](LICENSE)입니다.
- Neo4j Community(GPLv3)는 별도 컨테이너로만 쓰고 서버 플러그인을 넣지 않습니다.
- AGPL 라이브러리(PyMuPDF·borb), ApexCharts·Highcharts, elkjs(EPL), 라이선스가 없는 코드는 쓰지 않습니다.
- 선급 규칙(KR·IACS·BV) 원문은 싣지 않고 식의 형태와 조항 번호만 인용합니다.
- AI Hub 데이터는 이용정책상 학습용으로만 쓰고 원본을 저장소·외부 API에 넣지 않습니다. 실데이터(real) 모드는 외부 AI 호출을 막습니다.
