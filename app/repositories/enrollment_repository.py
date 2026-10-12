"""
Repository truy xuất cơ sở dữ liệu cho Ghi danh (Enrollment Repository) - SCRUM-218.
"""

from datetime import datetime
import logging
from mysql.connector import Error as MySQLError

from app.database.connection import get_db_connection
from app.models.enrollment import Enrollment

logger = logging.getLogger(__name__)


def count_enrollments_by_class_id(class_id: str) -> int:
    """Đếm tổng số học viên đã ghi danh vào một lớp học."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM class_enrollments WHERE class_id = %s",
                (class_id,),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)
    finally:
        conn.close()


def is_student_enrolled_in_class(class_id: str, student_id: str) -> bool:
    """Kiểm tra một học viên đã ghi danh vào lớp hay chưa."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM class_enrollments WHERE class_id = %s AND student_id = %s",
                (class_id, student_id),
            )
            row = cursor.fetchone()
            return bool(row and row[0] > 0)
    finally:
        conn.close()


def get_already_enrolled_student_ids(class_id: str, student_ids: list[str]) -> list[str]:
    """Lấy danh sách các student_id trong student_ids đã được ghi danh vào lớp."""
    if not student_ids:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(student_ids))
            query = f"""
                SELECT student_id FROM class_enrollments
                WHERE class_id = %s AND student_id IN ({placeholders})
            """
            cursor.execute(query, [class_id] + student_ids)
            rows = cursor.fetchall()
            return [r[0] for r in rows]
    finally:
        conn.close()


def create_enrollments(enrollments: list[Enrollment]) -> list[Enrollment]:
    """
    Ghi danh học viên vào lớp theo cơ chế transaction All-or-Nothing.
    Nếu bất kỳ bản ghi nào lỗi, rollback toàn bộ và raise exception.
    """
    if not enrollments:
        return []

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            for item in enrollments:
                cursor.execute(
                    """
                    INSERT INTO class_enrollments (
                        id, class_id, student_id, status,
                        enrolled_at, enrolled_by, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item.id,
                        item.class_id,
                        item.student_id,
                        item.status,
                        item.enrolled_at,
                        item.enrolled_by,
                        item.created_at,
                        item.updated_at,
                    ),
                )
            conn.commit()
            return enrollments
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_enrollments_by_class_id(class_id: str) -> list[Enrollment]:
    """Lấy danh sách học viên đã ghi danh trong một lớp học kèm thông tin người thực hiện và học viên."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    ce.*,
                    s.student_code,
                    s.full_name,
                    s.email,
                    s.phone,
                    s.status AS student_status,
                    c.class_code,
                    u.name AS enrolled_by_name,
                    u.email AS enrolled_by_email
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                JOIN students s ON ce.student_id = s.id
                LEFT JOIN users u ON ce.enrolled_by = u.id
                WHERE ce.class_id = %s
                ORDER BY ce.enrolled_at ASC
                """,
                (class_id,),
            )
            rows = cursor.fetchall()
            return [
                Enrollment(
                    id=r["id"],
                    class_id=r["class_id"],
                    student_id=r["student_id"],
                    status=r["status"],
                    enrolled_at=r["enrolled_at"],
                    enrolled_by=r["enrolled_by"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    student_code=r["student_code"],
                    full_name=r["full_name"],
                    email=r["email"],
                    phone=r["phone"],
                    student_status=r["student_status"],
                    class_code=r["class_code"],
                    enrolled_by_name=r.get("enrolled_by_name"),
                    enrolled_by_email=r.get("enrolled_by_email"),
                )
                for r in rows
            ]
    finally:
        conn.close()


def delete_enrollments_for_testing(class_id: str) -> None:
    """Hàm dọn dẹp dữ liệu test cho một lớp."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM class_enrollments WHERE class_id = %s", (class_id,))
            conn.commit()
    finally:
        conn.close()
