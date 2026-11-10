"""알림 메일의 받는 사람·참조·보내는 조직(docs/records.md(통보)).

연락처 묶음(ContactBook)은 시연용 가상 연락처다(params/contacts_v1.yaml). 합성 데이터 지도에만 붙이고 실데이터
지도에는 붙이지 않는다. 가상 연락처의 이메일은 모두 예약 도메인 '.example'이라 실제로 배달될 수 없다.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import Frozen

EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
RESERVED_DOMAIN = ".example"  # RFC 2606: 배달되지 않는 예약 도메인


class Contact(Frozen):
    organization: str = Field(min_length=1, max_length=60)  # 회사 이름
    department: str | None = Field(default=None, max_length=40)
    name: str = Field(min_length=1, max_length=40)
    title: str | None = Field(default=None, max_length=20)  # 직함(과장·책임 등)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=120)

    def honorific(self, colleague: bool = False) -> str:
        """인사말 호칭: 바깥 회사면 '한결밸브 최유진 과장님', 같은 회사 동료면 부서로 '배관설계팀 강민재 책임님'."""
        person = f"{self.name} {self.title}님" if self.title else f"{self.name}님"
        place = self.department if colleague and self.department else self.organization
        return f"{place} {person}"


class ContactBook(Frozen):
    """시연용 가상 연락처. 열쇠는 협력사 ID(지도의 supplier_id)와 도면 분야(hull·piping·outfitting·machinery·design)."""

    version: str
    organization: str = Field(min_length=1, max_length=60)  # 보내는 회사(같은 회사 연락처는 부서로 부른다)
    sender: str = Field(min_length=1, max_length=60)  # 보내는 조직·부서(서명 줄), 예: '가람조선 설계팀'
    procurement: Contact  # 협력사 메일의 참조(구매 담당)
    production: Contact  # 사내 제작 블록의 재작업 메일 받는 사람(생산관리)
    suppliers: dict[str, Contact]
    drawing: dict[str, Contact]

    @model_validator(mode="after")
    def _reserved_only(self) -> ContactBook:
        everyone = [self.procurement, self.production, *self.suppliers.values(), *self.drawing.values()]
        real = sorted(c.email for c in everyone if not c.email.lower().endswith(RESERVED_DOMAIN))
        if real:
            raise ValueError(f"가상 연락처의 이메일은 '{RESERVED_DOMAIN}' 도메인만 써요: {', '.join(real)}")
        return self
