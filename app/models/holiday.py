"""
Model thực thể Ngày nghỉ lễ (Holiday) - SCRUM-224.
Dùng để tự động bỏ qua các ngày nghỉ lễ khi sinh thời khóa biểu theo mẫu lặp.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class Holiday:
    id: str
    holiday_date: date | str
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        date_str = None
        if self.holiday_date:
            if isinstance(self.holiday_date, (datetime, date)):
                date_str = self.holiday_date.strftime("%Y-%m-%d")
            else:
                date_str = str(self.holiday_date)

        return {
            "id": self.id,
            "holiday_date": date_str,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
