"""
Model thực thể RubricTemplate và RubricCriteria - SCRUM-268.

Liên kết với project:
  - rubric_templates.created_by  -> users.id
  - rubric_criteria.template_id  -> rubric_templates.id (CASCADE DELETE)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RubricCriteria:
    """
    Một tiêu chí chấm điểm trong rubric (SCRUM-268).
    Ràng buộc nghiệp vụ:
    - 0 < weight <= 100
    - Tổng weight của tất cả criteria trong cùng template = 100
    - max_score > 0
    """

    id: str
    template_id: str
    name: str
    weight: float           # Trọng số % (0 < weight <= 100)
    max_score: float        # Điểm tối đa cho tiêu chí này
    order_index: int = 0
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "max_score": float(self.max_score),
            "weight": float(self.weight),
            "order_index": self.order_index,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class RubricTemplate:
    """
    Mẫu rubric chấm điểm - lưu để dùng lại cho nhiều bài tập (SCRUM-268).
    Liên kết: created_by -> users.id
    """

    id: str
    name: str
    created_by: str
    description: str | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    criteria: list[RubricCriteria] = field(default_factory=list)

    def to_dict(self, include_criteria: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "is_deleted": bool(self.is_deleted),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_criteria:
            data["criteria"] = [c.to_dict() for c in self.criteria]
            data["total_weight"] = round(sum(c.weight for c in self.criteria), 2)
        return data
