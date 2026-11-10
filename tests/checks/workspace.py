"""작업 공간·지도 전환의 성질(docs/operations.md(서비스) 6절).

지도 저장소(원자적 쓰기·내용 해시 대조·경로 조작 차단), 시작 복구(기록이 깨졌으면 기본 지도 + 사유), 세대 전환
(실패하면 이전 세대 그대로), 유효 데이터 모드(실데이터 지도에서 외부 호출 0), 요청 정합(기대 토큰이 다르면 409,
응답 머리글은 처리한 세대), 가져오기 API(올리기 → 확정, 크기 상한), 재시작 복구. 지도 파일·데이터 폴더는 임시 폴더에
만든다.
"""

from __future__ import annotations

import io
import tempfile
import threading
import warnings
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

from harness import Checker
from openpyxl import load_workbook
from openpyxl.styles import Font

from checks.llm import DEMO1, FakeModel
from ripple.api import pending_imports as pending_imports_module
from ripple.api import workspace as workspace_module
from ripple.api.app import create_app
from ripple.api.deps import AppContext
from ripple.api.routes import analyses as analyses_route
from ripple.api.workspace import PENDING_TTL_S, ImportChanged, NotFound, StaleWorkspace, Workspaces, info_of
from ripple.config.settings import Settings
from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.identity import snapshot_id
from ripple.contracts.ingest import MappingOverrides, MappingProposal, MappingSubmission, SheetOverride
from ripple.contracts.result import AnalysisResult
from ripple.contracts.workspace import WORKSPACE_HEADER, ImportPreview, SnapshotList
from ripple.engine.analyze import analyze
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.graph.memory import MemoryGraphStore
from ripple.ingest import build as build_module
from ripple.ingest import workbook as workbook_module
from ripple.ingest.export import to_bytes
from ripple.ingest.proposal import mapping_of, same_mapping
from ripple.ingest.variants import gate_variants
from ripple.store.snapshots import SnapshotStore, SnapshotStoreError, checked_id, write_atomic

with warnings.catch_warnings():
    # starlette 테스트 클라이언트가 httpx 대신 httpx2를 권하는 안내(UserWarning 하위). httpx를 유지한다
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

FILE = "ripple-template.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CONTEXT = {"ship_ids": ["S-001"], "as_of": "2026-10-20"}
UNREAD = "pump room CS line valve No.1 ball type please"  # 규칙 기반이 못 읽어 합성 모드면 다시 쓰기를 부르는 문장


def run(c: Checker) -> None:
    generated = generate(load_config())
    snapshot = generated.snapshot
    template = to_bytes(snapshot)  # 기본 지도 내보내기 = 양식 예시
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        _store(c, root, snapshot)
        imported = _api(c, root, snapshot, template)
        _limits(c, root, template)
        _external(c, root, template)
        _restart(c, root, snapshot.snapshot_id, imported)
        _holder(c, root, template)
        _review(c, root, snapshot)


def _settings(root: Path, data: str) -> Settings:
    """로그인은 끈다(작업 공간 성질만 본다 — 로그인·권한은 tests/checks/auth.py)."""
    base = Settings.from_env({"RIPPLE_AUTH": "off"})
    return replace(base, snapshot_path=root / "synthetic" / "snapshot.json", data_dir=root / data)


def _real(snapshot: GraphSnapshot) -> GraphSnapshot:
    real = snapshot.model_copy(update={"origin": "excel_import", "data_mode": DataMode.REAL})
    return real.model_copy(update={"snapshot_id": snapshot_id(real)})


def _bound(token: str) -> dict[str, str]:
    return {WORKSPACE_HEADER: token}


def _upload(client: TestClient, data: bytes, name: str = FILE) -> Any:
    return client.post(
        "/api/imports", params={"file_name": name}, content=data, headers={"Content-Type": "application/octet-stream"}
    )


def _submit(client: TestClient, proposal: MappingProposal) -> Any:
    """제안 그대로 '이대로 읽기'."""
    body = {"version": proposal.version, "mapping": mapping_of(proposal).model_dump(mode="json")}
    return client.post(f"/api/imports/{proposal.import_id}/mapping", json=body)


def _read(client: TestClient, data: bytes, name: str = FILE) -> ImportPreview:
    """올리기 → 제안 그대로 읽기 → 읽기 결과."""
    staged = _upload(client, data, name)
    assert staged.status_code == 200, staged.text[:300]
    response = _submit(client, MappingProposal.model_validate(staged.json()))
    assert response.status_code == 200, response.text[:300]
    return ImportPreview.model_validate(response.json())


def _confirm(client: TestClient, preview: ImportPreview, token: str | None = None) -> Any:
    headers = _bound(token) if token else {}
    return client.post(f"/api/imports/{preview.import_id}/confirm", json={"version": preview.version}, headers=headers)


def _attempt(run: Any) -> object:
    """실행 결과 또는 그 예외(다른 스레드의 결과를 검사에서 보려고)."""
    try:
        return run()
    except Exception as error:
        return error


def _listing(client: TestClient) -> SnapshotList:
    return SnapshotList.model_validate(client.get("/api/snapshots").json())


def _activate(client: TestClient, key: str, token: str) -> SnapshotList:
    response = client.post(f"/api/snapshots/{key}/activate", headers=_bound(token))
    assert response.status_code == 200, response.text
    return SnapshotList.model_validate(response.json())


def _xlsx(workbook: Any) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@contextmanager
def _limit(module: ModuleType, name: str, value: int) -> Iterator[None]:
    with mock.patch.object(module, name, value):
        yield


def _numbers(result: AnalysisResult) -> object:
    """지도 출처(엑셀 행)·ID를 뺀 계산 수치: 비용 줄·총액·판정·시점·일정."""
    lines = [line.model_dump(mode="json", exclude={"sources"}) for line in result.cost_lines]
    return (lines, result.total, result.verdict, result.timing, result.schedule)


# ---------- 지도 저장소 ----------


def _store(c: Checker, root: Path, snapshot: GraphSnapshot) -> None:
    c.section("지도 저장소: 원자적 쓰기·내용 대조·경로 조작 차단")
    store = SnapshotStore(root / "store")
    c.check("빈 저장소: 목록 없음·활성 기록 없음(기본 지도)", store.infos() == () and store.active() is None)
    real = _real(snapshot)
    first = info_of(real, "a.xlsx", imported_at=datetime(2026, 10, 8, 6, 0, tzinfo=UTC))
    saved = store.save(real, first)
    c.check(
        "저장 → 읽기: 같은 지도, 목록에 한 항목", store.load(real.snapshot_id) == real and store.infos() == (saved,)
    )
    later = info_of(real, "b.xlsx", imported_at=datetime(2026, 10, 9, tzinfo=UTC))
    c.check(
        "같은 지도를 다시 저장하면 한 항목이고 처음 정보(이름·가져온 시각)를 그대로 둠",
        store.save(real, later) == first and store.infos() == (first,),
    )
    c.check(
        "쓰고 나면 임시 파일이 남지 않음", not list(store.folder.glob(".*.tmp")) and not list(root.glob("store/.*.tmp"))
    )

    path = store.folder / f"{real.snapshot_id}.json"
    good = path.read_text(encoding="utf-8")
    renamed = real.model_copy(update={"blocks": (real.blocks[0].model_copy(update={"name": "바뀐 이름"}),)})
    path.write_text(renamed.model_dump_json(), encoding="utf-8")
    c.check(
        "내용이 ID와 맞지 않는(변조·손상) 지도는 읽지 않음",
        c.raises(lambda: store.load(real.snapshot_id), SnapshotStoreError),
    )
    path.write_text("{ 깨진 JSON", encoding="utf-8")
    c.check("깨진 지도 파일도 읽지 않음", c.raises(lambda: store.load(real.snapshot_id), SnapshotStoreError))
    store.save(real, first)
    c.check(
        "손상된 사본은 다시 저장하면 고쳐짐", store.load(real.snapshot_id) == real and path.read_text("utf-8") == good
    )

    c.check(
        "지도 ID 형식이 아닌 값(경로 조작)은 파일에 닿기 전에 거부",
        c.raises(lambda: checked_id("../active"), SnapshotStoreError)
        and c.raises(lambda: store.load("..\\active"), SnapshotStoreError)
        and c.raises(lambda: store.set_active("G-../../x"), SnapshotStoreError),
    )
    store.set_active(real.snapshot_id)
    pointed = store.active()
    store.set_active(None)
    c.check("활성 기록: 지도 ID ↔ null(기본 지도) 왕복", pointed == real.snapshot_id and store.active() is None)
    (store.root / "active.json").write_text("{ 깨짐", encoding="utf-8")
    c.check("깨진 활성 기록은 읽기 오류(조용히 기본 지도로 넘어가지 않음)", c.raises(store.active, SnapshotStoreError))

    # 글자 인코딩이 깨진 파일도 저장소 오류여야 시작 복구·목록이 그 파일만 건너뛴다
    (store.root / "active.json").write_bytes(b'{"snapshot_id": "\xff\xfe"}')
    info_path = store.folder / f"{real.snapshot_id}.info.json"
    good_info = info_path.read_bytes()
    info_path.write_bytes(b"\xff\xfe broken")
    listed = store.infos()
    info_path.write_bytes(good_info)
    path.write_bytes(b"\xff\xfe")
    c.check(
        "글자 인코딩이 깨진 활성 기록·정보 파일·지도 파일은 모두 저장소 오류(정보가 깨진 지도는 목록에서만 빠짐)",
        c.raises(store.active, SnapshotStoreError)
        and listed == ()
        and c.raises(lambda: store.load(real.snapshot_id), SnapshotStoreError),
        listed,
    )
    store.save(real, first)

    target = root / "store" / "note.txt"
    target.write_text("원래 내용", encoding="utf-8")
    with mock.patch("ripple.config.files.os.replace", side_effect=OSError("disk full")):  # write_atomic이 있는 곳
        failed = c.raises(lambda: write_atomic(target, "새 내용"), OSError)
    c.check(
        "바꿔 끼우기가 실패하면 원래 파일 그대로, 임시 파일도 지움",
        failed and target.read_text(encoding="utf-8") == "원래 내용" and not list(target.parent.glob(".*.tmp")),
    )


# ---------- API: 가져오기·전환·요청 정합 ----------


def _api(c: Checker, root: Path, snapshot: GraphSnapshot, template: bytes) -> str:
    c.section("작업 공간: 가져오기 → 확정 → 전환, 요청 정합(토큰)")
    settings = _settings(root, "data-a")
    app = create_app(settings)
    default_id = snapshot.snapshot_id
    with TestClient(app) as client:
        first = _listing(client)
        c.check(
            "시작: 활성 = 기본 지도(세대 1·합성·외부 모델 없음), 목록은 기본 지도 하나, 복구 문제 없음",
            first.active_snapshot_id == default_id
            and first.generation == 1
            and first.data_mode is DataMode.SYNTHETIC
            and not first.llm_external
            and first.restore_problem is None
            and [(i.snapshot_id, i.default) for i in first.items] == [(default_id, True)],
        )
        health = client.get("/api/health").json()
        c.check(
            "상태 확인의 작업 공간 토큰·지도 ID = 목록",
            health["workspace"] == first.workspace and health["snapshot_id"] == default_id,
        )
        samples = client.get("/api/samples", headers=_bound(first.workspace))
        c.check(
            "기대 토큰이 맞으면 200, 응답 머리글 = 처리한 세대의 토큰",
            samples.status_code == 200 and samples.headers.get(WORKSPACE_HEADER) == first.workspace,
        )
        thick = next(s for s in samples.json() if s["ecn_id"] == "ECN-D-0119")["request"]
        before = AnalysisResult.model_validate(
            client.post("/api/analyses", json=thick, headers=_bound(first.workspace)).json()
        )

        staged = _upload(client, template)
        proposal = MappingProposal.model_validate(staged.json())
        c.check(
            "지정 양식(기본 지도 내보내기) 올리기: 매핑 제안 = 모든 시트·열 정확 일치(확인할 것 0·상태 버전 1), "
            "지도는 아직",
            staged.status_code == 200 and proposal.exact and proposal.pending == 0 and proposal.version == 1,
            staged.text[:300],
        )
        read = _submit(client, proposal)
        preview = ImportPreview.model_validate(read.json())
        info = preview.info
        c.check(
            "이대로 읽기: 오류 없음·확정 ID·상태 버전 2·실제 데이터·호선·자료 기준일 2026-10-20",
            read.status_code == 200
            and preview.version == 2
            and preview.import_id is not None
            and info is not None
            and info.data_mode is DataMode.REAL
            and info.origin == "excel_import"
            and info.name == FILE
            and info.ship_ids == ("S-001",)
            and info.status_date == date(2026, 10, 20),
            read.text[:300],
        )
        assert preview.import_id is not None and info is not None
        imported = info.snapshot_id
        c.check("올리기·읽기만 하면 목록·활성 지도 그대로(확정 전)", _listing(client) == first)
        stale = _confirm(client, preview, f"{default_id}.x.1")
        c.check(
            "확정에 다른 토큰 → 409 workspace_changed(지금 토큰·지도 ID를 알려 줌), 활성 지도 그대로",
            stale.status_code == 409
            and stale.json()["detail"]["code"] == "workspace_changed"
            and stale.json()["detail"]["active"] == first.workspace
            and _listing(client).workspace == first.workspace,
            stale.text[:200],
        )
        confirmed = _confirm(client, preview, first.workspace)
        second = SnapshotList.model_validate(confirmed.json())
        c.check(
            "확정 → 그 지도로 전환(세대 2·유효 모드 real), 목록 = 기본 지도 + 가져온 지도",
            confirmed.status_code == 200
            and second.active_snapshot_id == imported
            and second.generation == 2
            and second.data_mode is DataMode.REAL
            and not second.llm_external
            and [i.snapshot_id for i in second.items] == [default_id, imported]
            and second.items[1].summary is not None,
        )
        repeat = _confirm(client, preview)
        c.check(
            "같은 가져오기를 같은 버전으로 다시 확정해도(응답을 잃은 재시도) 그대로: 200·같은 토큰(새 세대 없음)",
            repeat.status_code == 200 and SnapshotList.model_validate(repeat.json()).workspace == second.workspace,
            repeat.status_code,
        )
        health = client.get("/api/health").json()
        c.check(
            "상태 확인: 유효 데이터 모드 real·외부 모델 꺼짐·지도 = 가져온 지도",
            health["data_mode"] == "real" and health["llm_external"] is False and health["snapshot_id"] == imported,
        )
        c.check(
            "가져온 지도의 샘플은 빈 목록",
            client.get("/api/samples", headers=_bound(second.workspace)).json() == [],
        )

        old = _bound(first.workspace)
        refused = {
            "분석": client.post("/api/analyses", json=thick, headers=old),
            "영향": client.post("/api/impacts", json=thick, headers=old),
            "비서": client.post("/api/assistant/turns", json={"context": CONTEXT, "message": DEMO1}, headers=old),
            "대화": client.get("/api/assistant/conversations/C-x", headers=old),
            "부분 그래프": client.get("/api/graph/view", params={"center": "S-001"}, headers=old),
            "샘플": client.get("/api/samples", headers=old),
            "활성화": client.post(f"/api/snapshots/{default_id}/activate", headers=old),
        }
        c.check(
            "이전 토큰이면 분석·영향·비서·대화·부분 그래프·샘플·활성화 모두 409, 작업 공간 그대로",
            all(r.status_code == 409 for r in refused.values()) and _listing(client).workspace == second.workspace,
            {k: r.status_code for k, r in refused.items()},
        )
        after = client.post("/api/analyses", json=thick, headers=_bound(second.workspace))
        result = AnalysisResult.model_validate(after.json())
        c.check(
            "가져온 지도에서 같은 요청: 응답 머리글 = 새 토큰, 결과의 지도 ID = 가져온 지도",
            after.headers.get(WORKSPACE_HEADER) == second.workspace and result.versions.snapshot_id == imported,
        )
        c.check(
            "가져온 지도의 분석 수치 = 기본 지도(비용 줄·총액·판정·시점·일정, 출처 표기만 다름)",
            _numbers(result) == _numbers(before),
        )
        c.check("머리글이 없으면 대조하지 않음(200)", client.post("/api/analyses", json=thick).status_code == 200)

        third = _activate(client, imported, second.workspace)
        c.check(
            "같은 지도를 다시 켜면 세대·토큰이 바뀌고 이전 토큰은 409(대화 저장소가 새로 시작)",
            third.generation == 3
            and third.workspace != second.workspace
            and client.get("/api/samples", headers=_bound(second.workspace)).status_code == 409,
        )
        back = _activate(client, default_id, third.workspace)
        resampled = client.get("/api/samples", headers=_bound(back.workspace)).json()
        c.check(
            "기본 지도로 돌아가면 샘플이 다시 나옴(합성 모드)",
            back.data_mode is DataMode.SYNTHETIC
            and [s["ecn_id"] for s in resampled] == [s["ecn_id"] for s in samples.json()],
        )
        forth = _activate(client, imported, back.workspace)
        c.check(
            "다른 지도를 갔다 와도(A→B→A) 그 전 토큰은 409",
            forth.active_snapshot_id == imported
            and client.get("/api/samples", headers=_bound(third.workspace)).status_code == 409
            and client.get("/api/samples", headers=_bound(back.workspace)).status_code == 409,
        )

        token = forth.workspace
        unknown = client.post("/api/snapshots/G-0123456789abcdef/activate")
        crafted = client.post("/api/snapshots/..%5Cactive/activate")
        c.check(
            "목록에 없는 지도·형식이 아닌 ID 활성화는 404, 작업 공간 그대로",
            unknown.status_code == 404 and crafted.status_code == 404 and _listing(client).workspace == token,
            (unknown.status_code, crafted.status_code),
        )
        home = _activate(client, default_id, token)
        stored = settings.data_dir / "snapshots" / f"{imported}.json"
        good = stored.read_text(encoding="utf-8")
        stored.write_text(good.replace('"name":"', '"name":"변조 ', 1), encoding="utf-8")
        damaged = client.post(f"/api/snapshots/{imported}/activate", headers=_bound(home.workspace))
        c.check(
            "저장된 지도가 손상됐으면 활성화 422, 작업 공간·활성 기록 그대로",
            damaged.status_code == 422
            and _listing(client).workspace == home.workspace
            and SnapshotStore(settings.data_dir).active() is None,
            damaged.status_code,
        )
        stored.write_text(good, encoding="utf-8")

        exported = client.get(f"/api/snapshots/{imported}/export")
        again = _read(client, exported.content)
        c.check(
            "내보내기: 지정 양식 xlsx, 다시 올리면 같은 지도(같은 파일 이름 → 같은 ID)",
            exported.status_code == 200
            and exported.headers["content-type"].startswith(XLSX)
            and again.info is not None
            and again.info.snapshot_id == imported,
        )
        c.check(
            "목록에 없는 지도 내보내기는 404", client.get("/api/snapshots/G-0123456789abcdef/export").status_code == 404
        )

        _in_flight(c, client, thick, imported)
        final = _listing(client)
        if final.active_snapshot_id != imported:
            _activate(client, imported, final.workspace)  # 재시작 검사: 마지막 활성 = 가져온 지도
    return imported


def _in_flight(c: Checker, client: TestClient, thick: dict[str, Any], imported: str) -> None:
    """분석을 처리하는 중에 지도를 바꿔도 그 요청은 처음 잡은 세대로 끝나고 그렇게 표시된다."""
    start = _listing(client)
    other = next(i.snapshot_id for i in start.items if i.snapshot_id != start.active_snapshot_id)
    entered, release = threading.Event(), threading.Event()
    original = analyze  # 라우트 모듈이 가져다 쓰는 엔진 함수(그 이름을 느린 함수로 바꿔 끼운다)
    box: dict[str, Any] = {}

    def slow(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        release.wait(20)
        return original(*args, **kwargs)

    with mock.patch.object(analyses_route, "analyze", slow):
        worker = threading.Thread(
            target=lambda: box.setdefault(
                "r", client.post("/api/analyses", json=thick, headers=_bound(start.workspace))
            )
        )
        worker.start()
        entered.wait(20)
        switched = client.post(f"/api/snapshots/{other}/activate", headers=_bound(start.workspace))
        release.set()
        worker.join(30)
    response = box.get("r")
    result = AnalysisResult.model_validate(response.json()) if response is not None else None
    c.check(
        "분석 처리 중 전환돼도 응답은 처리한 세대(머리글 = 이전 토큰, 결과 지도 = 이전 지도), 전환은 완료",
        response is not None
        and response.status_code == 200
        and response.headers.get(WORKSPACE_HEADER) == start.workspace
        and result is not None
        and result.versions.snapshot_id == start.active_snapshot_id
        and switched.status_code == 200
        and _listing(client).active_snapshot_id == other,
        None if response is None else response.status_code,
    )


# ---------- 가져오기 상한 ----------


def _limits(c: Checker, root: Path, template: bytes) -> None:
    c.section("가져오기: 크기 상한·형식·동시 읽기")
    app = create_app(_settings(root, "data-limits"))
    with TestClient(app) as client:
        workbook = load_workbook(io.BytesIO(template))
        workbook.remove(workbook["공정"])
        broken = _read(client, _xlsx(workbook))
        c.check(
            "필수 시트(공정)를 뺀 파일: 리포트에 오류, 확정 ID·지도 정보 없음",
            broken.import_id is None
            and broken.info is None
            and any(i.severity == "error" and i.sheet == "공정" for i in broken.summary.issues),
        )
        c.check(
            "엑셀이 아닌 파일·빈 파일은 422",
            _upload(client, b"not an xlsx").status_code == 422 and _upload(client, b"").status_code == 422,
        )
        c.check("20MB를 넘으면 413", _upload(client, bytes(20 * 1024 * 1024 + 1)).status_code == 413)

        def refused(name: str, value: int, phrase: str) -> bool:
            with _limit(workbook_module, name, value):
                response = _upload(client, template)
            return response.status_code == 422 and phrase in str(response.json().get("detail"))

        c.check("압축을 푼 총량 상한을 넘으면 읽기 전에 422", refused("MAX_UNZIPPED_BYTES", 1000, "압축 해제 크기"))
        c.check("시트 수 상한을 넘으면 422", refused("MAX_SHEETS", 3, "쓰지 않는 시트 삭제"))
        c.check("시트 행 상한을 넘으면 그 시트를 말하는 422", refused("MAX_ROWS", 50, "행 초과"))
        c.check("전체 칸 상한을 넘으면 422", refused("MAX_CELLS", 1000, "칸 합계"))
        many = io.BytesIO()
        with zipfile.ZipFile(many, "w") as archive:
            for n in range(workbook_module.MAX_ZIP_ENTRIES + 1):
                archive.writestr(f"x/{n}.xml", "<a/>")
        response = _upload(client, many.getvalue())
        c.check(
            "zip 항목 수 상한을 넘으면 422",
            response.status_code == 422 and "안 항목" in str(response.json().get("detail")),
        )
        wide = load_workbook(io.BytesIO(template))
        wide["블록"].cell(row=2, column=workbook_module.MAX_COLUMNS + 10).value = "멀리 있는 값"
        response = _upload(client, _xlsx(wide))
        c.check(
            "상한 열 뒤에 값이 있으면 버리지 않고 422(값 손실 방지)",
            response.status_code == 422 and "열 뒤에 값 있음" in str(response.json().get("detail")),
        )
        styled = load_workbook(io.BytesIO(template))
        styled["블록"].cell(row=2, column=workbook_module.MAX_COLUMNS + 10).font = Font(bold=True)
        response = _upload(client, _xlsx(styled))
        c.check(
            "상한 열 뒤가 서식만 있는 빈칸이면 잘라 읽음(정상 가져오기: 지정 양식 그대로)",
            response.status_code == 200 and MappingProposal.model_validate(response.json()).exact,
            response.text[:200],
        )
        holder = app.state.workspaces
        assert isinstance(holder, Workspaces)
        with mock.patch.object(holder, "_parsing", threading.BoundedSemaphore(1)) as gate:
            gate.acquire()
            busy = _upload(client, template)
            gate.release()
        c.check("다른 파일을 읽는 중이면 503", busy.status_code == 503, busy.status_code)


# ---------- 유효 데이터 모드 ----------


def _external(c: Checker, root: Path, template: bytes) -> None:
    c.section("유효 데이터 모드: 실데이터 지도로 바꾸면 외부 모델 호출 0")
    fake = FakeModel()
    app = create_app(_settings(root, "data-llm"), llm_factory=lambda _: fake)
    with TestClient(app) as client:
        first = _listing(client)
        turn = client.post(
            "/api/assistant/turns", json={"context": CONTEXT, "message": DEMO1}, headers=_bound(first.workspace)
        )
        unread = client.post(
            "/api/assistant/turns", json={"context": CONTEXT, "message": UNREAD}, headers=_bound(first.workspace)
        )
        called = len(fake.prompts)
        c.check(
            "합성 지도 + 외부 모델: 설명 고르기·다시 쓰기에서 실제로 불림(검사가 호출을 셀 수 있음)",
            first.llm_external and turn.status_code == 200 and unread.status_code == 200 and called >= 2,
            called,
        )
        conversation = turn.json()["conversation_id"]
        preview = _read(client, template)
        second = SnapshotList.model_validate(_confirm(client, preview, first.workspace).json())
        bound = _bound(second.workspace)
        demo = client.post("/api/assistant/turns", json={"context": CONTEXT, "message": DEMO1}, headers=bound)
        hard = client.post("/api/assistant/turns", json={"context": CONTEXT, "message": UNREAD}, headers=bound)
        reused = client.post(
            "/api/assistant/turns",
            json={"conversation_id": conversation, "context": CONTEXT, "message": DEMO1},
            headers=bound,
        )
        stale = client.post(
            "/api/assistant/turns",
            json={"conversation_id": conversation, "context": CONTEXT, "message": DEMO1},
            headers=_bound(first.workspace),
        )
        body = demo.json()
        c.check(
            "실데이터 지도: 데모 1·못 읽는 문장·이전 대화 ID로 보낸 문장 모두 외부 호출 0"
            "(규칙 해석·기본 설명으로 끝까지)",
            len(fake.prompts) == called
            and body.get("state") == "analyzed"
            and body["explanation"]["source"] == "template"
            and hard.status_code == 200
            and reused.status_code == 200,
            (len(fake.prompts), called, demo.status_code),
        )
        c.check(
            "이전 세대 대화: 이전 토큰이면 409, 새 토큰이면 그 대화는 없어 새 대화로 시작",
            stale.status_code == 409 and reused.json()["conversation_id"] != conversation,
        )
        back = _activate(client, first.active_snapshot_id, second.workspace)
        c.check(
            "기본(합성) 지도로 돌아가면 외부 모델을 다시 쓸 수 있음",
            back.llm_external and back.data_mode is DataMode.SYNTHETIC,
        )


# ---------- 재시작 ----------


def _restart(c: Checker, root: Path, default_id: str, imported: str) -> None:
    c.section("재시작: 활성 지도 복구와 복구 실패 사유")
    settings = _settings(root, "data-a")
    with TestClient(create_app(settings)) as client:
        listing = _listing(client)
        c.check(
            "다시 켜면 마지막 활성 지도(가져온 지도)로 시작, 세대 1·새 토큰, 목록 그대로",
            listing.active_snapshot_id == imported
            and listing.generation == 1
            and listing.restore_problem is None
            and [i.snapshot_id for i in listing.items] == [default_id, imported]
            and listing.data_mode is DataMode.REAL,
        )
        _activate(client, default_id, listing.workspace)
    with TestClient(create_app(settings)) as client:
        c.check("기본 지도로 되돌린 뒤 다시 켜면 기본 지도", _listing(client).active_snapshot_id == default_id)

    def started(prepare: str) -> SnapshotList:
        data = root / f"data-restore-{prepare}"
        store = SnapshotStore(data)
        source = SnapshotStore(settings.data_dir)
        store.save(source.load(imported), source.info(imported))
        store.set_active(imported)
        if prepare == "pointer":
            (data / "active.json").write_text("{ 깨짐", encoding="utf-8")
        elif prepare == "missing":
            store.set_active("G-0123456789abcdef")
        elif prepare == "damaged":
            path = data / "snapshots" / f"{imported}.json"
            path.write_text(path.read_text(encoding="utf-8").replace('"name":"', '"name":"변조 ', 1), encoding="utf-8")
        elif prepare == "pointer-bytes":
            (data / "active.json").write_bytes(b'{"snapshot_id": "\xff"}')
        elif prepare == "snapshot-bytes":
            (data / "snapshots" / f"{imported}.json").write_bytes(b"\xff\xfe")
        elif prepare == "info-bytes":
            (data / "snapshots" / f"{imported}.info.json").write_bytes(b"\xff\xfe")
        elif prepare == "null":
            (data / "active.json").write_text("null", encoding="utf-8")
        with TestClient(create_app(replace(settings, data_dir=data))) as client:
            return _listing(client)

    outcomes = {p: started(p) for p in ("pointer", "missing", "damaged")}
    c.check(
        "활성 기록이 깨졌거나·없는 지도를 가리키거나·지도가 손상됐으면 기본 지도로 시작하고 사유를 알림",
        all(o.active_snapshot_id == default_id and o.restore_problem for o in outcomes.values()),
        {p: (o.active_snapshot_id, o.restore_problem) for p, o in outcomes.items()},
    )
    encoded = {p: started(p) for p in ("pointer-bytes", "snapshot-bytes", "info-bytes")}
    c.check(
        "글자 인코딩이 깨진 활성 기록·활성 지도·그 정보 파일이어도 서버가 시작되고 기본 지도 + 사유(목록도 동작)",
        all(o.active_snapshot_id == default_id and o.restore_problem for o in encoded.values())
        and [i.snapshot_id for i in encoded["info-bytes"].items] == [default_id],
        {p: (o.active_snapshot_id, o.restore_problem) for p, o in encoded.items()},
    )
    bare = started("null")
    problems = [o.restore_problem or "" for o in (*outcomes.values(), *encoded.values(), bare)]
    c.check(
        "사유는 사람이 읽는 말(예외 클래스 이름 없음) — active.json에 null만 적으면 기본 지도로 시작하고 맞는 형식"
        '({"snapshot_id": null})을 알려 줌(점검 D-5)',
        bare.active_snapshot_id == default_id
        and '{"snapshot_id": null}' in (bare.restore_problem or "")
        and not any("Error" in p for p in problems),
        problems,
    )


# ---------- 보관소(시계·실패 주입) ----------


class _Graph(MemoryGraphStore):
    """save를 실패하게 바꿀 수 있는 그래프 저장소(전환 중 실패 흉내)."""

    def __init__(self) -> None:
        super().__init__()
        self.broken = False

    def save(self, snapshot: GraphSnapshot) -> None:
        if self.broken:
            raise RuntimeError("그래프 저장소에 쓰지 못함")
        super().save(snapshot)


def _holder(c: Checker, root: Path, template: bytes) -> None:
    c.section("작업 공간 보관소: 확정 대기 만료·개수, 전환 실패 시 그대로")
    settings = _settings(root, "data-holder")
    clock = [0.0]
    graph = _Graph()
    holder = Workspaces(
        AppContext.load(settings), graph, None, SnapshotStore(settings.data_dir), monotonic=lambda: clock[0]
    )
    holder.start()

    def staged() -> tuple[str, int]:
        proposal = holder.stage(FILE, template)
        preview = holder.submit(
            proposal.import_id, MappingSubmission(version=proposal.version, mapping=mapping_of(proposal))
        )
        assert preview.version is not None and preview.info is not None
        return proposal.import_id, preview.version

    expired, expired_version = staged()
    clock[0] += PENDING_TTL_S + 1
    c.check(
        "30분이 지난 가져오기는 확정·다시 읽기 모두 없음(404)",
        c.raises(lambda: holder.confirm(expired, expired_version, None), NotFound)
        and c.raises(
            lambda: holder.submit(
                expired, MappingSubmission(version=expired_version, mapping=mapping_of(holder.stage(FILE, template)))
            ),
            NotFound,
        ),
    )
    with mock.patch.object(pending_imports_module, "MAX_PENDING", 2):
        imports = [staged() for _ in range(3)]
    (oldest, oldest_version), (newest, version) = imports[0], imports[-1]
    c.check(
        "확정을 기다리는 가져오기는 최근 것만 남음(오래된 것부터 버림)",
        c.raises(lambda: holder.confirm(oldest, oldest_version, None), NotFound),
    )
    switched = holder.confirm(newest, version, None)
    before = holder.current
    pointer = SnapshotStore(settings.data_dir).active()
    graph.broken = True
    failed = c.raises(lambda: holder.activate(holder.default_snapshot().snapshot_id, None), RuntimeError)
    c.check(
        "전환 중 실패(그래프 저장소)하면 이전 세대·활성 기록 그대로",
        failed
        and holder.current is before
        and before is switched
        and SnapshotStore(settings.data_dir).active() == pointer == switched.snapshot.snapshot_id,
    )
    graph.broken = False

    # 확정 응답을 잃은 화면의 재시도
    stale = "G-0000000000000000.x.1"
    c.check(
        "확정은 토큰을 먼저 대조: 옛 토큰이면 없는 가져오기여도 409(화면이 목록을 다시 읽게)",
        c.raises(lambda: holder.confirm("없는-가져오기", version, stale), StaleWorkspace)
        and c.raises(lambda: holder.confirm(newest, version, stale), StaleWorkspace),
    )
    again = holder.confirm(newest, version, switched.token)
    c.check("같은 가져오기를 같은 버전·지금 토큰으로 다시 확정하면 그대로(새 세대 없음, 대화 유지)", again is switched)
    c.check(
        "확정한 가져오기를 다른 버전으로 다시 확정하면 409(import_changed)",
        c.raises(lambda: holder.confirm(newest, version + 1, switched.token), ImportChanged),
    )
    home = holder.activate(holder.default_snapshot().snapshot_id, switched.token)
    back = holder.confirm(newest, version, home.token)
    c.check(
        "다른 지도로 바꾼 뒤 같은 가져오기를 다시 확정하면 그 지도로 다시 바꿈",
        back.snapshot.snapshot_id == switched.snapshot.snapshot_id and back.generation == home.generation + 1,
    )
    clock[0] += PENDING_TTL_S + 1
    c.check(
        "확정한 가져오기도 30분이 지나면 잊음(404)",
        c.raises(lambda: holder.confirm(newest, version, back.token), NotFound),
    )

    # 확정이 버전을 대조한 뒤 저장하는 사이에 덮어쓰기가 끼어들면 최신 수정이 사라짐
    # → 대조·저장·전환·대기 항목 제거를 가져오기 잠금 안에서. 끼어든 덮어쓰기는 확정이 끝난 뒤 '없는 가져오기'가 된다
    racing_id, racing_version = staged()
    store_save = holder._store.save
    outcome: dict[str, object] = {}

    def slow_save(*args: Any, **kwargs: Any) -> Any:
        worker = threading.Thread(
            target=lambda: outcome.setdefault(
                "propose",
                _attempt(
                    lambda: holder.propose(
                        racing_id,
                        MappingOverrides(
                            version=racing_version, sheets=(SheetOverride(file_sheet="재고", template=None),)
                        ),
                    )
                ),
            )
        )
        worker.start()
        worker.join(1.0)  # 잠금 밖이면 이 사이에 덮어쓰기가 끝나 버전이 오른다
        outcome["worker"] = worker
        return store_save(*args, **kwargs)

    with mock.patch.object(holder._store, "save", slow_save):
        confirmed_now = holder.confirm(racing_id, racing_version, holder.current.token if holder.current else None)
    worker = outcome.get("worker")
    if isinstance(worker, threading.Thread):
        worker.join(30)
    c.check(
        "확정 중에 들어온 덮어쓰기는 확정이 끝날 때까지 기다렸다가 '없는 가져오기'(404) — 옛 버전 확정이 새 수정을"
        " 조용히 지우지 않음",
        confirmed_now.snapshot.snapshot_id is not None and isinstance(outcome.get("propose"), NotFound),
        outcome.get("propose"),
    )

    # 읽는 사이 상태 버전이 바뀌면(덮어쓰기·다른 제출) 그 읽기 결과는 확정할 수 없다
    # (늦게 끝난 읽기가 새 상태를 덮지 않게)
    proposal = holder.stage(FILE, template)
    real_build = build_module.build

    def racing(*args: Any, **kwargs: Any) -> Any:
        holder._imports._pending[proposal.import_id].version += 1  # 읽는 동안 다른 곳에서 상태가 바뀜
        return real_build(*args, **kwargs)

    with mock.patch.object(workspace_module, "build", racing):
        late = holder.submit(
            proposal.import_id, MappingSubmission(version=proposal.version, mapping=mapping_of(proposal))
        )
    c.check(
        "읽는 사이 버전이 바뀐 읽기 결과는 오류가 없어도 확정할 수 없음(409 import_changed)",
        late.info is not None
        and late.version is not None
        and c.raises(lambda: holder.confirm(proposal.import_id, late.version or 0, None), ImportChanged),
    )


# ---------- 열 확인(제안·덮어쓰기·확정 매핑·상태 버전) ----------


def _review(c: Checker, root: Path, snapshot: GraphSnapshot) -> None:
    c.section("가져오기: 열 확인(제안·덮어쓰기·확정 매핑·상태 버전)")
    variant = next(v for v in gate_variants(snapshot) if v.name == "V1")
    app = create_app(_settings(root, "data-review"))
    with TestClient(app) as client:
        first = _listing(client)
        staged = _upload(client, variant.data, "V1.xlsx")
        proposal = MappingProposal.model_validate(staged.json())
        parts = next(sheet for sheet in proposal.template if sheet.key == "parts")
        thickness = next(field for field in parts.columns if field.key == "thickness_mm")
        c.check(
            "흔한 변형(V1) 올리기: 개입 전 제안 = 정답 매핑, 확인할 것이 있음, "
            "양식 정의에 원본 단위 고르기(m → mm ×1000)",
            staged.status_code == 200
            and not proposal.exact
            and proposal.pending > 0
            and not same_mapping(mapping_of(proposal), variant.truth)
            and {(u.unit, u.factor) for u in thickness.units} >= {("m", 1000.0), ("cm", 10.0), ("mm", 1.0)}
            and bool(proposal.calibration)
            and _listing(client) == first,
            staged.text[:200],
        )
        decided = [col for sheet in proposal.sheets for col in sheet.columns if col.answer is not None]
        c.check(
            "판단 열은 판단 계층 답(확률·되묻기 집합·경로)을 싣고, 자동 진행 열만 auto",
            bool(decided)
            and all(col.auto == (col.answer.route.value == "auto") for col in decided if col.answer)
            and any(not col.auto for col in decided),
        )
        mapping_url = f"/api/imports/{proposal.import_id}/mapping"
        confirm_url = f"/api/imports/{proposal.import_id}/confirm"
        proposal_url = f"/api/imports/{proposal.import_id}/proposal"
        good_response = _submit(client, proposal)
        good = ImportPreview.model_validate(good_response.json())
        stale = _submit(client, proposal)
        c.check(
            "제안 그대로 읽으면 오류 없이 지도(상태 버전 2), 옛 버전으로 다시 보내면 409 import_changed(지금 버전 2)",
            good.info is not None
            and good.version == 2
            and stale.status_code == 409
            and stale.json()["detail"]["code"] == "import_changed"
            and stale.json()["detail"]["version"] == 2,
            stale.text[:200],
        )
        stock = next(sheet for sheet in proposal.sheets if sheet.template == "stock")
        override = {"version": 2, "sheets": [{"file_sheet": stock.file_sheet, "template": None}]}
        skipped = MappingProposal.model_validate(client.post(proposal_url, json=override).json())
        c.check(
            "덮어쓰기(재고 시트 → 읽지 않음): 다시 제안(상태 버전 3), 그 시트는 읽지 않음·확실",
            skipped.version == 3
            and next(s for s in skipped.sheets if s.file_sheet == stock.file_sheet).template is None
            and next(s for s in skipped.sheets if s.file_sheet == stock.file_sheet).certain,
        )
        old = client.post(confirm_url, json={"version": good.version}, headers=_bound(first.workspace))
        unread = client.post(confirm_url, json={"version": 3}, headers=_bound(first.workspace))
        c.check(
            "덮어쓰기 뒤에는 그 전 읽기 결과(버전 2)로도, 읽지 않은 버전(3)으로도 확정할 수 없음(409), "
            "활성 지도 그대로",
            old.status_code == 409
            and old.json()["detail"]["code"] == "import_changed"
            and unread.status_code == 409
            and _listing(client).workspace == first.workspace,
        )
        mapping = mapping_of(skipped).model_dump(mode="json")
        parts_sheet = next(s for s in mapping["sheets"] if s["template"] == "parts")
        keyed = [col for col in parts_sheet["columns"] if col["key"]]
        keyed[1]["key"] = keyed[0]["key"]  # 같은 항목에 두 열
        failed = ImportPreview.model_validate(client.post(mapping_url, json={"version": 3, "mapping": mapping}).json())
        refused = client.post(confirm_url, json={"version": 4}, headers=_bound(first.workspace))
        c.check(
            "오류가 있는 읽기(같은 항목에 두 열)는 버전 4로 리포트만, 확정 409",
            failed.info is None and failed.version == 4 and not failed.summary.ok and refused.status_code == 409,
        )
        fixed = MappingProposal.model_validate(
            client.post(
                proposal_url, json={"version": 4, "sheets": [{"file_sheet": stock.file_sheet, "template": "stock"}]}
            ).json()
        )
        final = ImportPreview.model_validate(_submit(client, fixed).json())
        switched = client.post(confirm_url, json={"version": final.version}, headers=_bound(first.workspace))
        c.check(
            "다시 재고를 읽게 고친 제안(버전 5) → 읽기(버전 6) → 그 버전으로 확정하면 전환",
            fixed.version == 5
            and final.version == 6
            and final.info is not None
            and switched.status_code == 200
            and SnapshotList.model_validate(switched.json()).active_snapshot_id == final.info.snapshot_id,
        )

        second = _upload(client, variant.data, "V1.xlsx")
        again = MappingProposal.model_validate(second.json())
        url = f"/api/imports/{again.import_id}/proposal"
        sheet = again.sheets[0].file_sheet
        optional = next(s.file_sheet for s in again.sheets if s.template == "stock")

        def bad(body: dict[str, Any]) -> int:
            return int(client.post(url, json={"version": again.version, "sheets": [body]}).status_code)

        rejected = {
            "없는 시트": bad({"file_sheet": "없는 시트", "template": None}),
            "모르는 양식 시트": bad({"file_sheet": sheet, "template": "없는양식"}),
            "빈 머리글 행": bad({"file_sheet": sheet, "template": "ships", "header_rows": [999]}),
            "떨어진 두 행": bad({"file_sheet": sheet, "template": "ships", "header_rows": [1, 3]}),
        }
        c.check(
            "잘못된 덮어쓰기(없는 시트·모르는 양식 시트·빈 머리글 행·떨어진 두 행)는 422, 상태 버전 그대로",
            all(code == 422 for code in rejected.values())
            and client.post(
                url, json={"version": 1, "sheets": [{"file_sheet": optional, "template": None}]}
            ).status_code
            == 200,
            rejected,
        )
        stale_override = client.post(url, json={"version": 99, "sheets": [{"file_sheet": sheet, "template": None}]})
        c.check(
            "옛(또는 없는) 버전으로 보낸 덮어쓰기는 409 import_changed(지금 버전을 알려 줌)",
            stale_override.status_code == 409
            and stale_override.json()["detail"]["code"] == "import_changed"
            and stale_override.json()["detail"]["version"] == 2,
            stale_override.text[:200],
        )
        latest = MappingProposal.model_validate(
            client.post(url, json={"version": 2, "sheets": [{"file_sheet": optional, "template": None}]}).json()
        )
        mine = ImportPreview.model_validate(_submit(client, latest).json())
        other_tab = MappingProposal.model_validate({**latest.model_dump(mode="json"), "version": mine.version})
        theirs = ImportPreview.model_validate(_submit(client, other_tab).json())
        listing = _listing(client)
        old_result = client.post(
            f"/api/imports/{again.import_id}/confirm",
            json={"version": mine.version},
            headers=_bound(listing.workspace),
        )
        c.check(
            "두 창: 내 읽기(버전 n) 뒤 다른 창이 다시 읽었으면(n+1, 성공) 내 버전으로는 확정할 수 없음(409)"
            " — 다른 매핑의 지도를 내 결과로 알고 바꾸지 않게",
            mine.info is not None
            and theirs.info is not None
            and theirs.version == (mine.version or 0) + 1
            and old_result.status_code == 409
            and old_result.json()["detail"]["code"] == "import_changed"
            and _listing(client).workspace == listing.workspace,
            old_result.text[:200],
        )
        c.check(
            "없는 가져오기의 제안·읽기는 404",
            client.post("/api/imports/없는-가져오기/proposal", json=override).status_code == 404
            and client.post(
                "/api/imports/없는-가져오기/mapping", json={"version": 1, "mapping": {"sheets": []}}
            ).status_code
            == 404,
        )
    _ = (SheetOverride, MappingOverrides)
