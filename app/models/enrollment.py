"""
Model thực thể Ghi danh học viên vào lớp (Enrollment) - SCRUM-218.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def format_datetime_utc_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


@dataclass
class Enrollment:
    id: str
    class_id: str
    student_id: str
    status: str
    enrolled_at: datetime
    enrolled_by: str
    created_at: datetime
    updated_at: datetime
    student_code: str | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    student_status: str | None = None
    enrolled_by_name: str | None = None
    enrolled_by_email: str | None = None
    class_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "class_id": self.class_id,
            "student_id": self.student_id,
            "status": self.status,
            "enrolled_at": format_datetime_utc_iso(self.enrolled_at),
            "enrolled_by": self.enrolled_by,
            "created_at": format_datetime_utc_iso(self.created_at),
            "updated_at": format_datetime_utc_iso(self.updated_at),
            "student_code": self.student_code,
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "student_status": self.student_status,
            "enrolled_by_name": self.enrolled_by_name or self.enrolled_by_email or self.enrolled_by,
            "enrolled_by_email": self.enrolled_by_email,
            "class_code": self.class_code,
        }
