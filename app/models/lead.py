"""
Mô hình dữ liệu Lead / Yêu cầu tư vấn (SCRUM-125 - Activity A1).
Đại diện cho thông tin khách hàng tiềm năng gửi đăng ký tư vấn tuyển sinh/đào tạo.
Làm nền tảng cho SCRUM-125 (Public Consultation) và các story quản lý Lead tiếp theo (SCRUM-126/127/128).
"""

from dataclasses import dataclass
from datetime import datetime, timezone


LEAD_STATUS_NEW = "new"
LEAD_STATUS_CONTACTED = "contacted"
LEAD_STATUS_CONSULTING = "consulting"
LEAD_STATUS_TRIAL_SCHEDULED = "trial_scheduled"
LEAD_STATUS_WON = "won"
LEAD_STATUS_REJECTED = "rejected"

# SCRUM-213: 6 standard pipeline statuses in exact order
PIPELINE_LEAD_STATUSES = [
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_CONSULTING,
    LEAD_STATUS_TRIAL_SCHEDULED,
    LEAD_STATUS_WON,
    LEAD_STATUS_REJECTED,
]

# Legacy statuses for backward compatibility with existing tests
LEAD_STATUS_QUALIFIED = "qualified"
LEAD_STATUS_CONVERTED = "converted"
LEAD_STATUS_LOST = "lost"
LEAD_STATUS_CANCELLED = "cancelled"

VALID_LEAD_STATUSES = {
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_CONSULTING,
    LEAD_STATUS_TRIAL_SCHEDULED,
    LEAD_STATUS_WON,
    LEAD_STATUS_REJECTED,
    LEAD_STATUS_QUALIFIED,
    LEAD_STATUS_CONVERTED,
    LEAD_STATUS_LOST,
    LEAD_STATUS_CANCELLED,
}

# SCRUM-213: Danh sách lý do từ chối chuẩn
REJECTION_REASON_NO_NEED = "Không còn nhu cầu"
REJECTION_REASON_COST_UNSUITABLE = "Chi phí không phù hợp"
REJECTION_REASON_CHOSE_OTHER = "Chọn đơn vị khác"
REJECTION_REASON_UNREACHABLE = "Không liên lạc được"
REJECTION_REASON_OTHER = "Khác"

VALID_REJECTION_REASONS = [
    REJECTION_REASON_NO_NEED,
    REJECTION_REASON_COST_UNSUITABLE,
    REJECTION_REASON_CHOSE_OTHER,
    REJECTION_REASON_UNREACHABLE,
    REJECTION_REASON_OTHER,
]

# SCRUM-214: Loại tương tác chăm sóc Lead chuẩn (Gọi, Nhắn, Gặp)
INTERACTION_TYPE_CALL = "call"
INTERACTION_TYPE_MESSAGE = "message"
INTERACTION_TYPE_MEETING = "meeting"

VALID_INTERACTION_TYPES = (
    INTERACTION_TYPE_CALL,
    INTERACTION_TYPE_MESSAGE,
    INTERACTION_TYPE_MEETING,
)

INTERACTION_TYPE_LABELS = {
    INTERACTION_TYPE_CALL: "Gọi",
    INTERACTION_TYPE_MESSAGE: "Nhắn",
    INTERACTION_TYPE_MEETING: "Gặp",
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
    rejection_reason: str | None = None
    callback_date: str | None = None
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
            "rejection_reason": self.rejection_reason,
            "callback_date": self.callback_date,
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


@dataclass
class LeadCareLog:
    """
    Thực thể lưu nhật ký tương tác chăm sóc khách hàng (SCRUM-214 - Activity A1).
    Bao gồm loại tương tác (Gọi, Nhắn, Gặp), nội dung, thời điểm và người thực hiện.
    """

    id: str
    lead_id: str
    interaction_type: str
    content: str
    interaction_at: datetime
    performed_by_user_id: str | None = None
    performed_by_name: str | None = None
    created_at: datetime | None = None

    def validate(self) -> None:
        """Kiểm tra tính hợp lệ của nhật ký chăm sóc."""
        if self.interaction_type not in VALID_INTERACTION_TYPES:
            raise ValueError(
                f"Loại tương tác không hợp lệ: {self.interaction_type}. Chỉ chấp nhận 'call', 'message', hoặc 'meeting'."
            )
        if not self.content or not self.content.strip():
            raise ValueError("Nội dung tương tác không được để trống.")

    def to_dict(self) -> dict:
        """Chuyển đổi thực thể thành dictionary cho response API."""
        return {
            "id": self.id,
            "lead_id": self.lead_id,
            "interaction_type": self.interaction_type,
            "interaction_type_label": INTERACTION_TYPE_LABELS.get(
                self.interaction_type, self.interaction_type
            ),
            "content": self.content,
            "interaction_at": format_datetime_utc_iso(self.interaction_at),
            "performed_by_user_id": self.performed_by_user_id,
            "performed_by_name": self.performed_by_name,
            "created_at": format_datetime_utc_iso(self.created_at),
        }
