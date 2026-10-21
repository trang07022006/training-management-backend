"""
Model thực thể Buổi học trong thời khóa biểu lớp học (ClassSchedule) - SCRUM-224.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any


@dataclass
class ClassSchedule:
    id: str
    class_id: str
    session_number: int
    topic: str
    learning_date: date | str
    start_time: time | str
    end_time: time | str
    class_subject_id: str | None = None
    subject_id: str | None = None
    subject_session_id: str | None = None
    shift: str | None = None
    room_id: str | None = None
    instructor_id: str | None = None
    status: str = "scheduled"
    cancellation_reason: str | None = None
    attendance_checked: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    instructor_name: str | None = None
    instructor_email: str | None = None
    room_name: str | None = None
    room_code: str | None = None
    classroom_id: str | None = None
    room_type: str | None = None
    online_link: str | None = None
    is_online: bool = False
    online_url: str | None = None
    is_legacy_room: bool = False
    legacy_room_raw: str | None = None
    subject_name: str | None = None
    subject_code: str | None = None
    class_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        date_str = None
        if self.learning_date:
            if isinstance(self.learning_date, (datetime, date)):
                date_str = self.learning_date.strftime("%Y-%m-%d")
            else:
                date_str = str(self.learning_date)

        start_time_str = None
        if self.start_time:
            if isinstance(self.start_time, (datetime, time)):
                start_time_str = self.start_time.strftime("%H:%M:%S")
            else:
                start_time_str = str(self.start_time)

        end_time_str = None
        if self.end_time:
            if isinstance(self.end_time, (datetime, time)):
                end_time_str = self.end_time.strftime("%H:%M:%S")
            else:
                end_time_str = str(self.end_time)

        return {
            "id": self.id,
            "class_id": self.class_id,
            "class_code": self.class_code,
            "class_subject_id": self.class_subject_id,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "subject_code": self.subject_code,
            "subject_session_id": self.subject_session_id,
            "session_number": self.session_number,
            "topic": self.topic,
            "learning_date": date_str,
            "shift": self.shift,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "room_id": self.room_id,
            "room_code": self.room_code,
            "classroom_id": self.classroom_id,
            "room_name": self.room_name,
            "room_type": self.room_type,
            "online_link": self.online_link,
            "is_online": self.is_online,
            "online_url": self.online_url,
            "is_legacy_room": self.is_legacy_room,
            "legacy_room_raw": self.legacy_room_raw,
            "instructor_id": self.instructor_id,
            "instructor_name": self.instructor_name,
            "instructor_email": self.instructor_email,
            "status": self.status,
            "cancellation_reason": self.cancellation_reason,
            "attendance_checked": bool(self.attendance_checked),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
