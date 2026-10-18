"""
Repository truy xuất cơ sở dữ liệu cho Vòng đời học viên (Student Lifecycle Repository) - SCRUM-252.
Thực hiện các thao tác nguyên tử với Transaction và FOR UPDATE để đảm bảo tính toàn vẹn dữ liệu.
"""

from datetime import date, datetime
import logging
from typing import Any
import uuid

from mysql.connector import Error as MySQLError

from app.database.connection import get_db_connection
from app.models.student_lifecycle_history import StudentLifecycleHistory

logger = logging.getLogger(__name__)


def get_enrollment_by_class_and_student(class_id: str, student_id: str) -> dict[str, Any] | None:
    """Truy vấn thông tin ghi danh cụ thể của học viên trong một lớp."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT ce.*, c.class_code, c.status AS class_status, c.expected_start_date,
                       c.program_id, tp.code AS program_code, tp.name AS program_name
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE ce.class_id = %s AND ce.student_id = %s
                """,
                (class_id, student_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_student_active_enrollments(student_id: str) -> list[dict[str, Any]]:
    """Lấy danh sách các lớp học đang tham gia của học viên."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT ce.*, c.class_code, c.status AS class_status, c.expected_start_date,
                       c.program_id, tp.code AS program_code, tp.name AS program_name
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE ce.student_id = %s
                ORDER BY ce.enrolled_at DESC
                """,
                (student_id,),
            )
            return cursor.fetchall() or []
    finally:
        conn.close()


def record_reservation_atomic(
    student_id: str,
    class_id: str,
    effective_date_val: date,
    reason: str,
    actor_id: str,
) -> dict[str, Any]:
    """
    Thực hiện bảo lưu học viên trong một lớp học với Transaction nguyên tử (SCRUM-252 - Lát cắt 252.1).
    - Khóa bản ghi ghi danh bằng SELECT ... FOR UPDATE.
    - Cập nhật class_enrollments (lifecycle_status='reserved', effective_date, lifecycle_reason).
    - Lưu lịch sử vào student_lifecycle_history.
    - Nếu effective_date <= CURRENT_DATE: trạng thái áp dụng ngay ('applied', status='reserved').
    - Nếu effective_date > CURRENT_DATE: trạng thái chờ ('pending', status='enrolled').
    """
    today = date.today()
    is_immediate = effective_date_val <= today
    history_status = "applied" if is_immediate else "pending"
    enrollment_status = "reserved" if is_immediate else "enrolled"
    history_id = str(uuid.uuid4())

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # 1. Khóa hàng ghi danh để chống thao tác đồng thời
            cursor.execute(
                """
                SELECT id, status, lifecycle_status, effective_date 
                FROM class_enrollments 
                WHERE class_id = %s AND student_id = %s 
                FOR UPDATE
                """,
                (class_id, student_id),
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("ENROLLMENT_NOT_FOUND: Học viên chưa được ghi danh vào lớp học này.")

            # Kiểm tra trạng thái hiện tại
            curr_lifecycle = row.get("lifecycle_status")
            if curr_lifecycle == "reserved":
                raise RuntimeError("ALREADY_RESERVED: Học viên đã được bảo lưu ở lớp học này.")
            if curr_lifecycle in ("transferred", "dropped"):
                raise RuntimeError(f"INVALID_LIFECYCLE_STATE: Học viên đang ở trạng thái {curr_lifecycle}, không thể bảo lưu.")

            enrollment_id = row["id"]

            # 2. Cập nhật class_enrollments
            cursor.execute(
                """
                UPDATE class_enrollments
                SET lifecycle_status = 'reserved',
                    effective_date = %s,
                    lifecycle_reason = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (effective_date_val, reason, enrollment_status, enrollment_id),
            )

            # 3. Ghi vào bảng lịch sử student_lifecycle_history
            cursor.execute(
                """
                INSERT INTO student_lifecycle_history (
                    id, student_id, enrollment_id, action_type,
                    source_class_id, target_class_id, effective_date,
                    reason, status, performed_by, created_at, updated_at
                )
                VALUES (%s, %s, %s, 'reserve', %s, NULL, %s, %s, %s, %s, NOW(), NOW())
                """,
                (
                    history_id,
                    student_id,
                    enrollment_id,
                    class_id,
                    effective_date_val,
                    reason,
                    history_status,
                    actor_id,
                ),
            )

            conn.commit()

            return {
                "history_id": history_id,
                "student_id": student_id,
                "enrollment_id": enrollment_id,
                "class_id": class_id,
                "action_type": "reserve",
                "effective_date": effective_date_val.isoformat(),
                "reason": reason,
                "status": history_status,
                "enrollment_status": enrollment_status,
            }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_eligible_attendance_students(class_id: str, session_date_val: date) -> list[dict[str, Any]]:
    """
    Truy vấn danh sách học viên đủ điều kiện điểm danh cho một buổi học cụ thể (SCRUM-252 AC 2).
    Quy tắc nghiệp vụ:
    - Học viên phải được ghi danh vào hoặc trước ngày diễn ra buổi học (DATE(enrolled_at) <= session_date).
    - Học viên chưa có lifecycle exit, HOẶC ngày hiệu lực của bảo lưu/chuyển lớp/thôi học diễn ra SAU ngày buổi học.
    - Từ ngày hiệu lực (session_date >= effective_date): học viên KHÔNG nằm trong danh sách điểm danh.
    - Trước ngày hiệu lực (session_date < effective_date): học viên VẪN nằm trong danh sách điểm danh.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    ce.id AS enrollment_id,
                    ce.class_id,
                    ce.student_id,
                    ce.status AS enrollment_status,
                    ce.lifecycle_status,
                    ce.effective_date,
                    ce.enrolled_at,
                    s.student_code,
                    s.full_name,
                    s.email,
                    s.phone
                FROM class_enrollments ce
                JOIN students s ON ce.student_id = s.id
                WHERE ce.class_id = %s
                  AND DATE(ce.enrolled_at) <= %s
                  AND (
                      ce.lifecycle_status IS NULL
                      OR ce.lifecycle_status NOT IN ('reserved', 'transferred', 'dropped')
                      OR ce.effective_date > %s
                  )
                ORDER BY s.student_code ASC
                """,
                (class_id, session_date_val, session_date_val),
            )
            return cursor.fetchall() or []
    finally:
        conn.close()


def get_student_lifecycle_history(student_id: str) -> list[StudentLifecycleHistory]:
    """Lấy toàn bộ lịch sử biến động vòng đời của một học viên."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    slh.*,
                    s.full_name AS student_name,
                    s.student_code,
                    sc.class_code AS source_class_code,
                    tc.class_code AS target_class_code,
                    u.name AS performer_name,
                    u.email AS performer_email
                FROM student_lifecycle_history slh
                JOIN students s ON slh.student_id = s.id
                LEFT JOIN classes sc ON slh.source_class_id = sc.id
                LEFT JOIN classes tc ON slh.target_class_id = tc.id
                LEFT JOIN users u ON slh.performed_by = u.id
                WHERE slh.student_id = %s
                ORDER BY slh.created_at DESC, slh.effective_date DESC
                """,
                (student_id,),
            )
            rows = cursor.fetchall() or []
            return [
                StudentLifecycleHistory(
                    id=r["id"],
                    student_id=r["student_id"],
                    enrollment_id=r["enrollment_id"],
                    action_type=r["action_type"],
                    source_class_id=r["source_class_id"],
                    target_class_id=r["target_class_id"],
                    effective_date=r["effective_date"],
                    reason=r["reason"],
                    status=r["status"],
                    performed_by=r["performed_by"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    student_name=r.get("student_name"),
                    student_code=r.get("student_code"),
                    source_class_code=r.get("source_class_code"),
                    target_class_code=r.get("target_class_code"),
                    performer_name=r.get("performer_name"),
                    performer_email=r.get("performer_email"),
                )
                for r in rows
            ]
    finally:
        conn.close()
