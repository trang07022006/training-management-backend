"""
Kho lưu trữ dữ liệu Student (Student Repository) - SCRUM-215.
Cung cấp các hàm tương tác cơ sở dữ liệu cho bảng students.
"""

from datetime import datetime, timezone
import logging
from app.database.connection import get_db_connection
from app.models.student import Student

logger = logging.getLogger(__name__)


def generate_next_student_code(prefix: str = "HV") -> str:
    """
    Tự động sinh mã học viên duy nhất (SCRUM-215 - Sub-task 215-02).
    Quy tắc: HV + YYYY + 4 chữ số thứ tự (ví dụ: HV20260001, HV20260002).
    """
    year = datetime.now(timezone.utc).year
    search_pattern = f"{prefix}{year}%"

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT student_code FROM students
                WHERE student_code LIKE %s
                ORDER BY student_code DESC
                LIMIT 1
                FOR UPDATE
                """,
                (search_pattern,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                last_code = row[0]
                # Trích xuất phần số cuối
                seq_part = last_code[len(f"{prefix}{year}") :]
                try:
                    next_seq = int(seq_part) + 1
                except ValueError:
                    next_seq = 1
            else:
                next_seq = 1

            new_code = f"{prefix}{year}{next_seq:04d}"
            return new_code
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
