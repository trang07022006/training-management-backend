"""
Repository truy vấn và quản lý dữ liệu Điểm danh buổi học (SCRUM-254).
"""

import logging
from typing import Any, Optional
from mysql.connector import Error as MySQLError

from app.database.connection import get_db_connection
from app.models.session_attendance import AttendanceAuditLog, SessionAttendance

logger = logging.getLogger(__name__)


def get_schedule_details_for_attendance(schedule_id: str) -> Optional[dict[str, Any]]:
    """
    Truy vấn thông tin chi tiết của một buổi học để phục vụ giao diện điểm danh:
    Bao gồm thông tin lớp học, môn học, phòng học, giảng viên phụ trách, trạng thái và cờ attendance_checked.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
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
                    cs.updated_at,
                    c.class_code,
                    c.class_code AS class_name,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    cr.room_name AS room_name,
                    u.name AS instructor_name,
                    u.email AS instructor_email
                FROM class_schedules cs
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON cs.room_id = cr.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                WHERE cs.id = %s
                """,
                (schedule_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Chuyển đổi định dạng start_time, end_time, learning_date nếu cần
            learning_date = row["learning_date"]
            row["learning_date_str"] = learning_date.isoformat() if learning_date else None

            start_time = row["start_time"]
            end_time = row["end_time"]
            row["start_time_str"] = str(start_time) if start_time else None
            row["end_time_str"] = str(end_time) if end_time else None
            row["attendance_checked"] = bool(row.get("attendance_checked", False))
            return row
    finally:
        conn.close()


def is_trainer_assigned_to_session(user_id: str, schedule_id: str) -> bool:
    """
    Kiểm tra giảng viên (user_id) có thuộc phân công của buổi học hay không.
    Điều kiện hợp lệ:
    1. Giảng viên trực tiếp được gán trên buổi học (cs.instructor_id = user_id).
    2. Hoặc giảng viên được phân công cho môn học của lớp đó (class_subject_instructors).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM class_schedules cs
                WHERE cs.id = %s
                  AND (
                      cs.instructor_id = %s
                      OR EXISTS (
                          SELECT 1 FROM class_subject_instructors csi
                          WHERE csi.class_subject_id = cs.class_subject_id
                            AND csi.instructor_id = %s
                      )
                  )
                LIMIT 1
                """,
                (schedule_id, user_id, user_id),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def get_session_attendances(schedule_id: str) -> list[dict[str, Any]]:
    """
    Lấy danh sách các bản ghi điểm danh hiện có của buổi học.
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
                    sa.created_at,
                    sa.updated_at,
                    u.name AS recorded_by_name
                FROM session_attendances sa
                LEFT JOIN users u ON sa.recorded_by = u.id
                WHERE sa.schedule_id = %s
                """,
                (schedule_id,),
            )
            return cursor.fetchall() or []
    finally:
        conn.close()


def get_attendance_audit_logs(schedule_id: str) -> list[dict[str, Any]]:
    """
    Lấy danh sách lịch sử chỉnh sửa điểm danh của buổi học (phục vụ kiểm toán).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    aal.id,
                    aal.schedule_id,
                    aal.student_id,
                    aal.old_status,
                    aal.new_status,
                    aal.reason,
                    aal.performed_by,
                    aal.created_at,
                    s.student_code,
                    s.full_name AS student_name,
                    u.name AS performer_name,
                    u.email AS performer_email
                FROM attendance_audit_logs aal
                JOIN students s ON aal.student_id = s.id
                JOIN users u ON aal.performed_by = u.id
                WHERE aal.schedule_id = %s
                ORDER BY aal.created_at DESC
                """,
                (schedule_id,),
            )
            return cursor.fetchall() or []
    finally:
        conn.close()
