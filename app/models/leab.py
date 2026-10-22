from dataclasses import dataclass
from datetime import datetime, timezone


LEAD_STATUS_NEW = "new"
LEAD_STATUS_CONTACTED = "contacted"
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_CONVERTED = "converted"
LEAD_STATUS_LOST = "lost"

VALID_LEAD_STATUSES = {
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_QUALIFIED,
    LEAD_STATUS_CONVERTED,
    LEAD_STATUS_LOST,
}


@dataclass
class Lead:
    id: str
    name: str
    phone: str
    email: str | None = None
    source: str | None = None
    interested_program: str | None = None
    status: str = LEAD_STATUS_NEW
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("Họ tên không được để trống")

        if not self.phone or not self.phone.strip():
            raise ValueError("Số điện thoại không được để trống")

        self.name = self.name.strip()
        self.phone = self.phone.strip()

        if self.email is not None:
            self.email = self.email.strip().lower()

        if self.source is not None:
            self.source = self.source.strip()

        if self.interested_program is not None:
            self.interested_program = self.interested_program.strip()

        self.validate_status()

    def validate_status(self) -> None:
        if self.status not in VALID_LEAD_STATUSES:
            raise ValueError(
                f"Trạng thái Lead không hợp lệ: {self.status}"
            )

    def update_status(self, status: str) -> None:
        if status not in VALID_LEAD_STATUSES:
            raise ValueError(
                f"Trạng thái Lead không hợp lệ: {status}"
            )

        self.status = status
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "phone": self.phone,
            "email": self.email,
            "source": self.source,
            "interested_program": self.interested_program,
            "status": self.status,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at
                else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at
                else None
            ),
        }