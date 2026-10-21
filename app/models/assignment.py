"""
Model thực thể Assignment, AssignmentGrade, AssignmentCriteriaGrade - SCRUM-268.

Liên kết với project:
  - assignments.class_id            -> classes.id
  - assignments.rubric_template_id  -> rubric_templates.id
  - assignments.created_by          -> users.id
  - assignment_grades.student_id    -> students.id
  - assignment_grades.graded_by     -> users.id
  - assignment_criteria_grades.criteria_id -> rubric_criteria.id
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _fmt(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.isoformat() if isinstance(dt, datetime) else str(dt)


@dataclass
class Assignment:
    """
    Bài tập / kiểm tra của lớp (SCRUM-268).
    Gắn với rubric_template để chấm điểm theo tiêu chí.
    """

    id: str
    class_id: str
    title: str
    created_by: str
    max_score: float = 10.0
    description: str | None = None
    rubric_template_id: str | None = None   # None = chấm thủ công
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Joined (không lưu DB)
    rubric_template_name: str | None = None
    class_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "class_id": self.class_id,
            "title": self.title,
            "description": self.description,
            "rubric_template_id": self.rubric_template_id,
            "rubric_template_name": self.rubric_template_name,
            "max_score": float(self.max_score),
            "created_by": self.created_by,
            "class_code": self.class_code,
            "created_at": _fmt(self.created_at),
            "updated_at": _fmt(self.updated_at),
        }


@dataclass
class AssignmentCriteriaGrade:
    """Điểm của học viên cho một tiêu chí rubric (SCRUM-268)."""

    id: str
    grade_id: str
    criteria_id: str
    score: float
    comment: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Joined từ rubric_criteria
    criteria_name: str | None = None
    criteria_weight: float | None = None
    criteria_max_score: float | None = None
    criteria_order_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "grade_id": self.grade_id,
            "criteria_id": self.criteria_id,
            "criteria_name": self.criteria_name,
            "criteria_weight": float(self.criteria_weight) if self.criteria_weight is not None else None,
            "criteria_max_score": float(self.criteria_max_score) if self.criteria_max_score is not None else None,
            "criteria_order_index": self.criteria_order_index,
            "score": float(self.score),
            "comment": self.comment,
            "created_at": _fmt(self.created_at),
            "updated_at": _fmt(self.updated_at),
        }


@dataclass
class AssignmentGrade:
    """
    Điểm tổng của học viên cho bài tập (SCRUM-268).
    total_score tính tự động = Σ(score_i / max_score_i * weight_i) / 10
    Học viên xem được điểm chi tiết từng tiêu chí.
    """

    id: str
    assignment_id: str
    student_id: str
    total_score: float | None = None        # None = chưa chấm xong
    graded_by: str | None = None
    graded_at: datetime | None = None
    feedback: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Joined
    student_code: str | None = None
    student_name: str | None = None
    graded_by_name: str | None = None
    criteria_grades: list[AssignmentCriteriaGrade] = field(default_factory=list)

    def to_dict(self, include_criteria: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "assignment_id": self.assignment_id,
            "student_id": self.student_id,
            "student_code": self.student_code,
            "student_name": self.student_name,
            "total_score": float(self.total_score) if self.total_score is not None else None,
            "graded_by": self.graded_by,
            "graded_by_name": self.graded_by_name,
            "graded_at": _fmt(self.graded_at),
            "feedback": self.feedback,
            "created_at": _fmt(self.created_at),
            "updated_at": _fmt(self.updated_at),
        }
        if include_criteria:
            data["criteria_grades"] = [cg.to_dict() for cg in self.criteria_grades]
        return data
