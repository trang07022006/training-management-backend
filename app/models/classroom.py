from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Classroom:
    id: str
    room_code: str
    room_name: str
    room_type: str  # 'physical' hoặc 'online'
    capacity: int | None = None
    online_link: str | None = None
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_code": self.room_code,
            "room_name": self.room_name,
            "room_type": self.room_type,
            "capacity": self.capacity,
            "online_link": self.online_link,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
