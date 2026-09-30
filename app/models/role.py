from dataclasses import dataclass
from datetime import datetime


@dataclass
class Role:
    """Đại diện cho vai trò (Role) trong hệ thống phân quyền RBAC (SCRUM-60)."""

    id: str
    code: str
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
