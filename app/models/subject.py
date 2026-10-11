from dataclasses import dataclass
from datetime import datetime


SUBJECT_STATUS_DRAFT = "draft"
SUBJECT_STATUS_ACTIVE = "active"
SUBJECT_STATUS_ARCHIVED = "archived"
VALID_SUBJECT_STATUSES = {
    SUBJECT_STATUS_DRAFT,
    SUBJECT_STATUS_ACTIVE,
    SUBJECT_STATUS_ARCHIVED,
}

MIN_SUBJECT_CREDITS = 1
MAX_SUBJECT_CREDITS = 30


@dataclass
class Subject:
    """
    Đại diện cho một môn học/học phần trong hệ thống đào tạo (SCRUM-123 - Activity A1).
    Là thực thể danh mục độc lập, làm nền tảng cho cấu trúc chương trình đào tạo (SCRUM-124)
    và kế hoạch buổi học (SCRUM-129).
    """

    id: str
    code: str
    name: str
    credits: int
    description: str | None = None
    total_sessions: int | None = None
    weight: float | None = None
    learning_outcomes: str | None = None
    status: str = SUBJECT_STATUS_DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        """Chuyển đổi thực thể Subject thành dictionary an toàn cho JSON serialization."""
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "credits": self.credits,
            "description": self.description,
            "total_sessions": self.total_sessions,
            "weight": self.weight,
            "learning_outcomes": self.learning_outcomes,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
