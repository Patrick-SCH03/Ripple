# Ripple 화면(web)

설계변경(ECN) 영향 판단 업무 화면입니다. Vite + React 19 + TypeScript, 스타일은 Tailwind v4 + shadcn/ui(Radix), 파급 그래프는 React Flow(@xyflow/react) + dagre입니다. 디자인 규칙은 루트의 `DESIGN.md`를 따릅니다.

| 명령 | 하는 일 |
|---|---|
| `npm run dev` | 개발 서버(5173). `/api`는 로컬 API(8010, `RIPPLE_API_URL`로 변경)로 넘깁니다 |
| `npm run gen:api` | `docs/api/openapi.json`에서 API 타입(`src/api/schema.d.ts`)을 다시 만듭니다 |
| `npm test` | vitest: 화면 계산(`src/lib`의 표기·정렬·D-n·결재선·파급 묶음·배치 모드 등)과 `*.dom.test.tsx`의 부품 동작(jsdom) 검사 |
| `npm run lint` · `npm run typecheck` | oxlint · TypeScript 검사 |
| `npm run build` | 배포용 정적 파일(`dist/`). 그래프는 넓은 화면에서 처음 그릴 때 따로 불러옵니다 |

API 계약이 바뀌면 루트에서 `uv run python scripts/export_openapi.py` 뒤 `npm run gen:api`를 실행해 함께 커밋합니다(CI가 같은지 검사).

## 구조

```
src/
├── Root.tsx                # 화면 입구: / 소개 → /login 로그인 → /app 업무 화면(로그인 뒤, 따로 불러옴)
├── App.tsx                 # 업무 화면: 작업 공간(지금 지도)·밝기·배치·엑셀 가져오기
├── Workbench.tsx           # 한 지도의 업무 화면: 세션·비서·분석 기준을 모아 뼈대와 칸에 나눠 줌
├── state/                  # 동작 훅: 분석 세션·AI 비서·ECN 목록·상세·기록·명령 팔레트·상태 갱신
├── pages/                  # landing(소개) · login · manage(결재·현황) · report(판단 리포트)
├── components/
│   ├── shell/              # 뼈대: AppShell(폭별 배치), TopBar, CommandPalette, MapMenu, ThemeMenu, PaneHeader
│   ├── ecn/                # ECN 목록(왼쪽 칸)
│   ├── detail/             # ECN 상세(가운데 칸): 판정 머리·핵심 수치·할 일·사전 점검·근거 탭·들여쓴 목록(좁은 화면)
│   ├── graph/              # 영향 지도 그래프(넓은 화면, 따로 불러옴): GraphWorkspace(그래프 + 근거, 묶음 상태)·RippleFlow·FlowCards
│   ├── graph3d/            # 3D 배치(선체 위 블록·영향 관계, 3D를 열 때만 불러옴): Ship3DWorkspace·MapViewSwitch(2D·3D 전환)
│   ├── assistant/          # AI 비서 칸: 차례·되묻기 카드·알림 초안·메일 보내기
│   ├── records/            # 결재 띠·검토 요청·결정 대화상자·결정 도우미·이력 탭
│   ├── input/RequestEditor.tsx  # 요청 JSON 고치기(대화상자)
│   ├── intake/ · workspace/ · account/ · demo/ · curve/  # 문서 접수·엑셀 가져오기·계정·시연·곡선
│   ├── common/             # 여러 칸이 쓰는 부품(심각도 배지·용어 설명 등)
│   ├── EvidencePanel.tsx   # 근거 패널(엔터티·묶음 구성원·근거 경로)
│   └── ui/                 # shadcn 생성 부품(직접 고친 곳: 오버레이 흐림 제거, 한국어 문구)
├── lib/                    # 순수 함수와 작은 훅: 요청 글, 파급 계산, 그래프 묶음·배치(graphModel), 표기, 배치 모드, 밝기, 저장소, 초점
└── styles/                 # shadcn 상태 변형 사본(shadcn-variants.css), 근거 패널 스타일(evidence.css)
```

`public/`에는 소개 화면 그림(`landing/*.webp`, 1배·2배 — 크기는 `src/pages/landing/captures.ts`와 같아야 함), 아이콘·링크 미리보기 그림(`favicon.png` · `apple-touch-icon.png` · `brand/` · `og.png`), 첫 그림 전에 밝기를 정하는 `theme-init.js`가 있습니다. 배포는 `Dockerfile`(빌드 → Caddy)과 `Caddyfile`(정적 화면 + `/api` 넘김)입니다.

## 배치(DESIGN.md 7절)

| 폭 | 배치 |
|---|---|
| 1440px 이상 | ECN 목록 360 \| 상세 \| AI 비서 400(기본 닫힘). 경계는 끌거나 화살표·Home·End 키로 조절하고 크기는 이 브라우저에 기억합니다. 그래프는 방향키로 카드 이동, Enter 근거, Esc 돌아오기 |
| 1024~1439px | 목록(접기) + 상세, AI 비서는 오른쪽 시트 |
| 768~1023px | 한 칸 + 아래 탭(목록 · 상세 · 비서), 그래프 대신 들여쓴 영향 목록 |
| 768px 미만 | 목록 · 상세 두 탭(조회 전용) |

## shadcn 부품 더하기

`shadcn` 패키지는 의존성에 두지 않습니다(CLI 전체가 따라와 패키지가 약 2배로 늘어남). 필요한 상태 변형은 `src/styles/shadcn-variants.css`에 사본으로 두었습니다.

```bash
npx shadcn@4.21.3 add <부품 이름>
```

추가한 뒤 `package.json`에 `shadcn`이 생겼으면 지우고, 영어 문구·유리 효과(배경 흐림)·8px 넘는 모서리를 `DESIGN.md`에 맞게 고칩니다.
