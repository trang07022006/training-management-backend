"""
Repository truy xuất cơ sở dữ liệu cho Lớp học (Class Repository) - SCRUM-217.
"""

from datetime import datetime, timezone
import logging
import uuid
from mysql.connector import Error as MySQLError

from app.database.connection import get_db_connection
from app.models.class_entity import ClassEntity, ClassSubject

logger = logging.getLogger(__name__)


def _row_to_class(row: dict) -> ClassEntity:
    return ClassEntity(
        id=row["id"],
        class_code=row["class_code"],
        program_id=row["program_id"],
        expected_start_date=row.get("expected_start_date"),
        max_capacity=int(row.get("max_capacity") or 30),
        learning_mode=row.get("learning_mode") or "offline",
        status=row.get("status") or "preparing",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        program_code=row.get("program_code"),
        program_name=row.get("program_name"),
        enrolled_count=int(row.get("enrolled_count") or 0),
    )


def create_class(entity: ClassEntity) -> ClassEntity:
    """Tạo mới một lớp học trong cơ sở dữ liệu."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO classes (
                    id, class_code, program_id, expected_start_date,
                    max_capacity, learning_mode, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entity.id,
                    entity.class_code,
                    entity.program_id,
                    entity.expected_start_date,
                    entity.max_capacity,
                    entity.learning_mode,
                    entity.status,
                    entity.created_at,
                    entity.updated_at,
                ),
            )
            conn.commit()
            return get_class_by_id(entity.id)
    finally:
        conn.close()


def get_class_by_id(class_id: str) -> ClassEntity | None:
    """Lấy thông tin lớp học theo ID."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT c.*, tp.code AS program_code, tp.name AS program_name,
                       (SELECT COUNT(*) FROM class_enrollments ce WHERE ce.class_id = c.id) AS enrolled_count
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE c.id = %s
                """,
                (class_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return _row_to_class(row)
    except MySQLError:
        # Nếu bảng class_enrollments chưa có (SCRUM-218)
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT c.*, tp.code AS program_code, tp.name AS program_name, 0 AS enrolled_count
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE c.id = %s
                """,
                (class_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return _row_to_class(row)
    finally:
        conn.close()


def get_class_by_code(class_code: str) -> ClassEntity | None:
    """Lấy thông tin lớp học theo mã lớp."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT c.*, tp.code AS program_code, tp.name AS program_name
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE c.class_code = %s
                """,
                (class_code.strip(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return _row_to_class(row)
    finally:
        conn.close()


def update_class_status(class_id: str, new_status: str) -> ClassEntity | None:
    """Cập nhật trạng thái vòng đời của lớp học."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE classes
                SET status = %s, updated_at = %s
                WHERE id = %s
                """,
                (new_status, datetime.now(timezone.utc), class_id),
            )
            conn.commit()
            return get_class_by_id(class_id)
    finally:
        conn.close()


def copy_program_subjects_to_class(class_id: str, program_id: str) -> int:
    """
    Sao chép danh sách môn học từ chương trình đào tạo sang lớp (SCRUM-217 - 217-04).
    Lấy toàn bộ môn học trong program_subjects và insert vào class_subjects.
    Không sửa đổi program gốc.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # 1. Đọc danh sách môn học từ program_subjects
            cursor.execute(
                """
                SELECT ps.subject_id, ps.semester, ps.is_mandatory, ps.order_index
                FROM program_subjects ps
                WHERE ps.program_id = %s
                ORDER BY ps.semester ASC, ps.order_index ASC
                """,
                (program_id,),
            )
            subjects = cursor.fetchall()
            if not subjects:
                return 0

            # 2. Sao chép vào class_subjects
            now = datetime.now(timezone.utc)
            copied_count = 0
            for item in subjects:
                cs_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO class_subjects (
                        id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)
                    """,
                    (
                        cs_id,
                        class_id,
                        item["subject_id"],
                        item["semester"],
                        item["is_mandatory"],
                        item["order_index"],
                        now,
                        now,
                    ),
                )
                copied_count += 1

            conn.commit()
            return copied_count
    finally:
        conn.close()


def get_class_subjects(class_id: str) -> list[ClassSubject]:
    """Lấy danh sách môn học đã sao chép của một lớp học kèm thông tin giảng viên/trợ giảng (SCRUM-217 & SCRUM-220)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT cs.*, s.code AS subject_code, s.name AS subject_name, s.credits
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.class_id = %s
                ORDER BY cs.semester ASC, cs.order_index ASC
                """,
                (class_id,),
            )
            rows = cursor.fetchall()

            # Lấy thông tin phân công giảng viên cho các môn của lớp nếu bảng tồn tại
            instructors_by_subject = {}
            try:
                cursor.execute(
                    """
                    SELECT csi.class_subject_id, csi.instructor_id, csi.role_type,
                           u.name AS instructor_name, u.email AS instructor_email, u.role AS instructor_role
                    FROM class_subject_instructors csi
                    JOIN users u ON csi.instructor_id = u.id
                    WHERE csi.class_subject_id IN (SELECT id FROM class_subjects WHERE class_id = %s)
                    ORDER BY csi.created_at ASC
                    """,
                    (class_id,),
                )
                csi_rows = cursor.fetchall()
                for r in csi_rows:
                    cs_id = r["class_subject_id"]
                    if cs_id not in instructors_by_subject:
                        instructors_by_subject[cs_id] = {"main": None, "assistants": []}
                    info = {
                        "id": r["instructor_id"],
                        "name": r["instructor_name"],
                        "email": r["instructor_email"],
                        "role": r["instructor_role"],
                    }
                    if r["role_type"] == "main":
                        instructors_by_subject[cs_id]["main"] = info
                    else:
                        instructors_by_subject[cs_id]["assistants"].append(info)
            except Exception:
                instructors_by_subject = {}

            return [
                ClassSubject(
                    id=row["id"],
                    class_id=row["class_id"],
                    subject_id=row["subject_id"],
                    semester=row["semester"],
                    is_mandatory=bool(row["is_mandatory"]),
                    order_index=row["order_index"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    subject_code=row["subject_code"],
                    subject_name=row["subject_name"],
                    credits=row["credits"],
                    main_instructor=instructors_by_subject.get(row["id"], {}).get("main"),
                    assistants=instructors_by_subject.get(row["id"], {}).get("assistants", []),
                )
                for row in rows
            ]
    finally:
        conn.close()


def get_class_subject_by_id(class_subject_id: str) -> dict | None:
    """Lấy thông tin một môn học của lớp theo ID (SCRUM-220)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT cs.*, s.code AS subject_code, s.name AS subject_name, s.credits
                FROM class_subjects cs
                JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.id = %s
                """,
                (class_subject_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_class_subject_instructors(class_subject_id: str) -> list[dict]:
    """Lấy danh sách giảng viên chính và trợ giảng đã phân công cho môn học (SCRUM-220)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT csi.id, csi.class_subject_id, csi.instructor_id, csi.role_type,
                       csi.created_at, csi.updated_at,
                       u.name AS instructor_name, u.email AS instructor_email, u.role AS instructor_role
                FROM class_subject_instructors csi
                JOIN users u ON csi.instructor_id = u.id
                WHERE csi.class_subject_id = %s
                ORDER BY CASE WHEN csi.role_type = 'main' THEN 1 ELSE 2 END, csi.created_at ASC
                """,
                (class_subject_id,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def assign_instructors_to_class_subject(
    class_subject_id: str,
    main_instructor_id: str | None,
    assistant_ids: list[str],
) -> list[dict]:
    """
    Phân công giảng viên chính và trợ giảng cho môn học của lớp (SCRUM-220).
    - Mỗi môn có tối đa 1 giảng viên chính (main).
    - Có thể có 0..n trợ giảng (assistant).
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Xóa các phân công cũ của môn
            cursor.execute("DELETE FROM class_subject_instructors WHERE class_subject_id = %s", (class_subject_id,))

            now = datetime.now(timezone.utc)
            # Thêm giảng viên chính (nếu có)
            if main_instructor_id and main_instructor_id.strip():
                cursor.execute(
                    """
                    INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
                    VALUES (%s, %s, %s, 'main', %s, %s)
                    """,
                    (str(uuid.uuid4()), class_subject_id, main_instructor_id.strip(), now, now),
                )

            # Thêm trợ giảng (bỏ qua nếu trùng lặp hoặc trùng với main_instructor)
            seen_assts = set()
            for asst_id in assistant_ids:
                clean_id = asst_id.strip() if isinstance(asst_id, str) else str(asst_id)
                if not clean_id or clean_id == (main_instructor_id or "").strip():
                    continue
                if clean_id in seen_assts:
                    continue
                seen_assts.add(clean_id)
                cursor.execute(
                    """
                    INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
                    VALUES (%s, %s, %s, 'assistant', %s, %s)
                    """,
                    (str(uuid.uuid4()), class_subject_id, clean_id, now, now),
                )

            conn.commit()
        return get_class_subject_instructors(class_subject_id)
    finally:
        conn.close()


def list_classes(
    program_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    instructor_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ClassEntity], int]:
    """Lấy danh sách lớp học có lọc và phân trang (SCRUM-217, SCRUM-219, SCRUM-220)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            where_clauses = ["1=1"]
            params = []

            if program_id and program_id.strip():
                where_clauses.append("c.program_id = %s")
                params.append(program_id.strip())

            if status and status.strip():
                where_clauses.append("c.status = %s")
                params.append(status.strip())

            if search and search.strip():
                term = f"%{search.strip()}%"
                where_clauses.append("(c.class_code LIKE %s OR tp.name LIKE %s OR tp.code LIKE %s)")
                params.extend([term, term, term])

            if date_from and date_from.strip():
                where_clauses.append("c.expected_start_date >= %s")
                params.append(date_from.strip())

            if date_to and date_to.strip():
                where_clauses.append("c.expected_start_date <= %s")
                params.append(date_to.strip())

            where_sql = " AND ".join(where_clauses)

            # Count total
            count_query = f"""
                SELECT COUNT(*) AS total
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE {where_sql}
            """
            cursor.execute(count_query, params)
            total = cursor.fetchone()["total"]

            # Select page
            offset = (page - 1) * page_size
            data_query = f"""
                SELECT c.*, tp.code AS program_code, tp.name AS program_name,
                       (SELECT COUNT(*) FROM class_enrollments ce WHERE ce.class_id = c.id) AS enrolled_count
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE {where_sql}
                ORDER BY c.created_at DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(data_query, params + [page_size, offset])
            rows = cursor.fetchall()
            return [_row_to_class(r) for r in rows], total
    finally:
        conn.close()


def delete_class_for_testing(class_id: str) -> None:
    """Hàm dọn dẹp dữ liệu test."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM class_subjects WHERE class_id = %s", (class_id,))
            cursor.execute("DELETE FROM classes WHERE id = %s", (class_id,))
            conn.commit()
    finally:
        conn.close()
