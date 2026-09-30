from dataclasses import dataclass
from datetime import datetime


@dataclass
class Permission:
    """Đại diện cho quyền hạn (Permission) trong hệ thống RBAC (SCRUM-61)."""

    id: str
    code: str
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
