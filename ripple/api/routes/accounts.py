"""구성원 관리(관리자): 목록 · 추가(임시 비밀번호를 이 응답에서만) · 비밀번호 초기화 · 이름·역할·사용 여부 바꾸기 ·
지우기.

내 줄과 빠른 로그인 고정 계정은 바꾸거나 지울 수 없다(403 forbidden, ripple/auth/members.py)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from ripple.auth import AuthError, AuthService, Principal
from ripple.contracts.auth import Account, AccountCreate, AccountCreated, AccountList, AccountUpdate, PasswordIssued

from ..security import AUTH_RESPONSES, from_error, get_auth, require_manage

router = APIRouter(tags=["accounts"], responses=AUTH_RESPONSES)

Auth = Annotated[AuthService, Depends(get_auth)]
Manager = Annotated[Principal, Depends(require_manage)]


@router.get("/accounts")
def list_accounts(_: Manager, auth: Auth) -> AccountList:
    return AccountList(items=auth.list_accounts())


@router.post(
    "/accounts",
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "이미 있거나 쓸 수 없는 아이디(account_exists)"}},
)
def create_account(body: AccountCreate, _: Manager, auth: Auth) -> AccountCreated:
    try:
        return auth.create_account(body)
    except AuthError as error:
        raise from_error(error) from None


@router.post(
    "/accounts/{login_id}/reset-password",
    responses={404: {"description": "없는 계정"}, 422: {"description": "내 계정(비밀번호 바꾸기를 쓰기)"}},
)
def reset_password(login_id: str, actor: Manager, auth: Auth) -> PasswordIssued:
    try:
        return auth.reset_password(actor, login_id)
    except AuthError as error:
        raise from_error(error) from None


@router.patch(
    "/accounts/{login_id}",
    responses={404: {"description": "없는 계정"}, 409: {"description": "사용 중인 관리자가 0명이 됨(last_admin)"}},
)
def update_account(login_id: str, body: AccountUpdate, actor: Manager, auth: Auth) -> Account:
    try:
        return auth.update_account(actor, login_id, body)
    except AuthError as error:
        raise from_error(error) from None


@router.delete(
    "/accounts/{login_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "내 계정·빠른 로그인 고정 계정(forbidden)"},
        404: {"description": "없는 계정"},
        409: {"description": "사용 중인 관리자가 0명이 됨(last_admin)"},
    },
)
def delete_account(login_id: str, actor: Manager, auth: Auth) -> Response:
    """계정 지우기: 그 계정의 세션을 모두 끊는다. 기록·감사에 남은 이름은 그대로이고 그 아이디는 다시 쓰지 않는다."""
    try:
        auth.delete_account(actor, login_id)
    except AuthError as error:
        raise from_error(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
