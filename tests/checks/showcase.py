"""소개 화면 예시의 성질: 저장된 web/src/pages/landing/example.json이 지금 엔진 결과와 같고,
그림 카드가 총액을 빠짐없이 나누며, 그림 아래 번호 설명이 쓰는 값이 제품 화면과 같은 뜻인지
(결재함 '미루면'·결정 기한 카드), 판단 요약 첫 줄(추가 공수 + 추가 재료비 = 총변경비용)과 중량 변화가 결과 필드
그대로인지, 그림 파일 크기가 captures.ts와 맞고 쓰지 않는 그림이 남지 않으며 3D 반복 영상이 상한 안인지.

그림(web/public/landing) 속 숫자가 이 파일과 같은지는 화면 검사(web/src/pages/landing/captures.test.ts)가
본다 — 엔진이 바뀌어 이 파일을 다시 만들면 그 검사가 실패해 그림을 다시 찍으라고 알린다
(docs/operations.md(서비스) 3절 '그림 다시 찍기')."""

from __future__ import annotations

import json
import re
import struct
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from harness import Checker

from ripple.api.showcase import SHOWCASE_PATH, analyze_showcase, render_showcase
from ripple.config.settings import PROJECT_ROOT
from ripple.contracts.result import AnalysisResult
from ripple.records.recorded import curve_point, delay_cost
from scripts.export_showcase import showcase_document, synthetic_context


def run(c: Checker) -> None:
    c.section("소개 화면 예시")
    with tempfile.TemporaryDirectory() as folder:
        context = synthetic_context(Path(folder))
        showcase = showcase_document(context)
        result = analyze_showcase(context).result
    saved = PROJECT_ROOT / SHOWCASE_PATH
    c.check(
        "저장된 예시가 지금 엔진 결과와 같음(다르면 scripts/export_showcase.py로 다시 만들기)",
        saved.exists() and saved.read_text(encoding="utf-8") == render_showcase(showcase),
    )
    _check_cost(c, showcase, result)
    nodes = showcase["nodes"]
    keys = {n["key"] for n in nodes}
    c.check("두 번째 고리 카드의 부모는 첫 고리 카드", all(n["parent"] is None or n["parent"] in keys for n in nodes))
    parted = showcase["change"]["amount"] + sum(n["amount"] for n in nodes)
    c.check(
        "바뀌는 부재 + 카드 금액 합 = 총변경비용(그림이 빠뜨린 비용 줄 없음)",
        parted == showcase["total"]["value"],
        (parted, showcase["total"]["value"]),
    )
    c.check(
        "카드 수와 영향 수가 맞음(묶은 카드는 count만큼)",
        sum(n["count"] for n in nodes) <= showcase["impact_count"],
    )
    c.check(
        "화면이 쓰는 값이 있음(판정 이유·결정 기한·다음 날 추가손실·이유 줄·출구 지연)",
        bool(showcase["verdict"]["reasons"])
        and showcase["deadline"] is not None
        and showcase["delay"] is not None
        and showcase["step_up"] is not None
        and showcase["deadline_exit_days"] is not None,
    )
    late = delay_cost(result)
    deadline = result.timing.deadline.last_day
    c.check(
        "다음 날 추가손실(delay) = 결재함 '미루면' 값(records.delay_cost — 결정 기한 다음 날 곡선 대표값)",
        late is not None and showcase["delay"] == {"on": late[1].isoformat(), "loss": late[0]},
        (showcase["delay"], late),
    )
    c.check(
        "'미루면' 날 = 결정 기한 다음 날 = 이유 줄(step_up)이 바뀌는 날",
        showcase["delay"]["on"] == (deadline + timedelta(days=1)).isoformat() == showcase["step_up"]["on"],
        (showcase["delay"]["on"], deadline, showcase["step_up"]["on"]),
    )
    step = showcase["step_up"]
    c.check(
        "다음 날 총 추가손실 ≥ 이유 줄 하나의 증가분(번호 설명이 줄 하나의 값을 총액처럼 쓰지 않게)",
        showcase["delay"]["loss"] >= step["after"] - step["before"] > 0,
        (showcase["delay"]["loss"], step["after"] - step["before"]),
    )
    at_deadline = curve_point(result.timing.curve, deadline)
    as_of = curve_point(result.timing.curve, result.request.as_of)
    zone = showcase["zone_exit"]
    c.check(
        "출구 지연 기준일 → 결정 기한 = 곡선 값(결정 기한 카드 '늦출수록 출구 지연 늘어남'과 같은 수)",
        at_deadline is not None
        and as_of is not None
        and showcase["deadline_exit_days"] == at_deadline.max_exit_delay_days
        and (zone["delay_days"] if zone else 0) == as_of.max_exit_delay_days,
        (zone, showcase["deadline_exit_days"]),
    )
    json.loads(render_showcase(showcase))  # 저장 형식이 JSON으로 다시 읽힘
    _check_pictures(c)


def _check_cost(c: Checker, showcase: dict[str, Any], result: AnalysisResult) -> None:
    """판단 요약 첫 줄 값(추가 공수·추가 재료비)과 중량 변화가 결과 필드 그대로이고,
    공수 + 재료비 + 지체상금 = 총변경비용."""
    cost, split = showcase["cost"], result.cost_split
    c.check("예시 분석에 비용 구분이 있음(계약 1.35.0)", split is not None)
    if split is None:
        return
    c.check(
        "추가 공수·추가 재료비 = 결과 cost_split(새 계산 없음)",
        cost["labor"]["value"] == split.labor.value
        and cost["material"]["value"] == split.material.value
        and cost["labor_hours"]["value"] == split.labor_hours.value,
        (cost["labor"], cost["material"], cost["labor_hours"]),
    )
    c.check(
        "공수 + 재료비 + 지체상금 = 총변경비용(소개 화면 '총변경비용 = 공수 + 재료비'가 맞음)",
        cost["labor"]["value"] + cost["material"]["value"] + cost["damages"] == showcase["total"]["value"],
        (cost["labor"]["value"], cost["material"]["value"], cost["damages"], showcase["total"]["value"]),
    )
    parts = (cost["material_diff"] or 0) + (cost["purchase"] or 0)
    c.check("자재 차이 + 구매 = 추가 재료비", parts == cost["material"]["value"], (parts, cost["material"]["value"]))
    c.check("공수 작업 구분이 있음(재작업·용접·가공·도면 중)", bool(cost["works"]))
    weight = showcase["weight"]
    c.check(
        "중량 변화 = 결과 weight_change 합계(새 − 원래)",
        weight is not None
        and result.weight_change is not None
        and weight["delta_t"] == result.weight_change.delta_t
        and abs(weight["after_t"] - weight["before_t"] - weight["delta_t"]) < 1e-5,
        weight,
    )


CAPTURES = PROJECT_ROOT / "web" / "src" / "pages" / "landing" / "captures.ts"
PUBLIC = PROJECT_ROOT / "web" / "public"
SHOT = re.compile(r"src: '/landing/([\w-]+)',\s*width: (\d+),\s*height: (\d+),(?:\s*scales: \[([\d, ]+)\],)?")


def image_size(path: Path) -> tuple[int, int] | None:
    """PNG·WebP 머리에서 가로·세로(픽셀). 모르는 형식이면 None."""
    head = path.read_bytes()[:32]
    if head[1:4] == b"PNG":
        width, height = struct.unpack(">II", head[16:24])
        return width, height
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    kind = head[12:16]
    if kind == b"VP8X":
        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
    if kind == b"VP8 ":
        width, height = struct.unpack("<HH", head[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L":
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


VIDEO = re.compile(r"/landing/([\w-]+)\.(webm|mp4)\b")
# 반복 영상 한 개 상한(바이트): 3D 절 판 최대 폭 1600px를 배율 2 화면에서도 늘리지 않게 3200×1800 · 30fps로 만든
# 실측(webm 약 0.73MB · mp4 약 0.98MB)의 약 2배. 다시 찍어 크게 불어나면 잡는다.
# 절이 가까이 올 때만 받는다(첫 화면 무게 밖).
VIDEO_LIMIT = 2_000_000


def _check_pictures(c: Checker) -> None:
    """그림 파일 크기 = captures.ts의 1배 크기, n배 그림 = 정확히 n배(강조 테두리 자리가 그림과 어긋나지 않게 — 배율은
    captures.ts scales, 없으면 1·2배). 쓰지 않는 그림·배율 파일이 없고, 반복 영상은 파일이 있고 상한 안."""
    text = CAPTURES.read_text(encoding="utf-8")
    shots = SHOT.findall(text)
    c.check("captures.ts의 그림 14장", len(shots) == 14, len(shots))
    expected = {
        f"{name}.webp" if scale == 1 else f"{name}@{scale}x.webp"
        for name, _w, _h, scales in shots
        for scale in _scales(scales)
    }
    on_disk = {p.name for p in (PUBLIC / "landing").glob("*.webp")}
    c.check(
        "그림 파일 = captures.ts의 그림·배율(남는 것·빠진 것 없음)", on_disk == expected, sorted(on_disk ^ expected)
    )
    videos = VIDEO.findall(text)
    c.check(
        "3D 물결 반복 영상 webm·mp4가 captures.ts에 있음", {kind for _name, kind in videos} == {"webm", "mp4"}, videos
    )
    for name, kind in videos:
        path = PUBLIC / "landing" / f"{name}.{kind}"
        size = path.stat().st_size if path.exists() else -1
        c.check(f"영상 {name}.{kind}: 있음 · {VIDEO_LIMIT:,}바이트 이하", 0 < size <= VIDEO_LIMIT, size)
    for name, width, height, scales in shots:
        sizes = {
            scale: image_size(PUBLIC / "landing" / (f"{name}.webp" if scale == 1 else f"{name}@{scale}x.webp"))
            for scale in _scales(scales)
        }
        c.check(
            f"그림 {name}: 1배 = captures.ts 크기, 배율마다 정확히 n배",
            all(size == (scale * int(width), scale * int(height)) for scale, size in sizes.items()),
            (name, sizes, (width, height)),
        )
    c.check("링크 미리보기 그림 og.png = 1200×630", image_size(PUBLIC / "og.png") == (1200, 630))


def _scales(text: str) -> list[int]:
    """captures.ts scales 글('1, 2, 4') → 배율 목록. 없으면 1·2배."""
    return [int(part) for part in text.split(",")] if text.strip() else [1, 2]
