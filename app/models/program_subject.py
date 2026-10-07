from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ProgramSubject:
    """
    Đại diện cho một môn học gắn trong cấu trúc chương trình đào tạo (SCRUM-124 - Activity A1).
    Xác định học kỳ, tính bắt buộc/tự chọn, thứ tự học và liên kết điều kiện tiên quyết.
    """

    id: str
    program_id: str
    subject_id: str
    semester: int | None = None
    is_mandatory: bool = True
    order_index: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Thông tin join từ bảng subjects (phục vụ hiển thị cấu trúc chương trình)
    subject_code: str | None = None
    subject_name: str | None = None
    subject_credits: int | None = None
    subject_total_sessions: int | None = None
    subject_status: str | None = None

    # Danh sách điều kiện tiên quyết (danh sách ID hoặc dict chi tiết)
    prerequisites: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi thực thể ProgramSubject thành dictionary an toàn cho JSON serialization."""
        data: dict[str, Any] = {
            "id": self.id,
            "program_id": self.program_id,
            "subject_id": self.subject_id,
            "semester": self.semester,
            "is_mandatory": bool(self.is_mandatory),
            "order_index": self.order_index,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if self.subject_code is not None:
            data["subject_code"] = self.subject_code
        if self.subject_name is not None:
            data["subject_name"] = self.subject_name
        if self.subject_credits is not None:
            data["subject_credits"] = self.subject_credits
        if self.subject_total_sessions is not None:
            data["total_sessions"] = self.subject_total_sessions
        if self.subject_status is not None:
            data["subject_status"] = self.subject_status
        if self.prerequisites:
            data["prerequisites"] = self.prerequisites
        return data
