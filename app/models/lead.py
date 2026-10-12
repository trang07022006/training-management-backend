"""
Mô hình dữ liệu Lead / Yêu cầu tư vấn (SCRUM-125 - Activity A1).
Đại diện cho thông tin khách hàng tiềm năng gửi đăng ký tư vấn tuyển sinh/đào tạo.
Làm nền tảng cho SCRUM-125 (Public Consultation) và các story quản lý Lead tiếp theo (SCRUM-126/127/128).
"""

from dataclasses import dataclass
from datetime import datetime, timezone


LEAD_STATUS_NEW = "new"
LEAD_STATUS_CONTACTED = "contacted"
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_WON = "won"
LEAD_STATUS_CONVERTED = "converted"
LEAD_STATUS_LOST = "lost"
LEAD_STATUS_CANCELLED = "cancelled"

VALID_LEAD_STATUSES = {
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_QUALIFIED,
    LEAD_STATUS_WON,
    LEAD_STATUS_CONVERTED,
    LEAD_STATUS_LOST,
    LEAD_STATUS_CANCELLED,
}

LEAD_SOURCE_PUBLIC_FORM = "public_form"
LEAD_SOURCE_DIRECT = "direct"
LEAD_SOURCE_HOTLINE = "hotline"
LEAD_SOURCE_REFERRAL = "referral"
LEAD_SOURCE_SOCIAL = "social"
LEAD_SOURCE_EVENT = "event"
LEAD_SOURCE_OTHER = "other"

VALID_LEAD_SOURCES = {
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_SOURCE_DIRECT,
    LEAD_SOURCE_HOTLINE,
    LEAD_SOURCE_REFERRAL,
    LEAD_SOURCE_SOCIAL,
    LEAD_SOURCE_EVENT,
    LEAD_SOURCE_OTHER,
}


def format_datetime_utc_iso(dt: datetime | None) -> str | None:
    """
    Chuyển đổi datetime sang chuẩn ISO 8601 UTC có timezone rõ ràng với hậu tố 'Z'.
    Ví dụ: 2026-10-10T15:27:00Z
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Lead:
    """
    Thực thể Lead lưu trữ yêu cầu tư vấn của người dùng công khai hoặc các nguồn tuyển sinh.
    """

    id: str
    full_name: str
    phone: str
    email: str | None = None
    interested_program_id: str | None = None
    message: str | None = None
    source: str = LEAD_SOURCE_PUBLIC_FORM
    status: str = LEAD_STATUS_NEW
    assigned_to_user_id: str | None = None
    assigned_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Tùy chọn thông tin mở rộng khi JOIN với training_programs và users
    interested_program_code: str | None = None
    interested_program_name: str | None = None
    assigned_to_name: str | None = None
    assigned_to_email: str | None = None

    def validate_status(self) -> None:
        """Kiểm tra trạng thái của Lead có nằm trong danh mục hợp lệ không."""
        if self.status not in VALID_LEAD_STATUSES:
            raise ValueError(f"Trạng thái Lead không hợp lệ: {self.status}")

    def update_status(self, new_status: str) -> None:
        """Cập nhật trạng thái mới cho Lead."""
        if new_status not in VALID_LEAD_STATUSES:
            raise ValueError(f"Trạng thái Lead không hợp lệ: {new_status}")
        self.status = new_status

    def to_dict(self) -> dict:
        """
        Chuyển đổi thực thể Lead thành dictionary đầy đủ cho tầng nội bộ / quản trị.
        Các trường thời gian được chuẩn hóa ISO 8601 UTC (hậu tố Z).
        """
        data = {
            "id": self.id,
            "full_name": self.full_name,
            "phone": self.phone,
            "email": self.email,
            "interested_program_id": self.interested_program_id,
            "message": self.message,
            "source": self.source,
            "status": self.status,
            "assigned_to_user_id": self.assigned_to_user_id,
            "assigned_at": format_datetime_utc_iso(self.assigned_at),
            "created_at": format_datetime_utc_iso(self.created_at),
            "updated_at": format_datetime_utc_iso(self.updated_at),
        }
        if self.interested_program_code is not None:
            data["interested_program_code"] = self.interested_program_code
        if self.interested_program_name is not None:
            data["interested_program_name"] = self.interested_program_name
        if self.assigned_to_name is not None:
            data["assigned_to_name"] = self.assigned_to_name
        if self.assigned_to_email is not None:
            data["assigned_to_email"] = self.assigned_to_email
        return data

    def to_public_dict(self) -> dict:
        """
        Chuyển đổi dữ liệu trả về cho public client (tối thiểu thông tin, bảo mật PII).
        Các trường thời gian được chuẩn hóa ISO 8601 UTC (hậu tố Z).
        """
        return {
            "id": self.id,
            "created_at": format_datetime_utc_iso(self.created_at),
        }
