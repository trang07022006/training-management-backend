"""
Repository quản lý Thời khóa biểu lớp học (ClassSchedule Repository) - SCRUM-224.
"""

from datetime import datetime, timezone
import uuid
from app.database.connection import get_db_connection
from app.models.class_schedule import ClassSchedule


def insert_schedules_batch(schedules: list[ClassSchedule]) -> list[ClassSchedule]:
    """Lưu danh sách buổi học theo lô vào cơ sở dữ liệu (SCRUM-224)."""
    if not schedules:
        return []

    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        for s in schedules:
            if not s.id:
                s.id = str(uuid.uuid4())
            s.created_at = s.created_at or now
            s.updated_at = s.updated_at or now

        with conn.cursor() as cursor:
            sql = """
                INSERT INTO class_schedules (
                    id, class_id, class_subject_id, subject_id, subject_session_id,
                    session_number, topic, learning_date, shift, start_time, end_time,
                    room_id, instructor_id, status, cancellation_reason, attendance_checked,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """
            values = [
                (
                    s.id,
                    s.class_id,
                    s.class_subject_id,
                    s.subject_id,
                    s.subject_session_id,
                    s.session_number,
                    s.topic.strip(),
                    s.learning_date,
                    s.shift,
                    s.start_time,
                    s.end_time,
                    s.room_id,
                    s.instructor_id,
                    s.status,
                    s.cancellation_reason,
                    s.attendance_checked,
                    s.created_at,
                    s.updated_at,
                )
                for s in schedules
            ]
            cursor.executemany(sql, values)
            conn.commit()
        return schedules
    finally:
        conn.close()


def list_schedules_by_class_id(class_id: str) -> list[ClassSchedule]:
    """Lấy danh sách thời khóa biểu của một lớp, sắp xếp theo ngày học và giờ học."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, class_id, class_subject_id, subject_id, subject_session_id,
                       session_number, topic, learning_date, shift, start_time, end_time,
                       room_id, instructor_id, status, cancellation_reason, attendance_checked,
                       created_at, updated_at
                FROM class_schedules
                WHERE class_id = %s
                ORDER BY learning_date ASC, start_time ASC, session_number ASC
                """,
                (class_id,),
            )
            rows = cursor.fetchall()
            return [
                ClassSchedule(
                    id=r["id"],
                    class_id=r["class_id"],
                    class_subject_id=r["class_subject_id"],
                    subject_id=r["subject_id"],
                    subject_session_id=r["subject_session_id"],
                    session_number=r["session_number"],
                    topic=r["topic"],
                    learning_date=r["learning_date"],
                    shift=r["shift"],
                    start_time=r["start_time"],
                    end_time=r["end_time"],
                    room_id=r["room_id"],
                    instructor_id=r["instructor_id"],
                    status=r["status"],
                    cancellation_reason=r["cancellation_reason"],
                    attendance_checked=bool(r["attendance_checked"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
    finally:
        conn.close()


def get_schedule_by_id(schedule_id: str) -> ClassSchedule | None:
    """Lấy thông tin chi tiết một buổi học theo ID."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, class_id, class_subject_id, subject_id, subject_session_id,
                       session_number, topic, learning_date, shift, start_time, end_time,
                       room_id, instructor_id, status, cancellation_reason, attendance_checked,
                       created_at, updated_at
                FROM class_schedules
                WHERE id = %s
                """,
                (schedule_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return ClassSchedule(
                id=r["id"],
                class_id=r["class_id"],
                class_subject_id=r["class_subject_id"],
                subject_id=r["subject_id"],
                subject_session_id=r["subject_session_id"],
                session_number=r["session_number"],
                topic=r["topic"],
                learning_date=r["learning_date"],
                shift=r["shift"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                room_id=r["room_id"],
                instructor_id=r["instructor_id"],
                status=r["status"],
                cancellation_reason=r["cancellation_reason"],
                attendance_checked=bool(r["attendance_checked"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    finally:
        conn.close()


def count_schedules_by_class_id(class_id: str) -> int:
    """Đếm số buổi học đã xếp lịch của lớp."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM class_schedules WHERE class_id = %s", (class_id,))
            return cursor.fetchone()[0]
    finally:
        conn.close()


def delete_schedules_by_class_id(class_id: str) -> int:
    """Xóa thời khóa biểu của một lớp (dùng cho test hoặc tái xếp lịch)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM class_schedules WHERE class_id = %s", (class_id,))
            conn.commit()
            return cursor.rowcount
    finally:
        conn.close()
