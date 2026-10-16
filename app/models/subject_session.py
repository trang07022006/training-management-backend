"""
Model thực thể SubjectSession (Buổi học của môn học) - SCRUM-129.
Được mapping từ prototype:
Lesson(STT, Topic, Objective, SubjectId) -> SubjectSession(session_number, topic, objective, subject_id).
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SubjectSession:
    """
    Đại diện cho một buổi học của một môn học (SCRUM-129 - Activity A1).
    Ràng buộc toàn vẹn:
    - session_number >= 1
    - unique (subject_id, session_number)
    - nếu môn học có total_sessions, session_number <= total_sessions
    """

    id: str
    subject_id: str
    session_number: int
    topic: str
    objective: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        """Chuyển đổi thực thể SubjectSession thành dictionary an toàn cho JSON serialization."""
        return {
            "id": self.id,
            "subject_id": self.subject_id,
            "session_number": self.session_number,
            "topic": self.topic,
            "objective": self.objective,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
