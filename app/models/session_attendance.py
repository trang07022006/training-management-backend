"""
Model cho điểm danh buổi học và lịch sử chỉnh sửa điểm danh (SCRUM-254).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


ATTENDANCE_STATUSES = ("present", "late", "excused", "unexcused")

ATTENDANCE_STATUS_LABELS = {
    "present": "Có mặt",
    "late": "Đi muộn",
    "excused": "Vắng có phép",
    "unexcused": "Vắng không phép",
}


@dataclass
class SessionAttendance:
    """Bản ghi điểm danh của một học viên trong một buổi học."""
    id: str
    schedule_id: str
    student_id: str
    status: str
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "student_id": self.student_id,
            "status": self.status,
            "status_label": ATTENDANCE_STATUS_LABELS.get(self.status, self.status),
            "notes": self.notes,
            "recorded_by": self.recorded_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class AttendanceAuditLog:
    """Bản ghi lịch sử chỉnh sửa điểm danh cho mục đích kiểm toán."""
    id: str
    schedule_id: str
    student_id: str
    old_status: Optional[str]
    new_status: str
    reason: Optional[str]
    performed_by: str
    created_at: Optional[datetime] = None
    performer_name: Optional[str] = None
    performer_email: Optional[str] = None
    student_name: Optional[str] = None
    student_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "student_code": self.student_code,
            "old_status": self.old_status,
            "old_status_label": ATTENDANCE_STATUS_LABELS.get(self.old_status) if self.old_status else "Chưa điểm danh",
            "new_status": self.new_status,
            "new_status_label": ATTENDANCE_STATUS_LABELS.get(self.new_status, self.new_status),
            "reason": self.reason,
            "performed_by": self.performed_by,
            "performer_name": self.performer_name,
            "performer_email": self.performer_email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
