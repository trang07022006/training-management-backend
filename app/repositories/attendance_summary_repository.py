"""
Repository truy vấn và tổng hợp dữ liệu Bảng chuyên cần lớp học (SCRUM-256).
Hỗ trợ ma trận học viên theo buổi học, tổng hợp số buổi vắng và tỷ lệ chuyên cần.
"""

from datetime import date, datetime, timedelta
import logging
from typing import Any, Optional

from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def get_class_details(class_id: str) -> Optional[dict[str, Any]]:
    """
    Truy vấn thông tin cơ bản của lớp học bao gồm mã lớp, chương trình và trạng thái.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    c.id,
                    c.class_code,
                    c.program_id,
                    c.expected_start_date,
                    c.max_capacity,
                    c.learning_mode,
                    c.status,
                    tp.code AS program_code,
                    tp.name AS program_name
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE c.id = %s
                """,
                (class_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            if row.get("expected_start_date"):
                row["expected_start_date_str"] = row["expected_start_date"].isoformat()
            return row
    finally:
        conn.close()


def is_trainer_assigned_to_class(user_id: str, class_id: str) -> bool:
    """
    Kiểm tra giảng viên (user_id) có thuộc phân công của lớp học hay không.
    Điều kiện hợp lệ:
    1. Giảng viên được phân công cho môn học của lớp đó (class_subject_instructors).
    2. Hoặc giảng viên trực tiếp được gán trên bất kỳ buổi học nào của lớp (class_schedules).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM classes c
                WHERE c.id = %s
                  AND (
                      EXISTS (
                          SELECT 1 FROM class_subjects cs
                          JOIN class_subject_instructors csi ON cs.id = csi.class_subject_id
                          WHERE cs.class_id = c.id AND csi.instructor_id = %s
                      )
                      OR EXISTS (
                          SELECT 1 FROM class_schedules sched
                          WHERE sched.class_id = c.id AND sched.instructor_id = %s
                      )
                  )
                LIMIT 1
                """,
                (class_id, user_id, user_id),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def get_class_schedules_for_summary(
    class_id: str,
    subject_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Lấy danh sách toàn bộ các buổi học thực tế của lớp theo thứ tự thời gian.
    Hai buổi cùng ngày là hai cột riêng, phân biệt bằng schedule_id và giờ học (AC1).
    Sắp xếp: learning_date ASC, start_time ASC, id ASC.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            query = """
                SELECT 
                    cs.id,
                    cs.class_id,
                    cs.class_subject_id,
                    cs.subject_id,
                    cs.subject_session_id,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    cs.room_id,
                    cs.instructor_id,
                    cs.status,
                    cs.cancellation_reason,
                    cs.attendance_checked,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    COALESCE(cr.room_name, cr.room_code, cs.room_id) AS room_name,
                    cr.room_code,
                    u.name AS instructor_name,
                    u.email AS instructor_email
                FROM class_schedules cs
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                LEFT JOIN users u ON cs.instructor_id = u.id
                WHERE cs.class_id = %s
            """
            params: list[Any] = [class_id]

            if subject_id:
                query += " AND cs.subject_id = %s"
                params.append(subject_id)

            query += " ORDER BY cs.learning_date ASC, cs.start_time ASC, cs.id ASC"

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall() or []

            # Format các trường thời gian
            for r in rows:
                learning_date = r.get("learning_date")
                r["learning_date_str"] = learning_date.isoformat() if learning_date else None

                start_time = r.get("start_time")
                end_time = r.get("end_time")
                r["start_time_str"] = str(start_time) if start_time else None
                r["end_time_str"] = str(end_time) if end_time else None
                r["attendance_checked"] = bool(r.get("attendance_checked", False))

            return rows
    finally:
        conn.close()


def get_enrolled_and_history_students(class_id: str) -> list[dict[str, Any]]:
    """
    Lấy danh sách tất cả học viên thuộc lớp (ghi danh hiện tại hoặc từng tham gia có lịch sử điểm danh).
    Bao gồm thông tin vòng đời (SCRUM-252) để xét điều kiện áp dụng tại từng buổi học.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT
                    s.id AS student_id,
                    s.student_code,
                    s.full_name,
                    s.email,
                    s.phone,
                    ce.id AS enrollment_id,
                    ce.enrolled_at,
                    ce.status AS enrollment_status,
                    ce.lifecycle_status,
                    ce.effective_date
                FROM students s
                LEFT JOIN class_enrollments ce ON s.id = ce.student_id AND ce.class_id = %s
                WHERE ce.class_id = %s
                   OR s.id IN (
                       SELECT DISTINCT sa.student_id
                       FROM session_attendances sa
                       JOIN class_schedules cs ON sa.schedule_id = cs.id
                       WHERE cs.class_id = %s
                   )
                ORDER BY s.student_code ASC, s.id ASC
                """,
                (class_id, class_id, class_id),
            )
            rows = cursor.fetchall() or []

            for r in rows:
                enrolled_at = r.get("enrolled_at")
                if enrolled_at:
                    if isinstance(enrolled_at, (datetime, date)):
                        r["enrolled_date"] = enrolled_at.date() if isinstance(enrolled_at, datetime) else enrolled_at
                        r["enrolled_at_str"] = enrolled_at.isoformat()
                    else:
                        r["enrolled_date"] = date.fromisoformat(str(enrolled_at)[:10])
                        r["enrolled_at_str"] = str(enrolled_at)
                else:
                    r["enrolled_date"] = None
                    r["enrolled_at_str"] = None

                effective_date = r.get("effective_date")
                if effective_date:
                    if isinstance(effective_date, (datetime, date)):
                        r["effective_date_val"] = effective_date.date() if isinstance(effective_date, datetime) else effective_date
                        r["effective_date_str"] = effective_date.isoformat()
                    else:
                        r["effective_date_val"] = date.fromisoformat(str(effective_date)[:10])
                        r["effective_date_str"] = str(effective_date)
                else:
                    r["effective_date_val"] = None
                    r["effective_date_str"] = None

            return rows
    finally:
        conn.close()


def get_class_attendances(class_id: str) -> list[dict[str, Any]]:
    """
    Truy vấn toàn bộ kết quả điểm danh hiện hành của các buổi học trong lớp (1 single batch query, chống N+1).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    sa.id,
                    sa.schedule_id,
                    sa.student_id,
                    sa.status,
                    sa.notes,
                    sa.recorded_by,
                    sa.updated_at
                FROM session_attendances sa
                JOIN class_schedules cs ON sa.schedule_id = cs.id
                WHERE cs.class_id = %s
                """,
                (class_id,),
            )
            return cursor.fetchall() or []
    finally:
        conn.close()
