"""API의 성질: 버전 확인, 영향 탐색·부분 그래프·샘플, 계약대로 받고 거부, OpenAPI 계약 파일이 최신.

지도 파일은 임시 폴더에 생성기로 만들어 쓴다(저장소의 data/는 커밋하지 않는다).
"""

from __future__ import annotations

import json
import tempfile
import time
import tomllib
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from harness import Checker, nominal

from ripple import __version__
from ripple.api.app import create_app
from ripple.api.openapi import OPENAPI_PATH, render_openapi
from ripple.api.samples import with_summaries
from ripple.api.workspace import Workspaces
from ripple.config.loaders import load_decision_config, load_params, load_rulebook, load_strength
from ripple.config.settings import PROJECT_ROOT, Settings
from ripple.contracts.assistant import AnalysisNotices, AssistantTurn, NotificationTarget
from ripple.contracts.base import CONTRACT_VERSION
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.graphview import GraphView
from ripple.contracts.identity import snapshot_id
from ripple.contracts.result import Amount, AnalysisResult, ImpactReport, ZeroLossDeadline
from ripple.explain.compose import notifications
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.graph.factory import open_store

with warnings.catch_warnings():
    # starlette 테스트 클라이언트가 httpx 대신 httpx2를 권하는 안내(UserWarning 하위). httpx를 유지한다
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient


def run(c: Checker) -> None:
    generated = generate(load_config())
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        settings = replace(
            Settings.from_env({"RIPPLE_AUTH": "off"}),  # 로그인·권한은 tests/checks/auth.py
            snapshot_path=root / "synthetic" / "snapshot.json",
            data_dir=root / "data",
        )
        app = create_app(settings)
        with TestClient(app) as client:
            _system(c, client, settings, generated.snapshot.snapshot_id)
            _impacts(c, client)
            _analyses(c, client, app)
            _assistant(c, client)
            _graph(c, client)
            _body_limit(c, client)
        _startup(c, root, settings)
    _contract_file(c, app)


def _body_limit(c: Checker, client: TestClient) -> None:
    c.section("API: 본문 크기 상한")
    big = b"{" + b" " * (2 * 1024 * 1024) + b"}"
    json_headers = {"content-type": "application/json"}
    over = client.post("/api/analyses", content=big, headers=json_headers)
    login = client.post("/api/auth/login", content=big, headers=json_headers)
    c.check(
        "엑셀 올리기 밖의 2MB 본문은 읽기 전에 413(분석·로그인 경로)",
        over.status_code == 413 and login.status_code == 413 and "1MB" in over.json()["detail"],
        (over.status_code, login.status_code),
    )
    upload = client.post("/api/imports", params={"file_name": "x.xlsx"}, content=b"PK" + b"0" * (2 * 1024 * 1024))
    c.check(
        "엑셀 올리기는 1MB 상한을 받지 않음(파일 검사까지 가서 xlsx가 아니라 422, 20MB는 경로가 셈)",
        upload.status_code == 422,
        upload.status_code,
    )


def _assistant(c: Checker, client: TestClient) -> None:
    c.section("API: AI 비서 대화")
    context = {"ship_ids": ["S-001"], "as_of": "2026-10-20"}
    message = "선주 요청으로 펌프룸 스트리핑 글로브 밸브 1번을 볼 밸브로 바꿔 주세요"
    first = client.post("/api/assistant/turns", json={"context": context, "message": message})
    body = first.json()
    c.check("데모 1 문장 → 200, 분석까지", first.status_code == 200 and body["state"] == "analyzed", first.status_code)
    c.check(
        "응답은 비서 차례 계약대로(결과·설명·알림)",
        AssistantTurn.model_validate(body).result is not None and len(body["notifications"]) >= 1,
    )
    history = client.get(f"/api/assistant/conversations/{body['conversation_id']}")
    c.check("대화 기록 조회", history.status_code == 200 and len(history.json()["turns"]) == 1)
    c.check("없는 대화 조회는 404", client.get("/api/assistant/conversations/C-none").status_code == 404)
    ghost = client.post(
        "/api/assistant/turns",
        json={"conversation_id": "C-none", "context": context, "answer": {"question_id": "intent", "option_id": "x"}},
    )
    c.check("없는 대화의 답은 409", ghost.status_code == 409, ghost.status_code)
    both = client.post("/api/assistant/turns", json={"context": context})
    c.check("문장도 답도 없으면 422", both.status_code == 422, both.status_code)


def _system(c: Checker, client: TestClient, settings: Settings, expected_snapshot: str) -> None:
    c.section("API: 상태 확인")
    health = client.get("/api/health")
    body = health.json()
    c.check("상태 확인은 200", health.status_code == 200, health.status_code)
    c.check(
        "상태 확인에 앱·계약 버전과 불러온 지도 ID가 나옴",
        body["app_version"] == __version__
        and body["contract_version"] == CONTRACT_VERSION
        and body["snapshot_id"] == expected_snapshot,
    )
    c.check(
        "상태 확인의 규칙·파라미터·강도 규칙·판단 버전이 YAML과 같음",
        (body["rules_version"], body["params_version"], body["strength_version"], body["decision_version"])
        == (
            load_rulebook(settings.rules_path).version,
            load_params(settings.params_path).version,
            load_strength(settings.strength_path).version,
            load_decision_config(settings.decision_path).version,
        ),
    )
    c.check("기본 데이터 모드는 synthetic", body["data_mode"] == "synthetic")
    real = Settings.from_env({"RIPPLE_DATA_MODE": "real"})
    c.check("환경 변수로 real 모드를 켤 수 있음", real.data_mode is DataMode.REAL)
    c.check("데이터 모드 오타는 시작할 때 거부", c.raises(lambda: Settings.from_env({"RIPPLE_DATA_MODE": "reel"})))
    c.check(
        "지도 저장소 이름 오타는 시작할 때 거부", c.raises(lambda: Settings.from_env({"RIPPLE_GRAPH_STORE": "neo"}))
    )
    neo4j = Settings.from_env({"RIPPLE_GRAPH_STORE": "neo4j"})
    c.check("Neo4j 저장소는 비밀번호 환경 변수 없이 열지 않음", c.raises(lambda: open_store(neo4j, env={})))

    c.check(
        "계약에 맞지 않는 분석 요청은 422",
        client.post("/api/analyses", json={"as_of": "2026-10-20"}).status_code == 422,
    )


def _impacts(c: Checker, client: TestClient) -> None:
    c.section("API: 영향 탐색")
    samples = client.get("/api/samples").json()
    ops = {s["op"] for s in samples}
    c.check("샘플은 연산 8종을 모두 담음", len(ops) == 8, sorted(ops))
    responses = [client.post("/api/impacts", json=s["request"]) for s in samples]
    c.check("샘플 요청은 모두 200", all(r.status_code == 200 for r in responses), [r.status_code for r in responses])
    reports = [ImpactReport.model_validate(r.json()) for r in responses]
    c.check(
        "샘플마다 미리 계산한 규칙과 응답의 규칙이 같음",
        all(
            tuple(s["rules"]) == tuple(sorted({i.rule_id for i in r.impacts}))
            for s, r in zip(samples, reports, strict=True)
        ),
    )
    again = client.post("/api/impacts", json=samples[0]["request"]).json()
    c.check("같은 요청이면 같은 응답(분석 ID 포함)", again == responses[0].json())
    body = samples[0]["request"]
    body = body | {"change": body["change"] | {"ops": [{"op": "remove_part", "part_ids": ["S-001:없는-부재"]}]}}
    refused = client.post("/api/impacts", json=body)
    detail = refused.json().get("detail", {})
    c.check(
        "지도와 맞지 않는 요청은 422와 명사형 이유 목록",
        refused.status_code == 422 and bool(detail.get("problems")) and all(nominal(p) for p in detail["problems"]),
        detail,
    )
    c.check(
        "계약에 맞지 않는 영향 요청도 422",
        client.post("/api/impacts", json={"as_of": "2026-10-20"}).status_code == 422,
    )
    thick = next(s["request"] for s in samples if "to_mm" in s["request"]["change"]["ops"][0])
    op = thick["change"]["ops"][0] | {"to_mm": float("inf")}
    endless = json.dumps(thick | {"change": thick["change"] | {"ops": [op]}})  # 'Infinity' 그대로
    statuses = [
        client.post(path, content=endless, headers={"content-type": "application/json"}).status_code
        for path in ("/api/impacts", "/api/analyses")
    ]
    c.check("JSON의 Infinity 수치는 서버 오류가 아니라 422", statuses == [422, 422], statuses)


def _analyses(c: Checker, client: TestClient, app: FastAPI) -> None:
    c.section("API: 비용·일정 분석")
    samples = client.get("/api/samples").json()
    responses = [client.post("/api/analyses", json=s["request"]) for s in samples]
    c.check("샘플 요청은 모두 200", all(r.status_code == 200 for r in responses), [r.status_code for r in responses])
    results = [AnalysisResult.model_validate(r.json()) for r in responses]
    reports = [ImpactReport.model_validate(client.post("/api/impacts", json=s["request"]).json()) for s in samples]
    c.check(
        "분석 결과의 영향은 영향 탐색 결과를 모두 담음(일정·보류·인도 영향을 더할 뿐)",
        all(
            {i.key for i in rep.impacts} <= {i.key for i in res.impacts}
            for rep, res in zip(reports, results, strict=True)
        ),
    )
    c.check(
        "곡선은 기준일부터 탐색 기간 끝까지, 요약 판정과 영향 그래프가 있음",
        all(len(r.timing.curve) == r.request.horizon_days + 1 and r.graph.nodes for r in results),
    )
    summaries = [s.get("summary") for s in samples]
    c.check(
        f"샘플 {len(samples)}건 모두 목록 요약 = 같은 요청(기준일 확정·보류 없음)의 분석"
        "(판정·추가손실 0 마감일·총액·분석 ID)",
        len(samples) >= 10
        and all(
            summary is not None
            and summary["analysis_id"] == result.analysis_id
            and summary["verdict"] == result.verdict.level.value
            and ZeroLossDeadline.model_validate(summary["deadline"]) == result.timing.deadline
            and Amount.model_validate(summary["total"]) == result.total
            for summary, result in zip(summaries, results, strict=True)
        ),
    )
    holder = app.state.workspaces
    assert isinstance(holder, Workspaces) and holder.current is not None
    workspace = holder.current
    blocks = workspace.index.blocks
    c.check(
        "목록 요약의 블록 = 바뀌는 부재가 속한 지도 블록(비어 있지 않고 ID 순)",
        all(s["blocks"] and s["blocks"] == sorted(s["blocks"]) and set(s["blocks"]) <= set(blocks) for s in summaries),
        [s["blocks"] for s in summaries][:3],
    )
    book = load_rulebook(PROJECT_ROOT / "rules" / "propagation.yaml")
    params = load_params(PROJECT_ROOT / "params" / "cost_v1.yaml")
    started = time.perf_counter()
    with_summaries(workspace.samples, workspace.index, book, params)
    took = time.perf_counter() - started
    c.check(
        f"앱 시작 때 목록 요약 {len(samples)}건 {took:.1f}초(1건 1초 상한 × 건수 안)",
        took <= len(samples),
        took,
    )
    again = client.post("/api/analyses", json=samples[0]["request"]).json()
    c.check("같은 요청이면 같은 응답(분석 ID 포함)", again == responses[0].json())
    body = samples[0]["request"] | {"holds": [{"po_id": "PO-없음", "hold_days": 5}]}
    refused = client.post("/api/analyses", json=body)
    detail = refused.json().get("detail", {})
    c.check(
        "지도에 없는 발주를 보류하면 422와 명사형 이유",
        refused.status_code == 422 and any("보류할 발주" in p and nominal(p) for p in detail.get("problems", [])),
        detail,
    )
    thick = next(s for s in samples if s["request"]["change"]["ecn_id"] == "ECN-D-0119")
    wide = client.post("/api/analyses", json=thick["request"] | {"include_alternatives": True})
    alts = AnalysisResult.model_validate(wide.json()) if wide.status_code == 200 else None
    c.check(
        "대안을 켜면 요청안이 첫 대안이고 권고·날짜별 최저 비용 대안·강도 규칙 버전이 있음(ECN-D-0119)",
        alts is not None
        and alts.alternatives[0].alt_id == "ALT-REQ"
        and len(alts.alternatives) > 1
        and alts.recommendation is not None
        and bool(alts.cheapest_by_date)
        and alts.versions.strength == load_strength(PROJECT_ROOT / "rules" / "strength.yaml").version,
        wide.status_code,
    )
    plain = AnalysisResult.model_validate(responses[samples.index(thick)].json())
    c.check(
        "대안을 켜도 요청안의 비용 줄·총액은 같고 분석 ID는 다름",
        alts is not None
        and alts.cost_lines == plain.cost_lines
        and alts.total == plain.total
        and alts.analysis_id != plain.analysis_id,
    )
    _notices(c, client, samples, results, workspace.assistant.resources.directory)


def _notices(
    c: Checker, client: TestClient, samples: list[dict[str, Any]], results: list[AnalysisResult], directory: Any
) -> None:
    """1.37.0 상세 '통보문 보기': 같은 요청 → 같은 분석 ID, 비서와 같은 규칙의 초안(작업반 번역), 받는 쪽 거르기."""
    crew = [client.post("/api/analyses/notices?target=crew", json=s["request"]) for s in samples]
    bodies = [AnalysisNotices.model_validate(r.json()) for r in crew if r.status_code == 200]
    c.check(
        "통보문 요청은 모두 200 · 분석 ID = 같은 요청의 분석",
        len(bodies) == len(samples)
        and all(b.analysis_id == r.analysis_id for b, r in zip(bodies, results, strict=True)),
        [r.status_code for r in crew],
    )
    c.check(
        "target=crew면 작업반 초안만, 비서 분석 차례와 같은 규칙(compose.notifications)의 초안 그대로",
        all(
            b.notifications == tuple(n for n in notifications(r, directory) if n.target is NotificationTarget.CREW)
            for b, r in zip(bodies, results, strict=True)
        ),
    )
    with_crew = [b for b in bodies if b.notifications]
    c.check(
        f"작업반 통보가 있는 샘플 {len(with_crew)}건 · 모두 번역 초안(영어·베트남어)과 공식 메일",
        bool(with_crew) and all(n.email and n.email.translations for b in with_crew for n in b.notifications),
    )
    every = client.post("/api/analyses/notices", json=samples[0]["request"])
    c.check(
        "받는 쪽을 주지 않으면 비서와 같은 알림 초안 전부",
        every.status_code == 200
        and AnalysisNotices.model_validate(every.json()).notifications == notifications(results[0], directory),
        every.status_code,
    )


def _graph(c: Checker, client: TestClient) -> None:
    c.section("API: 부분 그래프")
    request = client.get("/api/samples").json()[0]["request"]
    report = ImpactReport.model_validate(client.post("/api/impacts", json=request).json())
    center = next(n.id for n in report.graph.nodes if n.attrs.get("role") == "target")
    view = client.get("/api/graph/view", params={"center": center, "depth": 1})
    graph = GraphView.model_validate(view.json())
    c.check("중심 엔터티의 깊이 1 부분 그래프", view.status_code == 200 and center in {n.id for n in graph.nodes})
    pair = [("center", center), ("center", report.impacts[0].entity_id), ("depth", "0")]
    several = client.get("/api/graph/view", params=pair)
    c.check(
        "중심을 여러 개 주면 그 노드들과 사이 연결", several.status_code == 200 and len(several.json()["nodes"]) == 2
    )
    c.check("없는 엔터티는 404", client.get("/api/graph/view", params={"center": "없는-ID"}).status_code == 404)
    deep = client.get("/api/graph/view", params={"center": center, "depth": 9})
    c.check("깊이 상한(4)을 넘으면 422", deep.status_code == 422)


def _startup(c: Checker, root: Path, settings: Settings) -> None:
    c.section("API: 시작할 때 지도 확인")

    def start(target: Path) -> None:
        with TestClient(create_app(replace(settings, snapshot_path=target))):
            pass

    c.check("지도 파일이 없으면 시작하지 않음", c.raises(lambda: start(root / "없음.json"), FileNotFoundError))
    snapshot = GraphSnapshot.model_validate_json((root / "synthetic" / "snapshot.json").read_text(encoding="utf-8"))
    renamed = snapshot.model_copy(update={"blocks": (snapshot.blocks[0].model_copy(update={"name": "바뀐 이름"}),)})
    tampered = root / "tampered.json"
    tampered.write_text(renamed.model_dump_json(), encoding="utf-8")
    c.check("내용과 ID가 맞지 않는 지도는 거부", c.raises(lambda: start(tampered)))
    real = snapshot.model_copy(update={"origin": "excel_import", "data_mode": DataMode.REAL})
    real_path = root / "real.json"
    real_path.write_text(real.model_copy(update={"snapshot_id": snapshot_id(real)}).model_dump_json(), encoding="utf-8")
    c.check("실제 데이터 지도는 synthetic 모드에서 열지 않음", c.raises(lambda: start(real_path)))


def _contract_file(c: Checker, app: FastAPI) -> None:
    c.section("API 계약 파일")
    schemas = app.openapi()["components"]["schemas"]
    c.check(
        "OpenAPI에 분석 요청·영향 보고·부분 그래프·샘플 스키마가 있음",
        {"AnalysisRequest", "AnalysisResult", "ImpactReport", "GraphView", "Sample", "Health"} <= set(schemas),
    )
    target = PROJECT_ROOT / OPENAPI_PATH
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    c.check(
        "docs/api/openapi.json이 최신(scripts/export_openapi.py로 갱신)",
        current == render_openapi(app),
    )
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    c.check("패키지 버전과 앱 버전이 같음", project["version"] == __version__)
