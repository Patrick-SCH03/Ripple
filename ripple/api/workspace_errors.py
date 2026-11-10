"""작업 공간·가져오기 오류(API가 409·404·422·503으로 바꾼다)와 409 응답 만들기."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status

from ripple.contracts.updates import UpdatePreview
from ripple.contracts.workspace import ImportConflict, WorkspaceConflict

from .generation import Workspace


class StaleWorkspace(Exception):
    """요청이 기대한 작업 공간이 지금 것이 아니다(409)."""

    def __init__(self, expected: str, active: Workspace) -> None:
        super().__init__(expected, active.token)
        self.conflict = WorkspaceConflict(
            message="다른 곳에서 지도 변경 또는 서버 재시작 · 지금 지도로 다시 불러온 뒤 진행",
            expected=expected,
            active=active.token,
            active_snapshot_id=active.snapshot.snapshot_id,
        )


class ImportChanged(Exception):
    """화면이 보낸 가져오기 상태 버전이 지금 것이 아니거나, 그 버전에서 오류 없이 만든 지도가 없다(409)."""

    def __init__(self, message: str, version: int) -> None:
        super().__init__(message, version)
        self.conflict = ImportConflict(message=message, version=version)


class UpdateRejected(ValueError):
    """상태 갱신에 거부 항목이 있다(422, 아무것도 바꾸지 않음)."""

    def __init__(self, preview: UpdatePreview) -> None:
        super().__init__(f"거부 항목 {len(preview.problems)}건")
        self.preview = preview


class NotFound(LookupError):
    """목록에 없는 지도·없거나 만료된 가져오기(404). 메시지는 명사형."""


class Busy(RuntimeError):
    """다른 엑셀을 읽는 중(503). 메시지는 명사형."""


def conflict(error: StaleWorkspace | ImportChanged) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error.conflict.model_dump(mode="json"))


@contextmanager
def import_step_errors(*, invalid: bool) -> Iterator[None]:
    """가져오기 단계(다시 제안·확정 매핑으로 읽기)의 오류 → HTTP: 상태 버전 다름 409 · 없거나 만료 404 · 다른 엑셀을
    읽는 중 503, invalid면 값 오류(모르는 시트·빈 머리글 행) 422(아니면 그대로 낸다)."""
    try:
        yield
    except ImportChanged as error:
        raise conflict(error) from None
    except NotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    except Busy as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
    except ValueError as error:
        if not invalid:
            raise
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
