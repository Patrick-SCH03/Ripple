"""지도 파일 읽기: 생성기·가져오기가 쓴 snapshot.json → GraphSnapshot."""

from __future__ import annotations

from pathlib import Path

from ripple.contracts.domain import DataMode, GraphSnapshot
from ripple.contracts.identity import snapshot_id


def load_snapshot(path: Path, data_mode: DataMode) -> GraphSnapshot:
    """지도 파일을 읽고 내용 해시와 데이터 모드를 확인한다.

    실제 데이터 지도는 real 모드에서만 연다(합성 모드에서는 외부 LLM 호출이 열려 있기 때문).
    """
    if not path.exists():
        raise FileNotFoundError(
            f"지도 파일 없음: {path} — `uv run python scripts/generate.py`로 합성 지도 생성 또는 "
            "RIPPLE_SNAPSHOT_PATH 지정 필요"
        )
    snapshot = GraphSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    if snapshot_id(snapshot) != snapshot.snapshot_id:
        raise ValueError(f"지도 파일 ID({snapshot.snapshot_id})와 내용 불일치: {path}")
    if snapshot.data_mode is DataMode.REAL and data_mode is not DataMode.REAL:
        raise ValueError("실제 데이터 지도는 RIPPLE_DATA_MODE=real에서만 열기 가능(외부 LLM 차단)")
    return snapshot
