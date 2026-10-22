"""
Mô hình dữ liệu Hồ sơ Học viên (Student Profile) - SCRUM-215.
Lưu trữ thông tin học viên được chuyển đổi từ Lead đã chốt.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone


def format_datetime_utc_iso(dt: datetime | date | None) -> str | None:
    """Chuyển đổi datetime sang chuẩn ISO 8601 UTC có hậu tố Z hoặc định dạng ngày nếu là date."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(dt, date):
        return dt.strftime("%Y-%m-%d")
    return str(dt)


@dataclass
class Student:
    """Thực thể Student lưu trữ thông tin học viên."""

    id: str
    student_code: str
    full_name: str
    phone: str
    email: str | None = None
    program_id: str | None = None
    user_id: str | None = None
    lead_id: str | None = None
    status: str = "enrolled"
    entry_level: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Tùy chọn thông tin mở rộng khi JOIN
    program_code: str | None = None
    program_name: str | None = None

    def to_dict(self) -> dict:
        """Chuyển đổi thành dictionary chuẩn API."""
        data = {
            "id": self.id,
            "student_code": self.student_code,
            "full_name": self.full_name,
            "phone": self.phone,
            "email": self.email,
            "program_id": self.program_id,
            "user_id": self.user_id,
            "lead_id": self.lead_id,
            "status": self.status,
            "entry_level": self.entry_level,
            "notes": self.notes,
            "created_at": format_datetime_utc_iso(self.created_at),
            "updated_at": format_datetime_utc_iso(self.updated_at),
        }
        if self.program_code is not None:
            data["program_code"] = self.program_code
        if self.program_name is not None:
            data["program_name"] = self.program_name
        return data
