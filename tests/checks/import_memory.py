"""열 매핑 기억 API(docs/input.md(엑셀 양식) 4절): 확정한 매핑을 같은 모양의 다음 파일에 제안으로 싣고, 제목 행 단위만
바뀌어도 싣지 않으며, 관리자가 지우면 처음부터. 로그인은 끈다(권한은 auth_api 표)."""

from __future__ import annotations

import io
import tempfile
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

from harness import Checker
from openpyxl import load_workbook

from ripple.api.app import create_app
from ripple.config.settings import Settings
from ripple.contracts.ingest import MappingProposal
from ripple.contracts.workspace import WORKSPACE_HEADER
from ripple.generator.build import generate
from ripple.generator.io import load_config, write_outputs
from ripple.ingest.export import to_bytes
from ripple.ingest.proposal import mapping_of

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

FILE = "plant.xlsx"
OCTET = {"Content-Type": "application/octet-stream"}


def _stage(client: TestClient, data: bytes) -> MappingProposal:
    response = client.post(f"/api/imports?file_name={FILE}", content=data, headers=OCTET)
    return MappingProposal.model_validate(response.json())


def _titled(data: bytes, note: str) -> bytes:
    """'호선' 시트 맨 위에 제목 행(단위 안내)을 넣은 파일."""
    book = load_workbook(io.BytesIO(data))
    sheet = book["호선"]
    sheet.insert_rows(1)
    sheet["A1"] = note
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def run(c: Checker) -> None:
    generated = generate(load_config())
    data = _titled(to_bytes(generated.snapshot), "호선 목록 (단위: 원)")
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        settings = replace(
            Settings.from_env({"RIPPLE_AUTH": "off"}),
            snapshot_path=root / "synthetic" / "snapshot.json",
            data_dir=root / "data",
        )
        with TestClient(create_app(settings)) as client:
            _flow(c, client, data)


def _flow(c: Checker, client: TestClient, data: bytes) -> None:
    c.section("열 매핑 기억: 확정 → 같은 모양 파일에 제안")
    first = _stage(client, data)
    c.check("처음 올린 파일에는 기억한 매핑이 없음", first.remembered is None)
    mapping = mapping_of(first)
    body: dict[str, Any] = {"version": first.version, "mapping": mapping.model_dump(mode="json")}
    preview = client.post(f"/api/imports/{first.import_id}/mapping", json=body).json()
    token = client.get("/api/snapshots").json()["workspace"]
    confirmed = client.post(
        f"/api/imports/{first.import_id}/confirm",
        json={"version": preview["version"]},
        headers={WORKSPACE_HEADER: token},
    )
    c.check("확정 성공", confirmed.status_code == 200, confirmed.text[:200])
    again = _stage(client, data)
    c.check(
        "같은 파일을 다시 올리면 확정한 매핑과 그 파일 이름이 제안에 실림",
        again.remembered == mapping and again.remembered_from == FILE,
    )
    changed = _stage(client, _titled(to_bytes(generate(load_config()).snapshot), "호선 목록 (단위: 천원)"))
    c.check("제목 행 단위만 원 → 천원으로 바뀌면 싣지 않음(금액 1,000배 오독 방지)", changed.remembered is None)
    cleared = client.delete("/api/imports/mappings")
    c.check(
        "관리자가 지우면 같은 파일도 처음부터 열 확인",
        cleared.status_code == 204 and _stage(client, data).remembered is None,
    )
