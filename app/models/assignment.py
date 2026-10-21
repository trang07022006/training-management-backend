"""
Model thực thể Bài tập, Bài nộp, Lần nộp và Yêu cầu làm lại (Assignment Models) - SCRUM-269.
Quản lý vòng đời bài nộp:
Đã nộp (submitted) -> Giảng viên yêu cầu làm lại -> Cần làm lại (needs_rework)
-> Học viên gửi lần nộp mới -> Đã nộp lại (resubmitted) -> Giảng viên chấm điểm (graded) hoặc yêu cầu tiếp.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


SUBMISSION_STATUS_SUBMITTED = "submitted"
SUBMISSION_STATUS_GRADED = "graded"
SUBMISSION_STATUS_NEEDS_REWORK = "needs_rework"
SUBMISSION_STATUS_RESUBMITTED = "resubmitted"

SUBMISSION_STATUSES = [
    SUBMISSION_STATUS_SUBMITTED,
    SUBMISSION_STATUS_GRADED,
    SUBMISSION_STATUS_NEEDS_REWORK,
    SUBMISSION_STATUS_RESUBMITTED,
]

SUBMISSION_STATUS_LABELS = {
    SUBMISSION_STATUS_SUBMITTED: "Đã nộp",
    SUBMISSION_STATUS_GRADED: "Đã chấm",
    SUBMISSION_STATUS_NEEDS_REWORK: "Cần làm lại",
    SUBMISSION_STATUS_RESUBMITTED: "Đã nộp lại",
}

REWORK_STATUS_OPEN = "open"
REWORK_STATUS_FULFILLED = "fulfilled"
REWORK_STATUS_CANCELLED = "cancelled"

REWORK_STATUSES = [
    REWORK_STATUS_OPEN,
    REWORK_STATUS_FULFILLED,
    REWORK_STATUS_CANCELLED,
]


@dataclass
class Assignment:
    id: str
    class_id: str
    title: str
    description: str | None
    due_date: datetime | str | None
    max_score: float
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    class_code: str | None = None
    creator_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "class_id": self.class_id,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date.isoformat() if isinstance(self.due_date, datetime) else self.due_date,
            "max_score": float(self.max_score) if self.max_score is not None else 10.0,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "class_code": self.class_code,
            "creator_name": self.creator_name,
        }


@dataclass
class SubmissionVersion:
    id: str
    submission_id: str
    version_number: int
    submission_type: str
    submitted_at: datetime
    content: str | None = None
    file_url: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    repo_url: str | None = None
    rework_request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "submission_id": self.submission_id,
            "version_number": self.version_number,
            "submission_type": self.submission_type,
            "content": self.content,
            "file_url": self.file_url,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "repo_url": self.repo_url,
            "submitted_at": self.submitted_at.isoformat() if isinstance(self.submitted_at, datetime) else self.submitted_at,
            "rework_request_id": self.rework_request_id,
        }


@dataclass
class SubmissionReworkRequest:
    id: str
    submission_id: str
    submission_version_id: str | None
    request_number: int
    comment: str
    new_deadline: datetime
    requested_by: str
    status: str
    created_at: datetime
    fulfilled_at: datetime | None = None
    fulfilled_version_id: str | None = None
    requested_by_name: str | None = None
    fulfilled_version_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "submission_id": self.submission_id,
            "submission_version_id": self.submission_version_id,
            "request_number": self.request_number,
            "comment": self.comment,
            "new_deadline": self.new_deadline.isoformat() if isinstance(self.new_deadline, datetime) else self.new_deadline,
            "requested_by": self.requested_by,
            "requested_by_name": self.requested_by_name,
            "status": self.status,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "fulfilled_at": self.fulfilled_at.isoformat() if isinstance(self.fulfilled_at, datetime) else self.fulfilled_at,
            "fulfilled_version_id": self.fulfilled_version_id,
            "fulfilled_version_number": self.fulfilled_version_number,
        }


@dataclass
class AssignmentSubmission:
    id: str
    assignment_id: str
    student_id: str
    status: str
    score: float | None
    feedback: str | None
    graded_by: str | None
    graded_at: datetime | None
    rework_count: int
    created_at: datetime
    updated_at: datetime
    student_code: str | None = None
    student_name: str | None = None
    student_email: str | None = None
    assignment_title: str | None = None
    assignment_max_score: float | None = None
    current_rework_request: SubmissionReworkRequest | None = None
    rework_history: list[SubmissionReworkRequest] = field(default_factory=list)
    versions: list[SubmissionVersion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        latest_version = self.versions[-1] if self.versions else None
        return {
            "id": self.id,
            "assignment_id": self.assignment_id,
            "student_id": self.student_id,
            "student_code": self.student_code,
            "student_name": self.student_name,
            "student_email": self.student_email,
            "assignment_title": self.assignment_title,
            "assignment_max_score": float(self.assignment_max_score) if self.assignment_max_score is not None else 10.0,
            "status": self.status,
            "status_label": SUBMISSION_STATUS_LABELS.get(self.status, self.status),
            "score": float(self.score) if self.score is not None else None,
            "feedback": self.feedback,
            "graded_by": self.graded_by,
            "graded_at": self.graded_at.isoformat() if isinstance(self.graded_at, datetime) else self.graded_at,
            "rework_count": self.rework_count,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "submitted_at": latest_version.submitted_at.isoformat() if (latest_version and isinstance(latest_version.submitted_at, datetime)) else (latest_version.submitted_at if latest_version else None),
            "current_rework_request": self.current_rework_request.to_dict() if self.current_rework_request else None,
            "rework_history": [r.to_dict() for r in self.rework_history],
            "versions": [v.to_dict() for v in self.versions],
        }
