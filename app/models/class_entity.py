"""
Model thực thể Lớp học (Class Entity) - SCRUM-217.
Vòng đời: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


CLASS_STATUS_PREPARING = "preparing"
CLASS_STATUS_IN_PROGRESS = "in_progress"
CLASS_STATUS_COMPLETED = "completed"
CLASS_STATUS_CANCELLED = "cancelled"

CLASS_STATUSES = [
    CLASS_STATUS_PREPARING,
    CLASS_STATUS_IN_PROGRESS,
    CLASS_STATUS_COMPLETED,
    CLASS_STATUS_CANCELLED,
]

CLASS_STATUS_LABELS = {
    CLASS_STATUS_PREPARING: "Chuẩn bị",
    CLASS_STATUS_IN_PROGRESS: "Đang học",
    CLASS_STATUS_COMPLETED: "Kết thúc",
    CLASS_STATUS_CANCELLED: "Huỷ",
}

# Hỗ trợ ánh xạ ngược từ tiếng Việt sang mã trạng thái chuẩn
VIETNAMESE_TO_STATUS = {
    "chuẩn bị": CLASS_STATUS_PREPARING,
    "chuan bi": CLASS_STATUS_PREPARING,
    "đang học": CLASS_STATUS_IN_PROGRESS,
    "dang hoc": CLASS_STATUS_IN_PROGRESS,
    "kết thúc": CLASS_STATUS_COMPLETED,
    "ket thuc": CLASS_STATUS_COMPLETED,
    "huỷ": CLASS_STATUS_CANCELLED,
    "hủy": CLASS_STATUS_CANCELLED,
    "huy": CLASS_STATUS_CANCELLED,
}


@dataclass
class ClassEntity:
    id: str
    class_code: str
    program_id: str
    expected_start_date: date | str | None
    max_capacity: int
    learning_mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    program_code: str | None = None
    program_name: str | None = None
    enrolled_count: int = 0
    session_progress: str | None = None

    def to_dict(self) -> dict[str, Any]:
        start_date_str = None
        if self.expected_start_date:
            if isinstance(self.expected_start_date, (datetime, date)):
                start_date_str = self.expected_start_date.strftime("%Y-%m-%d")
            else:
                start_date_str = str(self.expected_start_date)

        return {
            "id": self.id,
            "class_code": self.class_code,
            "program_id": self.program_id,
            "program_code": self.program_code,
            "program_name": self.program_name,
            "expected_start_date": start_date_str,
            "max_capacity": self.max_capacity,
            "learning_mode": self.learning_mode,
            "status": self.status,
            "status_label": CLASS_STATUS_LABELS.get(self.status, self.status),
            "enrolled_count": self.enrolled_count,
            "session_progress": self.session_progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class ClassSubject:
    id: str
    class_id: str
    subject_id: str
    semester: int | None
    is_mandatory: bool
    order_index: int
    created_at: datetime
    updated_at: datetime
    subject_code: str | None = None
    subject_name: str | None = None
    credits: int | None = None
    main_instructor: dict | None = None
    assistants: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "class_id": self.class_id,
            "subject_id": self.subject_id,
            "subject_code": self.subject_code,
            "subject_name": self.subject_name,
            "credits": self.credits,
            "semester": self.semester,
            "is_mandatory": self.is_mandatory,
            "order_index": self.order_index,
            "main_instructor": self.main_instructor,
            "assistants": self.assistants or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
