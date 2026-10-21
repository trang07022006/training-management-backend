"""
Mô hình dữ liệu Đơn xin phép vắng (SCRUM-255).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


ABSENCE_STATUS_PENDING = "pending"
ABSENCE_STATUS_APPROVED = "approved"
ABSENCE_STATUS_REJECTED = "rejected"

ABSENCE_STATUSES = {
    ABSENCE_STATUS_PENDING,
    ABSENCE_STATUS_APPROVED,
    ABSENCE_STATUS_REJECTED,
}

ABSENCE_STATUS_LABELS = {
    ABSENCE_STATUS_PENDING: "Chờ duyệt",
    ABSENCE_STATUS_APPROVED: "Đã duyệt",
    ABSENCE_STATUS_REJECTED: "Từ chối",
}


@dataclass
class AbsenceRequestAttachment:
    id: str
    request_id: str
    file_name: str
    file_path: str
    file_size: int
    mime_type: str
    created_at: Optional[datetime] = None


@dataclass
class AbsenceRequest:
    id: str
    schedule_id: str
    student_id: str
    reason: str
    status: str = ABSENCE_STATUS_PENDING
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
