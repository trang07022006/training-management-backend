"""
Kho lưu trữ dữ liệu Student (Student Repository) - SCRUM-215.
Cung cấp các hàm tương tác cơ sở dữ liệu cho bảng students.
"""

from datetime import datetime, timezone
import logging
from app.database.connection import get_db_connection
from app.models.student import Student

logger = logging.getLogger(__name__)


def generate_next_student_code(prefix: str = "STU") -> str:
    """
    Tự động sinh mã học viên kỹ thuật tối thiểu duy nhất (SCRUM-215 - Sub-task 215-02).
    Format kỹ thuật: STU + 6 chữ số thứ tự (ví dụ: STU000001, STU000002).
    Đảm bảo an toàn concurrency và tránh collision qua atomic sequence counter & database unique constraint.
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # Đảm bảo bảng sequence tồn tại
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS student_code_sequences (
                    prefix VARCHAR(20) NOT NULL PRIMARY KEY,
                    current_val INT UNSIGNED NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            # Kiểm tra và khởi tạo sequence counter đồng bộ từ MAX(student_code)
            cursor.execute(
                "SELECT current_val FROM student_code_sequences WHERE prefix = %s FOR UPDATE",
                (prefix,),
            )
            row = cursor.fetchone()
            if row is None:
                # Quét mã lớn nhất hiện có trong students để tránh trùng nếu bảng đã có dữ liệu
                cursor.execute(
                    "SELECT student_code FROM students WHERE student_code LIKE %s ORDER BY student_code DESC LIMIT 1",
                    (f"{prefix}%",),
                )
                max_row = cursor.fetchone()
                current_max = 0
                if max_row and max_row[0]:
                    raw_code = str(max_row[0])
                    digits = raw_code[len(prefix):]
                    if digits.isdigit():
                        current_max = int(digits)

                cursor.execute(
                    "INSERT INTO student_code_sequences (prefix, current_val) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE current_val = current_val",
                    (prefix, current_max),
                )

            # Atomic increment an toàn tuyệt đối với LAST_INSERT_ID
            cursor.execute(
                "UPDATE student_code_sequences SET current_val = LAST_INSERT_ID(current_val + 1) WHERE prefix = %s",
                (prefix,),
            )
            connection.commit()

            cursor.execute("SELECT LAST_INSERT_ID()")
            next_seq_row = cursor.fetchone()
            next_seq = next_seq_row[0] if next_seq_row else 1

            return f"{prefix}{next_seq:06d}"
    finally:
        connection.close()


def create_student(student: Student) -> Student:
    """
    Tạo bản ghi học viên mới trong database.
    """
    now = datetime.now(timezone.utc)
    if not student.created_at:
        student.created_at = now
    if not student.updated_at:
        student.updated_at = now

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            insert_sql = """
                INSERT INTO students (
                    id, student_code, user_id, lead_id,
                    full_name, phone, email, program_id,
                    status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(
                insert_sql,
                (
                    student.id,
                    student.student_code,
                    student.user_id,
                    student.lead_id,
                    student.full_name,
                    student.phone,
                    student.email,
                    student.program_id,
                    student.status,
                    student.created_at,
                    student.updated_at,
                ),
            )
            connection.commit()
            return student
    finally:
        connection.close()


def get_student_by_id(student_id: str) -> Student | None:
    """Lấy thông tin học viên theo ID."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    s.id, s.student_code, s.user_id, s.lead_id,
                    s.full_name, s.phone, s.email, s.program_id,
                    s.status, s.created_at, s.updated_at,
                    tp.code AS program_code, tp.name AS program_name
                FROM students s
                LEFT JOIN training_programs tp ON s.program_id = tp.id
                WHERE s.id = %s
            """
            cursor.execute(sql, (student_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Student(
                id=row[0],
                student_code=row[1],
                user_id=row[2],
                lead_id=row[3],
                full_name=row[4],
                phone=row[5],
                email=row[6],
                program_id=row[7],
                status=row[8],
                created_at=row[9],
                updated_at=row[10],
                program_code=row[11],
                program_name=row[12],
            )
    finally:
        connection.close()


def get_student_by_lead_id(lead_id: str) -> Student | None:
    """Lấy thông tin học viên theo lead_id (dùng để kiểm tra duplicate conversion)."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    s.id, s.student_code, s.user_id, s.lead_id,
                    s.full_name, s.phone, s.email, s.program_id,
                    s.status, s.created_at, s.updated_at,
                    tp.code AS program_code, tp.name AS program_name
                FROM students s
                LEFT JOIN training_programs tp ON s.program_id = tp.id
                WHERE s.lead_id = %s
            """
            cursor.execute(sql, (lead_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Student(
                id=row[0],
                student_code=row[1],
                user_id=row[2],
                lead_id=row[3],
                full_name=row[4],
                phone=row[5],
                email=row[6],
                program_id=row[7],
                status=row[8],
                created_at=row[9],
                updated_at=row[10],
                program_code=row[11],
                program_name=row[12],
            )
    finally:
        connection.close()


def get_student_by_code(student_code: str) -> Student | None:
    """Lấy thông tin học viên theo mã học viên."""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    s.id, s.student_code, s.user_id, s.lead_id,
                    s.full_name, s.phone, s.email, s.program_id,
                    s.status, s.created_at, s.updated_at,
                    tp.code AS program_code, tp.name AS program_name
                FROM students s
                LEFT JOIN training_programs tp ON s.program_id = tp.id
                WHERE s.student_code = %s
            """
            cursor.execute(sql, (student_code,))
            row = cursor.fetchone()
            if not row:
                return None
            return Student(
                id=row[0],
                student_code=row[1],
                user_id=row[2],
                lead_id=row[3],
                full_name=row[4],
                phone=row[5],
                email=row[6],
                program_id=row[7],
                status=row[8],
                created_at=row[9],
                updated_at=row[10],
                program_code=row[11],
                program_name=row[12],
            )
    finally:
        connection.close()
