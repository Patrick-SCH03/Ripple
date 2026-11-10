"""합성 NCR 묶음(docs/records.md '합성 NCR', ripple/cases/ncr.py)과 요약 API(GET /api/ncrs/summary).

- 같은 설정·씨앗 = 같은 묶음(기준일이 바뀌어도 같음), 씨앗이 다르면 다름.
- 모든 문장에 '합성 묶음(시연)', 건수만(비율·금액 없음), 설계변경 번호를 가리키지 않음(시연 목록과 겹치지 않음).
- 실데이터 모드는 빈 묶음 + 이유, 요약 available=false.
- 사전 점검 항목의 '같은 유형 합성 NCR n건' = 이 묶음의 유형별 건수(분석 API 응답까지).
"""

from __future__ import annotations

import re
import tempfile
import warnings
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from harness import Checker

from ripple.api.app import create_app
from ripple.api.ncr import ncr_counts, ncr_summary
from ripple.cases import NcrBundle, load_ncr_settings, ncr_bundle
from ripple.cases.ncr import NCR_TYPES
from ripple.config.settings import Settings
from ripple.contracts.domain import BlockStage, DataMode
from ripple.contracts.ncr import SYNTHETIC_LABEL, NcrRecord, NcrSummary, NcrTypeCount
from ripple.contracts.result import AnalysisResult
from ripple.generator.build import Generated, generate
from ripple.generator.config import GeneratorConfig
from ripple.generator.io import load_config, write_outputs

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

UNSHOWN = re.compile(r"%|만원|억원|\d원|ECN-")  # 비율·금액·설계변경 번호


def run(c: Checker) -> None:
    config = load_config()
    bundle = ncr_bundle(config, DataMode.SYNTHETIC, load_ncr_settings())
    _bundle(c, config, bundle)
    _real(c, config)
    _api(c, generate(config), bundle)


def _bundle(c: Checker, config: GeneratorConfig, bundle: NcrBundle) -> None:
    c.section("합성 NCR 묶음: 결정적 · 합성 표기 · 건수만")
    settings = load_ncr_settings()
    later = config.model_copy(update={"scenario_date": config.scenario_date + timedelta(days=7)})
    other = config.model_copy(update={"seed": config.seed + 1})
    c.check(
        "같은 설정·씨앗이면 같은 묶음, 기준일이 바뀌어도 같음(실시간 시연 세계), 씨앗이 다르면 다름",
        bundle == ncr_bundle(config, DataMode.SYNTHETIC, settings)
        and bundle == ncr_bundle(later, DataMode.SYNTHETIC, settings)
        and bundle.records != ncr_bundle(other, DataMode.SYNTHETIC, settings).records,
    )
    ids = [r.ncr_id for r in bundle.records]
    c.check(
        f"건수 = 설정({settings.count}건), 번호 NCR-S-0001부터 빠짐없이, 늘 synthetic",
        ids == [f"NCR-S-{n:04d}" for n in range(1, settings.count + 1)] and all(r.synthetic for r in bundle.records),
        ids[:3],
    )
    texts = [t for r in bundle.records for t in (r.cause, r.action)]
    c.check("모든 문장(원인·조치)에 '합성 묶음(시연)'", all(SYNTHETIC_LABEL in t for t in texts))
    c.check(
        "비율·금액·설계변경 번호가 없음(건수만, 시연 목록·과거 사례의 설계변경과 겹치지 않음)",
        not any(UNSHOWN.search(t) for t in texts),
        [t for t in texts if UNSHOWN.search(t)][:2],
    )
    crews = {t.name for t in config.crews.teams}
    c.check(
        "조치 수행 주체는 생성기 작업반 이름 또는 직영, 탑재 단계에서 발견한 건은 직영",
        all(r.performer in crews | {"직영"} for r in bundle.records)
        and all(r.performer == "직영" for r in bundle.records if r.found_stage is BlockStage.ERECTED)
        and any(r.performer in crews for r in bundle.records),
    )
    counts = bundle.counts()
    c.check(
        "유형별 건수 합 = 묶음 건수, 사전 점검 6종이 모두 한 건 이상",
        sum(counts.values()) == len(bundle.records) and all(counts[f"P-0{n}"] > 0 for n in range(1, 7)),
        counts,
    )
    summary = bundle.summary(5)
    c.check(
        "요약: 유형 8종 순서대로(0건 유형 포함) · 총 건수 · 최근 5건은 번호 큰 순",
        [x.ncr_type for x in summary.counts] == list(NCR_TYPES)
        and summary.total == len(bundle.records)
        and [r.ncr_id for r in summary.recent] == sorted(ids, reverse=True)[:5]
        and summary.available
        and summary.label == SYNTHETIC_LABEL,
    )
    first = bundle.records[0].model_dump()
    c.check(
        "계약: '합성 묶음(시연)'이 없는 문장은 거부",
        c.raises(lambda: NcrRecord.model_validate({**first, "cause": "취부 위치가 어긋났어요."})),
    )


def _real(c: Checker, config: GeneratorConfig) -> None:
    c.section("합성 NCR 묶음: 실데이터 모드 차단")
    real = ncr_bundle(config, DataMode.REAL)
    summary = real.summary(5)
    c.check(
        "실데이터 모드: 묶음을 만들지 않음(빈 묶음 + 이유), 요약 available=false · 건수 0",
        not real.records
        and not real.synthetic
        and real.counts() == {}
        and not summary.available
        and summary.total == 0
        and not summary.recent
        and bool(summary.reason),
        summary,
    )
    one = NcrTypeCount(ncr_type="P-01", name="설치 시점", count=1)
    c.check(
        "계약: 묶음이 없는데 건수가 있거나 이유가 없는 요약은 거부",
        c.raises(lambda: NcrSummary(available=False, synthetic=False, reason="x", total=1, counts=(one,)))
        and c.raises(lambda: NcrSummary(available=False, synthetic=False)),
    )


def _api(c: Checker, generated: Generated, bundle: NcrBundle) -> None:
    c.section("합성 NCR 요약 API · 분석 응답의 같은 유형 합성 NCR 건수")
    c.check(
        "api/ncr.py: 실데이터면 사전 점검 건수 None · 요약 빈 묶음, 합성이면 이 묶음의 건수",
        ncr_counts(DataMode.REAL) is None
        and not ncr_summary(DataMode.REAL).available
        and ncr_counts(DataMode.SYNTHETIC) == bundle.counts(),
    )
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        write_outputs(generated, root / "synthetic")
        settings = replace(
            Settings.from_env({"RIPPLE_AUTH": "off"}),  # 권한 행렬은 tests/checks/auth_api.py
            snapshot_path=root / "synthetic" / "snapshot.json",
            data_dir=root / "data",
        )
        with TestClient(create_app(settings)) as client:
            got = client.get("/api/ncrs/summary")
            two = client.get("/api/ncrs/summary", params={"recent": 2})
            c.check(
                "GET /api/ncrs/summary(합성 작업 공간): 200, 요약 = 묶음 요약(설정의 최근 건수), recent=2면 2건",
                got.status_code == 200
                and NcrSummary.model_validate(got.json()) == bundle.summary(load_ncr_settings().recent)
                and len(two.json()["recent"]) == 2,
                got.status_code,
            )
            c.check(
                "recent는 1~20(넘으면 422)",
                client.get("/api/ncrs/summary", params={"recent": 99}).status_code == 422,
            )
            samples = client.get("/api/samples").json()
            pipe = next(s for s in samples if s["request"]["change"]["ecn_id"] == "ECN-D-0043")
            response = client.post("/api/analyses", json=pipe["request"])
            result = AnalysisResult.model_validate(response.json())
            counts = bundle.counts()
            c.check(
                "분석 응답(ECN-D-0043)의 사전 점검마다 같은 유형 합성 NCR 건수 = 묶음의 유형별 건수",
                response.status_code == 200
                and bool(result.prechecks)
                and all(i.ncr_count == counts[i.rule_id] for i in result.prechecks),
                [(i.rule_id, i.ncr_count) for i in result.prechecks],
            )
