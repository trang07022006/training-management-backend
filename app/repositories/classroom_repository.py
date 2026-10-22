from datetime import datetime, timezone
import uuid
from app.database.connection import get_db_connection
from app.models.classroom import Classroom


def insert_classroom(classroom: Classroom) -> Classroom:
    """Thêm mới phòng học vào cơ sở dữ liệu (SCRUM-221)."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        if not classroom.id:
            classroom.id = str(uuid.uuid4())
        classroom.created_at = classroom.created_at or now
        classroom.updated_at = classroom.updated_at or now

        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO classrooms (id, room_code, room_name, room_type, capacity, online_link, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    classroom.id,
                    classroom.room_code.strip(),
                    classroom.room_name.strip(),
                    classroom.room_type.strip(),
                    classroom.capacity,
                    classroom.online_link.strip() if classroom.online_link else None,
                    classroom.status,
                    classroom.created_at,
                    classroom.updated_at,
                ),
            )
            conn.commit()
        return classroom
    finally:
        conn.close()


def get_classroom_by_id(classroom_id: str) -> Classroom | None:
    """Lấy thông tin phòng học theo ID (SCRUM-221)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM classrooms WHERE id = %s", (classroom_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Classroom(
                id=row["id"],
                room_code=row["room_code"],
                room_name=row["room_name"],
                room_type=row["room_type"],
                capacity=row["capacity"],
                online_link=row["online_link"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    finally:
        conn.close()


def get_classroom_by_code(room_code: str) -> Classroom | None:
    """Tìm phòng học theo mã phòng (SCRUM-221)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM classrooms WHERE room_code = %s", (room_code.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            return Classroom(
                id=row["id"],
                room_code=row["room_code"],
                room_name=row["room_name"],
                room_type=row["room_type"],
                capacity=row["capacity"],
                online_link=row["online_link"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    finally:
        conn.close()


def list_classrooms(
    room_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Classroom], int]:
    """Lấy danh sách phòng học có phân trang và lọc (SCRUM-221)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            where_clauses = ["1=1"]
            params = []

            if room_type and room_type.strip():
                where_clauses.append("room_type = %s")
                params.append(room_type.strip().lower())

            if status and status.strip():
                where_clauses.append("status = %s")
                params.append(status.strip())

            if search and search.strip():
                term = f"%{search.strip()}%"
                where_clauses.append("(room_code LIKE %s OR room_name LIKE %s)")
                params.extend([term, term])

            where_sql = " AND ".join(where_clauses)

            # Đếm tổng số
            count_query = f"SELECT COUNT(*) AS total FROM classrooms WHERE {where_sql}"
            cursor.execute(count_query, params)
            total = cursor.fetchone()["total"]

            # Lấy danh sách
            offset = (page - 1) * page_size
            data_query = f"""
                SELECT * FROM classrooms
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(data_query, params + [page_size, offset])
            rows = cursor.fetchall()

            items = [
                Classroom(
                    id=row["id"],
                    room_code=row["room_code"],
                    room_name=row["room_name"],
                    room_type=row["room_type"],
                    capacity=row["capacity"],
                    online_link=row["online_link"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
            return items, total
    finally:
        conn.close()


def delete_classroom_for_testing(classroom_id: str) -> None:
    """Xóa phòng học phục vụ tearDown testing."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM classrooms WHERE id = %s", (classroom_id,))
            conn.commit()
    finally:
        conn.close()


def find_unique_classroom_by_code_or_name(val: str) -> tuple[Classroom | None, str]:
    """
    Rà soát và ánh xạ chuỗi phòng học (như 'P301', 'UAT-P20') sang phòng trong danh mục chuẩn.
    Chỉ ánh xạ khi xác định duy nhất (Unique Match).
    Trả về: (Classroom, "EXACT_ID" | "UNIQUE_CODE" | "UNIQUE_NAME") nếu xác định duy nhất,
            (None, "AMBIGUOUS") nếu trùng nhiều phòng,
            (None, "NOT_FOUND") nếu không tìm thấy.
    """
    if not val or not str(val).strip():
        return None, "EMPTY"

    v = str(val).strip()

    # 1. Khớp ID chính xác
    by_id = get_classroom_by_id(v)
    if by_id:
        return by_id, "EXACT_ID"

    # 2. Khớp mã phòng (room_code có UNIQUE constraint)
    by_code = get_classroom_by_code(v)
    if by_code:
        return by_code, "UNIQUE_CODE"

    # 3. Khớp tên phòng (room_name)
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM classrooms WHERE room_name = %s", (v,))
            rows = cursor.fetchall()
            if len(rows) == 1:
                row = rows[0]
                return Classroom(
                    id=row["id"],
                    room_code=row["room_code"],
                    room_name=row["room_name"],
                    room_type=row["room_type"],
                    capacity=row["capacity"],
                    online_link=row["online_link"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                ), "UNIQUE_NAME"
            elif len(rows) > 1:
                return None, "AMBIGUOUS"
            return None, "NOT_FOUND"
    finally:
        conn.close()

