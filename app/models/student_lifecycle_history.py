"""
Model biểu diễn Lịch sử thay đổi vòng đời học viên (Student Lifecycle History) - SCRUM-252.
Lưu vết 3 loại thao tác: Bảo lưu (reserve), Chuyển lớp (transfer), Thôi học (drop).
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class StudentLifecycleHistory:
    id: str
    student_id: str
    action_type: str  # 'reserve', 'transfer', 'drop'
    effective_date: date
    reason: str
    performed_by: str
    created_at: datetime
    updated_at: datetime
    enrollment_id: str | None = None
    source_class_id: str | None = None
    target_class_id: str | None = None
    status: str = "applied"  # 'pending' hoặc 'applied'
    # Các trường bổ sung khi join
    student_name: str | None = None
    student_code: str | None = None
    source_class_code: str | None = None
    target_class_code: str | None = None
    performer_name: str | None = None
    performer_email: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "student_id": self.student_id,
            "enrollment_id": self.enrollment_id,
            "action_type": self.action_type,
            "source_class_id": self.source_class_id,
            "source_class_code": self.source_class_code,
            "target_class_id": self.target_class_id,
            "target_class_code": self.target_class_code,
            "effective_date": self.effective_date.isoformat() if isinstance(self.effective_date, (date, datetime)) else str(self.effective_date),
            "reason": self.reason,
            "status": self.status,
            "performed_by": self.performed_by,
            "performer_name": self.performer_name,
            "performer_email": self.performer_email,
            "student_name": self.student_name,
            "student_code": self.student_code,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }
