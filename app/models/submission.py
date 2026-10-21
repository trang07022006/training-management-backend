"""
Model cho Bài nộp và Nhật ký sửa điểm - SCRUM-267.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _fmt(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.isoformat() if isinstance(dt, datetime) else str(dt)


@dataclass
class AssignmentSubmission:
    """
    Bài nộp của học viên cho một bài tập (SCRUM-267).
    """
    id: str
    assignment_id: str
    student_id: str
    submission_type: str = "both"  # 'file', 'repo_url', 'both'
    file_url: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    repo_url: str | None = None
    note: str | None = None
    submitted_at: datetime | None = None
    status: str = "submitted"  # 'submitted', 'graded', 'returned'
    score: float | None = None
    feedback: str | None = None
    graded_by: str | None = None
    graded_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Joined fields
    student_code: str | None = None
    student_name: str | None = None
    student_email: str | None = None
    assignment_title: str | None = None
    assignment_max_score: float = 10.0
    assignment_is_published: bool = False
    graded_by_name: str | None = None

    def to_dict(self, is_student_view: bool = False) -> dict[str, Any]:
        """
        Nếu is_student_view=True và chưa công bố (is_published=False):
        Ẩn điểm số và feedback để tuân thủ Acceptance Criteria:
        "Điểm chỉ hiển thị cho học viên sau khi giảng viên bấm Công bố".
        """
        show_grade = not is_student_view or self.assignment_is_published

        return {
            "id": self.id,
            "assignment_id": self.assignment_id,
            "student_id": self.student_id,
            "student_code": self.student_code,
            "student_name": self.student_name,
            "student_email": self.student_email,
            "submission_type": self.submission_type,
            "file_url": self.file_url,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "repo_url": self.repo_url,
            "note": self.note,
            "submitted_at": _fmt(self.submitted_at),
            "status": self.status,
            "score": float(self.score) if (show_grade and self.score is not None) else None,
            "feedback": self.feedback if show_grade else None,
            "is_graded": self.score is not None,
            "is_published": bool(self.assignment_is_published),
            "graded_by_name": self.graded_by_name if show_grade else None,
            "graded_at": _fmt(self.graded_at) if show_grade else None,
            "assignment_title": self.assignment_title,
            "assignment_max_score": float(self.assignment_max_score),
            "created_at": _fmt(self.created_at),
            "updated_at": _fmt(self.updated_at),
        }


@dataclass
class SubmissionGradeAuditLog:
    """
    Nhật ký ghi lại mỗi lần sửa điểm (SCRUM-267).
    """
    id: str
    submission_id: str
    performed_by: str
    old_score: float | None
    new_score: float
    old_feedback: str | None = None
    new_feedback: str | None = None
    change_reason: str | None = None
    created_at: datetime | None = None
    performer_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "submission_id": self.submission_id,
            "performed_by": self.performed_by,
            "performer_name": self.performer_name,
            "old_score": float(self.old_score) if self.old_score is not None else None,
            "new_score": float(self.new_score),
            "old_feedback": self.old_feedback,
            "new_feedback": self.new_feedback,
            "change_reason": self.change_reason,
            "created_at": _fmt(self.created_at),
        }
