from dataclasses import dataclass
from datetime import datetime


PROGRAM_STATUS_DRAFT = "draft"
PROGRAM_STATUS_ACTIVE = "active"
PROGRAM_STATUS_ARCHIVED = "archived"
VALID_PROGRAM_STATUSES = {
    PROGRAM_STATUS_DRAFT,
    PROGRAM_STATUS_ACTIVE,
    PROGRAM_STATUS_ARCHIVED,
}


@dataclass
class TrainingProgram:
    """
    Đại diện cho một chương trình đào tạo (SCRUM-122 - Activity A1).
    Là thực thể khung độc lập, làm nền tảng cho môn học (SCRUM-123)
    và cấu trúc chương trình đào tạo (SCRUM-124).
    """

    id: str
    code: str
    name: str
    description: str | None = None
    duration_semesters: int | None = None
    standard_tuition_fee: int | None = None
    absence_alert_threshold: float = 20.0
    status: str = PROGRAM_STATUS_DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        """Chuyển đổi thực thể TrainingProgram thành dictionary an toàn cho JSON serialization."""
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "duration_semesters": self.duration_semesters,
            "standard_tuition_fee": self.standard_tuition_fee,
            "absence_alert_threshold": float(self.absence_alert_threshold) if self.absence_alert_threshold is not None else 20.0,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
