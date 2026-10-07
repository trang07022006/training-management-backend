"""
Mô hình dữ liệu Lead / Yêu cầu tư vấn (SCRUM-125 - Activity A1).
Đại diện cho thông tin khách hàng tiềm năng gửi đăng ký tư vấn tuyển sinh/đào tạo.
Làm nền tảng cho SCRUM-125 (Public Consultation) và các story quản lý Lead tiếp theo (SCRUM-126/127/128).
"""

from dataclasses import dataclass
from datetime import datetime


LEAD_STATUS_NEW = "new"
LEAD_STATUS_CONTACTED = "contacted"
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_CONVERTED = "converted"
LEAD_STATUS_LOST = "lost"
LEAD_STATUS_CANCELLED = "cancelled"

VALID_LEAD_STATUSES = {
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_QUALIFIED,
    LEAD_STATUS_CONVERTED,
    LEAD_STATUS_LOST,
    LEAD_STATUS_CANCELLED,
}

LEAD_SOURCE_PUBLIC_FORM = "public_form"


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
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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
        """
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
