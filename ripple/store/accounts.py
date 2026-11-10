"""계정·세션 저장소(파일): 서버를 다시 켜거나 다시 배포해도 계정과 로그인이 남는다(docs/operations.md(서비스) 2절).

폴더(설정 RIPPLE_DATA_DIR — 지도 저장소와 같은 곳, 깃 제외):
  accounts.json   {"version": 3, "accounts": [StoredAccount, ...]}
                  계정을 지운 뒤에는 {"version": 4, "accounts": [...], "retired_ids": [지운 아이디, ...]}
  sessions.json   {"version": 1, "sessions": [StoredSession, ...]}
                  토큰은 SHA-256만 둔다(파일이 새도 쓸 수 있는 토큰이 아님)

- 쓰기는 write_atomic(같은 폴더 임시 파일 → 바꿔 끼우기,
  Windows 짧은 잠금은 다시 시도 — config/files.py). 서버 프로세스는 하나라는 전제로
  메모리 사본 + 잠금으로 차례를 지킨다.
- 계정 파일이 손상됐으면 AccountStoreError로 시작을 멈춘다(빈 계정으로 시작해 첫 관리자 변수가
  관리자를 새로 만들지 않게).
  세션 파일이 손상됐으면 세션 없이 시작한다(모두 다시 로그인).
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, Field, ValidationError, field_validator

from ripple.contracts.auth import DisplayName, LoginId, StaffRole
from ripple.contracts.base import Frozen

from .snapshots import write_atomic

MAX_SESSIONS = 1000  # 넘으면 오래된 세션부터 지운다(체험 로그인이 파일을 끝없이 늘리지 않게)


class AccountStoreError(ValueError):
    """계정·세션 파일을 읽을 수 없다(손상·형식 오류). 메시지는 명사형."""


class RetiredIdError(ValueError):
    """지운 계정의 아이디로 새 계정을 만들려 함(지운 아이디는 다시 쓰지 않는다)."""


class StoredAccount(Frozen):
    login_id: LoginId
    name: DisplayName
    role: StaffRole
    password_hash: str = Field(min_length=1)
    must_change_password: bool = False
    disabled: bool = False
    created_at: AwareDatetime
    last_login_at: AwareDatetime | None = None
    # 세션 판: 비밀번호 변경·초기화·역할 변경·멈춤마다 1씩 오른다. 세션은 만들 때의 판을 갖고, 판이 다르면 무효
    # (세션 지우기와 로그인이 엇갈려도 옛 비밀번호로 만든 세션이 살아남지 않게)
    session_version: int = Field(default=0, ge=0)


class StoredSession(Frozen):
    token_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    login_id: str  # 체험 세션은 공용 계정 ID
    demo: bool = False
    account_version: int = Field(default=0, ge=0)  # 만들 때 계정의 세션 판
    created_at: AwareDatetime
    expires_at: AwareDatetime


# 파일 형식 판: 2 = 계정·세션의 세션 판(session_version·account_version)을 둠. 1은 그 필드 없이 0으로 읽는다.
# 3 = 계정의 결재 단계(approval_level)를 뒀던 판(계약 1.24.0). 1.25.0에서 결재 단계를 없애 읽을 때 그 칸을 버리고,
#     쓸 때는 넣지 않는다(판 번호는 3 그대로 — 1.24.0 코드가 이 파일을 읽으면 빠진 칸을 기본값으로 채운다).
# 모르는(더 새) 판이면 읽기 오류로 시작을 멈춘다 — 새 형식으로 쓴 볼륨을 옛 이미지로 되돌리면 세션 판을 모르는 코드가
# 폐기한 세션을 되살릴 수 있으므로 조용히 무시하지 않는다(되돌릴 때는 볼륨 백업도 함께, docs/operations.md(배포) 4절).
FILE_VERSIONS = (1, 2, 3)
FILE_VERSION = 3
# 계정 파일만 판 4 = 지운 계정의 아이디 목록(retired_ids)을 둠(계정 삭제). 지운 계정이 없으면 판 3 그대로 쓰고(옛 코드로
# 되돌려도 읽힘), 하나라도 지우면 판 4로 쓴다 — 옛 코드는 이 파일로 시작하지 않는다(지운 아이디를 다시 만들어
# 기록·감사에 남은 그 사람과 새 사람이 한 아이디로 섞이지 않게). 세션 파일은 판 3 그대로.
RETIRED_IDS_VERSION = 4
ACCOUNT_FILE_VERSIONS = (*FILE_VERSIONS, RETIRED_IDS_VERSION)


RETIRED_ACCOUNT_FIELDS = frozenset({"approval_level"})  # 판 3(계약 1.24.0)에만 있던 칸 — 읽을 때 버린다


class _AccountFile(Frozen):
    version: int = FILE_VERSION
    accounts: tuple[StoredAccount, ...] = ()
    retired_ids: tuple[str, ...] = ()  # 판 4: 지운 계정의 아이디(다시 쓰지 않는다)

    @field_validator("version")
    @classmethod
    def _known(cls, value: int) -> int:
        if value not in ACCOUNT_FILE_VERSIONS:
            raise ValueError(f"모르는 계정 파일 형식 판: {value}")
        return value

    @field_validator("accounts", mode="before")
    @classmethod
    def _drop_retired(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        return [
            {k: v for k, v in item.items() if k not in RETIRED_ACCOUNT_FIELDS} if isinstance(item, dict) else item
            for item in value
        ]


class _SessionFile(Frozen):
    version: int = FILE_VERSION
    sessions: tuple[StoredSession, ...] = ()

    @field_validator("version")
    @classmethod
    def _known(cls, value: int) -> int:
        if value not in FILE_VERSIONS:
            raise ValueError(f"모르는 세션 파일 형식 판: {value}")
        return value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def account_file_text(accounts: Iterable[StoredAccount], retired: Collection[str]) -> str:
    """계정 파일 본문: 지운 아이디가 없으면 판 3(그 칸 없음 — 옛 코드도 읽음), 있으면 판 4.
    계정은 만든 시각·아이디 순."""
    ordered = tuple(sorted(accounts, key=lambda a: (a.created_at, a.login_id)))
    if not retired:
        return _AccountFile(accounts=ordered).model_dump_json(indent=2, exclude={"retired_ids"}) + "\n"
    body = _AccountFile(version=RETIRED_IDS_VERSION, accounts=ordered, retired_ids=tuple(sorted(retired)))
    return body.model_dump_json(indent=2) + "\n"


class AccountStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "accounts.json"
        self._lock = threading.Lock()
        self._accounts: dict[str, StoredAccount] = {}
        self._retired: frozenset[str] = frozenset()
        self._loaded = False

    def load(self) -> None:
        """파일을 읽어 메모리 사본을 만든다. 파일이 없으면 빈 저장소. 손상이면 AccountStoreError."""
        with self._lock:
            stored = _read(self.path, _AccountFile)
            self._accounts = {a.login_id: a for a in stored.accounts}
            self._retired = frozenset(stored.retired_ids)
            self._loaded = True

    def all(self) -> tuple[StoredAccount, ...]:
        with self._lock:
            self._require()
            return tuple(sorted(self._accounts.values(), key=lambda a: (a.created_at, a.login_id)))

    def get(self, login_id: str) -> StoredAccount | None:
        with self._lock:
            self._require()
            return self._accounts.get(login_id)

    def is_retired(self, login_id: str) -> bool:
        """지운 계정의 아이디인가(다시 쓰지 않는다)."""
        with self._lock:
            self._require()
            return login_id in self._retired

    def change(self, mutate: Callable[[dict[str, StoredAccount]], None]) -> None:
        """잠근 채로 사본을 고치고 파일에 쓴다. 쓰기가 실패하면 메모리도 그대로 둔다.
        지운 아이디로 계정을 새로 넣으면 RetiredIdError(아무것도 쓰지 않음)."""
        with self._lock:
            self._require()
            draft = dict(self._accounts)
            mutate(draft)
            reused = sorted((draft.keys() - self._accounts.keys()) & self._retired)
            if reused:
                raise RetiredIdError(f"지운 계정의 아이디 재사용 불가: {', '.join(reused)}")
            self._write(draft, self._retired)

    def delete(
        self, login_id: str, check: Callable[[StoredAccount, Mapping[str, StoredAccount]], None]
    ) -> StoredAccount | None:
        """잠근 채로 계정을 지우고 그 아이디를 지운 아이디 목록에 넣어 파일에 쓴다. 지운 계정(없으면 None, 아무것도
        쓰지 않음). check는 잠금 안의 지울 계정(지우기 전)과 지운 뒤의 계정들을 보고 예외로 거절할 수 있다(마지막 팀장
        등 — 잠금 밖에서 먼저 읽은 사본으로 판단하지 않게)."""
        with self._lock:
            self._require()
            draft = dict(self._accounts)
            removed = draft.pop(login_id, None)
            if removed is None:
                return None
            check(removed, draft)
            retired = self._retired | {login_id}
            self._write(draft, retired)
            self._retired = retired
            return removed

    def _write(self, draft: dict[str, StoredAccount], retired: frozenset[str]) -> None:
        """잠금 안에서 부른다: 파일에 쓰고 성공하면 메모리 사본을 바꾼다."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self.path, account_file_text(draft.values(), retired))
        self._accounts = draft

    def _require(self) -> None:
        if not self._loaded:
            raise RuntimeError("계정 저장소 아직 안 읽음")


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "sessions.json"
        self._lock = threading.Lock()
        self._sessions: dict[str, StoredSession] = {}
        self.load_problem: str | None = None

    def load(self, now: datetime) -> None:
        """파일을 읽는다. 손상이면 세션 없이 시작하고 load_problem에 이유를 남긴다. 만료된 세션은 버린다."""
        with self._lock:
            try:
                stored = _read(self.path, _SessionFile).sessions
            except AccountStoreError as error:
                stored = ()
                self.load_problem = str(error)
            self._sessions = {s.token_hash: s for s in stored if s.expires_at > now}

    def create(
        self,
        login_id: str,
        *,
        demo: bool,
        now: datetime,
        expires_at: datetime,
        version: int = 0,
        keep_latest: int | None = None,
    ) -> str:
        """새 세션의 토큰(32바이트 무작위, URL에 안전한 글자)을 돌려준다. 저장은 해시만.

        keep_latest가 있으면(빠른 로그인처럼 인증 없이 만드는 세션) 그 계정 세션을 최근 keep_latest개만 남기고, 전역
        상한을 넘으면 그 계정의 오래된 세션부터 지운다 — 다른 계정의 세션을 밀어내지 않게."""
        token = secrets.token_urlsafe(32)
        session = StoredSession(
            token_hash=token_hash(token),
            login_id=login_id,
            demo=demo,
            account_version=version,
            created_at=now,
            expires_at=expires_at,
        )

        capped_owner = login_id if keep_latest is not None else None

        def add(sessions: dict[str, StoredSession]) -> None:
            for key in [k for k, s in sessions.items() if s.expires_at <= now]:
                del sessions[key]
            sessions[session.token_hash] = session
            if keep_latest is not None:
                _drop(sessions, stale_own(sessions.values(), login_id, keep_latest))
            _drop(sessions, over_cap(sessions.values(), owner=capped_owner, fresh=session, cap=MAX_SESSIONS))

        self._change(add)
        return token

    def resolve(self, token: str, now: datetime) -> StoredSession | None:
        """토큰의 세션. 없거나 만료면 None(만료된 것은 다음 쓰기 때 지운다)."""
        with self._lock:
            session = self._sessions.get(token_hash(token))
        if session is None or session.expires_at <= now:
            return None
        return session

    def delete(self, token: str) -> None:
        key = token_hash(token)

        def drop(sessions: dict[str, StoredSession]) -> None:
            sessions.pop(key, None)

        self._change(drop)

    def delete_for(self, login_id: str, *, below: int | None = None, keep: str | None = None) -> None:
        """그 계정의 세션을 지운다: 비밀번호 변경·초기화·끄기·역할 변경 뒤 정리(무효 판단은 세션 판이 한다).

        below가 있으면 그 판보다 오래된 세션만 — 계정 변경과 정리 사이에 새 판으로 만든 정상 세션은 남긴다.
        keep 토큰 하나는 남길 수 있다."""
        kept = None if keep is None else token_hash(keep)

        def stale(session: StoredSession) -> bool:
            return session.login_id == login_id and (below is None or session.account_version < below)

        def drop(sessions: dict[str, StoredSession]) -> None:
            for key in [k for k, s in sessions.items() if stale(s) and k != kept]:
                del sessions[key]

        self._change(drop)

    def count_for(self, login_id: str) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.login_id == login_id)

    def _change(self, mutate: Callable[[dict[str, StoredSession]], None]) -> None:
        with self._lock:
            draft = dict(self._sessions)
            mutate(draft)
            body = _SessionFile(sessions=tuple(sorted(draft.values(), key=lambda s: s.created_at)))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, body.model_dump_json(indent=2) + "\n")
            self._sessions = draft


def stale_own(sessions: Iterable[StoredSession], login_id: str, keep: int) -> list[StoredSession]:
    """그 계정 세션 가운데 최근 keep개를 넘는 오래된 것(만든 시각 순 — 같은 시각이면 먼저 들어온 것이 오래된 것)."""
    own = sorted((s for s in sessions if s.login_id == login_id), key=lambda s: s.created_at)
    return own[: max(0, len(own) - keep)]


def over_cap(
    sessions: Collection[StoredSession], *, owner: str | None, fresh: StoredSession, cap: int
) -> list[StoredSession]:
    """전역 상한(cap)을 넘는 만큼 지울 세션. owner(상한이 있는 세션을 만든 계정)가 있으면 그 계정의 오래된 세션부터 —
    다른 계정의 세션을 밀어내지 않게 — 그다음 전체에서 오래된 순. 방금 만든 세션(fresh)은 자기 계정 몫에 넣지 않는다."""
    extra = len(sessions) - cap
    if extra <= 0:
        return []

    def own_older(other: StoredSession) -> bool:
        return owner is not None and other.login_id == owner and other is not fresh

    return sorted(sessions, key=lambda s: (not own_older(s), s.created_at))[:extra]


def _drop(sessions: dict[str, StoredSession], olds: Iterable[StoredSession]) -> None:
    for old in olds:
        del sessions[old.token_hash]


def _read[T: Frozen](path: Path, model: type[T]) -> T:
    if not path.exists():
        return model()
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as error:
        raise AccountStoreError(f"{path.name} 읽기 실패: {type(error).__name__}") from None
