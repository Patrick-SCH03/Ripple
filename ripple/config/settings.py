"""실행 설정: 환경 변수 → Settings.

비밀값(API 키·DB 비밀번호)은 이 모듈에서 다루지 않는다. 어댑터가 필요할 때 직접 읽고
로그에 남기지 않는다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ripple.contracts.domain import DataMode

PROJECT_ROOT = Path(__file__).resolve().parents[2]


GRAPH_STORES = ("memory", "neo4j")
SWITCHES = {"on": True, "off": False}
_BUILD = re.compile(r"^[0-9A-Za-z._-]{1,64}$")
_RESET_LABEL = re.compile(r"^[0-9A-Za-z_-]{1,40}$")  # ripple/store/reset.py LABEL과 같음
LLM_PROVIDERS = ("claude",)
# 뺀 제공자(Gemini): 배포 설정에 남아 있어도 시작을 막지 않고 건너뛴다(오타가 아닌 옛 이름만)
RETIRED_PROVIDERS = ("gemini",)
DEFAULT_SNAPSHOT = PROJECT_ROOT / "data" / "synthetic" / "20261020" / "snapshot.json"
GENERATOR_CONFIG = PROJECT_ROOT / "generator" / "config.yaml"  # 기본 합성 지도 생성기 설정
DEMO_GENERATOR_CONFIG = PROJECT_ROOT / "generator" / "demo_map.yaml"  # 시연 합성 지도(기본 + 블록 사이 관계 보강)
DEMO_SNAPSHOT = PROJECT_ROOT / "data" / "synthetic_demo" / "20261020" / "snapshot.json"  # generate.py --map demo
DEFAULT_DATA_DIR = PROJECT_ROOT / ".data"  # 가져온 지도·활성 지도 기록(깃 제외, 실데이터가 들어간다)


def parse_switch(name: str, value: str) -> bool:
    """on/off 설정. 그 밖의 값은 오류(오타로 보안 설정이 조용히 꺼지지 않게)."""
    key = value.strip().lower()
    if key not in SWITCHES:
        raise ValueError(f"{name}은(는) on 또는 off만 가능: {value!r}")
    return SWITCHES[key]


def parse_build(values: Mapping[str, str]) -> str | None:
    """배포한 커밋: RIPPLE_BUILD(이미지 빌드 인자) 또는 Railway가 주는 RAILWAY_GIT_COMMIT_SHA. 형식이 아니면 버림."""
    raw = values.get("RIPPLE_BUILD") or values.get("RAILWAY_GIT_COMMIT_SHA") or ""
    return raw if _BUILD.fullmatch(raw) else None


ResetScope = Literal["records", "all"]  # 기록 비우기 범위(ripple/store/reset.py)
SyntheticClock = Literal["fixed", "live"]  # 합성 시연 세계의 날짜(docs/operations.md(서비스) 6절)
SyntheticMap = Literal["base", "demo"]  # 기본 합성 지도 · 시연 합성 지도(docs/operations.md(서비스) 6절)


def parse_map(value: str) -> SyntheticMap:
    """RIPPLE_SYNTHETIC_MAP: base(기본, 평가 관문의 지도) 또는 demo(시연 합성 지도 — 시연 영상·공개 배포·소개 예시)."""
    name = value.strip().lower() or "base"
    if name == "base":
        return "base"
    if name == "demo":
        return "demo"
    raise ValueError(f"RIPPLE_SYNTHETIC_MAP은 base 또는 demo만 가능: {value!r}")


def parse_clock(value: str) -> SyntheticClock:
    """RIPPLE_SYNTHETIC_CLOCK: fixed(기본, 지도 파일의 날짜에 멈춤) 또는 live(한국 시간 오늘로 매일 다시 만듦)."""
    clock = value.strip().lower() or "fixed"
    if clock == "fixed":
        return "fixed"
    if clock == "live":
        return "live"
    raise ValueError(f"RIPPLE_SYNTHETIC_CLOCK은 fixed 또는 live만 가능: {value!r}")


def default_snapshot(values: Mapping[str, str]) -> Path:
    """RIPPLE_SNAPSHOT_PATH가 없을 때의 지도 파일: 시연 합성 지도면 그 생성 결과, 아니면 기본 합성 지도."""
    return DEMO_SNAPSHOT if parse_map(values.get("RIPPLE_SYNTHETIC_MAP", "")) == "demo" else DEFAULT_SNAPSHOT


def parse_reset(value: str) -> str | None:
    """RIPPLE_RESET_RECORDS: 비우면 아무것도 안 함. 값은 영문·숫자·_·- 1~40자(보관 폴더 이름에 씀)."""
    label = value.strip()
    if label and not _RESET_LABEL.fullmatch(label):
        raise ValueError(f"RIPPLE_RESET_RECORDS는 영문·숫자·_·- 1~40자만 가능: {value!r}")
    return label or None


def parse_reset_scope(value: str) -> ResetScope:
    """RIPPLE_RESET_SCOPE: records(기본, 기록·실적·수정 기록) 또는 all(+ 지도·상태 갱신·열 매핑 기억)."""
    scope = value.strip().lower() or "records"
    if scope == "records":
        return "records"
    if scope == "all":
        return "all"
    raise ValueError(f"RIPPLE_RESET_SCOPE는 records 또는 all만 가능: {value!r}")


def parse_llm(value: str) -> tuple[str, ...]:
    """RIPPLE_LLM: off(기본, 외부 호출 없음) 또는 제공자 쉼표 목록(claude). 같은 이름은 한 번, 뺀 제공자는 건너뜀.
    대소문자는 가리지 않는다('Claude'·'OFF' — 배포 변수 오타로 서버가 뜨지 않던 것)."""
    value = value.lower()
    if value.strip() in ("", "off"):
        return ()
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in LLM_PROVIDERS + RETIRED_PROVIDERS]
    if unknown or not names:
        raise ValueError(f"RIPPLE_LLM은 off 또는 {', '.join(LLM_PROVIDERS)}의 쉼표 목록만 가능: {value!r}")
    return tuple(dict.fromkeys(name for name in names if name in LLM_PROVIDERS))


@dataclass(frozen=True, slots=True)
class Settings:
    data_mode: DataMode
    rules_path: Path
    params_path: Path
    decision_path: Path
    lexicon_path: Path = PROJECT_ROOT / "rules" / "lexicon.yaml"  # 해석기 현장 용어 사전
    strength_path: Path = PROJECT_ROOT / "rules" / "strength.yaml"  # 대안 강도 사전검사 규칙
    snapshot_path: Path = DEFAULT_SNAPSHOT  # 앱이 시작할 때 불러올 연결 지도(scripts/generate.py가 만듦)
    graph_store: str = "memory"  # memory | neo4j(지도를 Neo4j에도 저장해 브라우저로 볼 수 있게)
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"  # 비밀번호는 Neo4j 어댑터가 NEO4J_PASSWORD에서 직접 읽는다
    # 켠 외부 생성 모델 제공자(비면 off). 합성 모드에서만 호출하고, 키는 어댑터가 .env에서 직접 읽는다
    llm_providers: tuple[str, ...] = ()
    llm_routes_path: Path = PROJECT_ROOT / "params" / "llm_v1.yaml"  # 작업별 모델 경로(측정으로 정함)
    data_dir: Path = DEFAULT_DATA_DIR  # 지도 저장소(ripple/store/snapshots.py)
    column_path: Path = PROJECT_ROOT / "params" / "column_v1.yaml"  # 엑셀 열 매핑 보정 산출물(열 문)
    contacts_path: Path = PROJECT_ROOT / "params" / "contacts_v1.yaml"  # 알림 메일의 시연용 가상 연락처(합성 지도만)
    glossary_path: Path = PROJECT_ROOT / "params" / "glossary_v1.yaml"  # 1.36.0 현장 통보문 번역 초안(고정 문장·용어집)
    # 로그인(docs/operations.md(서비스) 2절): off는 개발·검사용(모든 요청을 개발 관리자로). 이미지·배포 설정에는 두지
    # 않는다
    auth_required: bool = True
    demo_login: bool = False  # 체험 로그인(합성 데이터만 보는 공용 계정)
    # 빠른 로그인(시연 배포 전용): 아이디·비밀번호 없이 담당자·팀장 고정 계정으로. 누구나 팀장이 되므로 기본 꺼짐
    quick_login: bool = False
    cookie_secure: bool = True  # 세션 쿠키 Secure(https). 로컬 http에서 Secure 쿠키를 안 받는 도구를 쓸 때만 off
    build: str | None = None  # 배포한 커밋(상태 확인에 실어 라이브 주소의 버전을 확인)
    # 기록 비우기 표지(RIPPLE_RESET_RECORDS, docs/operations.md(배포) 4절): 새 값이면 시작할 때 기록·실적을 보관 폴더로
    # 옮긴다
    reset_records: str | None = None
    reset_scope: ResetScope = "records"  # RIPPLE_RESET_SCOPE: all이면 지도·상태 갱신·열 매핑 기억도 함께
    # live면 기본 합성 지도를 지도 파일 대신 생성기로 '한국 시간 오늘' 기준으로 만들고 날이 바뀌면 다시 만든다
    synthetic_clock: SyntheticClock = "fixed"
    # demo면 기본 지도 자리에 시연 합성 지도(generator/demo_map.yaml)를 깐다. 라이브 배포에는 두지 않는다(기본 base)
    synthetic_map: SyntheticMap = "base"
    # 합성 시연 기록 시드(RIPPLE_DEMO_SEED, docs/operations.md(서비스) 7절): 켜면 기록 저장소가 비어 있을 때 한 번,
    # 실제 기록 흐름으로 팀장 화면을 채우는 과거 기록을 만든다. 합성 데이터 모드에서만
    demo_seed: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if env is None else env
        mode = values.get("RIPPLE_DATA_MODE", DataMode.SYNTHETIC.value)
        try:
            data_mode = DataMode(mode)
        except ValueError:
            raise ValueError(f"RIPPLE_DATA_MODE는 synthetic 또는 real만 가능: {mode!r}") from None
        providers = parse_llm(values.get("RIPPLE_LLM", "off"))
        store = values.get("RIPPLE_GRAPH_STORE", "memory")
        if store not in GRAPH_STORES:
            raise ValueError(f"RIPPLE_GRAPH_STORE는 {' 또는 '.join(GRAPH_STORES)}만 가능: {store!r}")
        return cls(
            data_mode=data_mode,
            rules_path=Path(values.get("RIPPLE_RULES_PATH", PROJECT_ROOT / "rules" / "propagation.yaml")),
            params_path=Path(values.get("RIPPLE_PARAMS_PATH", PROJECT_ROOT / "params" / "cost_v1.yaml")),
            decision_path=Path(values.get("RIPPLE_DECISION_PATH", PROJECT_ROOT / "params" / "decision_v3.yaml")),
            lexicon_path=Path(values.get("RIPPLE_LEXICON_PATH", PROJECT_ROOT / "rules" / "lexicon.yaml")),
            strength_path=Path(values.get("RIPPLE_STRENGTH_PATH", PROJECT_ROOT / "rules" / "strength.yaml")),
            snapshot_path=Path(values.get("RIPPLE_SNAPSHOT_PATH", default_snapshot(values))),
            graph_store=store,
            neo4j_uri=values.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            neo4j_user=values.get("NEO4J_USER", "neo4j"),
            llm_providers=providers,
            llm_routes_path=Path(values.get("RIPPLE_LLM_ROUTES_PATH", PROJECT_ROOT / "params" / "llm_v1.yaml")),
            data_dir=Path(values.get("RIPPLE_DATA_DIR", DEFAULT_DATA_DIR)),
            column_path=Path(values.get("RIPPLE_COLUMN_PATH", PROJECT_ROOT / "params" / "column_v1.yaml")),
            contacts_path=Path(values.get("RIPPLE_CONTACTS_PATH", PROJECT_ROOT / "params" / "contacts_v1.yaml")),
            glossary_path=Path(values.get("RIPPLE_GLOSSARY_PATH", PROJECT_ROOT / "params" / "glossary_v1.yaml")),
            auth_required=parse_switch("RIPPLE_AUTH", values.get("RIPPLE_AUTH", "on")),
            demo_login=parse_switch("RIPPLE_DEMO_LOGIN", values.get("RIPPLE_DEMO_LOGIN", "off")),
            quick_login=parse_switch("RIPPLE_QUICK_LOGIN", values.get("RIPPLE_QUICK_LOGIN", "off")),
            cookie_secure=parse_switch("RIPPLE_COOKIE_SECURE", values.get("RIPPLE_COOKIE_SECURE", "on")),
            build=parse_build(values),
            reset_records=parse_reset(values.get("RIPPLE_RESET_RECORDS", "")),
            # 범위는 표지가 있을 때만 읽는다(표지 없이 남은 범위 변수의 오타로 서버가 뜨지 않게)
            reset_scope=parse_reset_scope(values.get("RIPPLE_RESET_SCOPE", ""))
            if parse_reset(values.get("RIPPLE_RESET_RECORDS", ""))
            else "records",
            synthetic_clock=parse_clock(values.get("RIPPLE_SYNTHETIC_CLOCK", "")),
            synthetic_map=parse_map(values.get("RIPPLE_SYNTHETIC_MAP", "")),
            demo_seed=parse_switch("RIPPLE_DEMO_SEED", values.get("RIPPLE_DEMO_SEED", "off")),
        )

    @property
    def generator_config(self) -> Path:
        """기본 지도 자리의 합성 세계를 만드는 생성기 설정(실시간 시연 세계·시연 기록·합성 과거 사례가 같이 쓴다)."""
        return DEMO_GENERATOR_CONFIG if self.synthetic_map == "demo" else GENERATOR_CONFIG

    @property
    def live_world(self) -> bool:
        """합성 모드에서 시연 세계를 실시간(한국 시간 오늘)으로 돌리나."""
        return self.synthetic_clock == "live" and self.data_mode is DataMode.SYNTHETIC
