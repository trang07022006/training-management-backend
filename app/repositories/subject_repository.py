from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.database.connection import get_db_connection
from app.models.subject import (
    SUBJECT_STATUS_DRAFT,
    Subject,
)


def _to_mysql_datetime(value: datetime | None):
    """Chuyển đổi thời gian có múi giờ sang UTC không múi giờ để lưu vào MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu Subject."""
    connection = get_db_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            yield cursor
        if write:
            connection.commit()
    except Exception:
        if write:
            connection.rollback()
        raise
    finally:
        connection.close()


def _row_to_model(row: dict) -> Subject:
    """Chuyển đổi dictionary row từ MySQL thành đối tượng Subject."""
    sessions = row.get("total_sessions")
    return Subject(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        credits=int(row["credits"]),
        description=row.get("description"),
        total_sessions=int(sessions) if sessions is not None else None,
        status=str(row.get("status") or SUBJECT_STATUS_DRAFT),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def insert_subject(subject: Subject) -> Subject:
    """
    Thêm một môn học/học phần mới vào cơ sở dữ liệu (SCRUM-123 - Activity A1).
    Sử dụng hoàn toàn parameterized query để chống SQL injection.
    """
    created_at = subject.created_at or datetime.now(timezone.utc)
    updated_at = subject.updated_at or created_at

    sql = """
        INSERT INTO subjects (
            id,
            code,
            name,
            credits,
            description,
            total_sessions,
            status,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        subject.id,
        subject.code,
        subject.name,
        subject.credits,
        subject.description,
        subject.total_sessions,
        subject.status,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    return Subject(
        id=subject.id,
        code=subject.code,
        name=subject.name,
        credits=subject.credits,
        description=subject.description,
        total_sessions=subject.total_sessions,
        status=subject.status,
        created_at=created_at,
        updated_at=updated_at,
    )


def get_subject_by_id(subject_id: str) -> Subject | None:
    """Lấy thông tin môn học theo UUID."""
    sql = """
        SELECT id, code, name, credits, description, total_sessions, status, created_at, updated_at
        FROM subjects
        WHERE id = %s
        LIMIT 1
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (subject_id,))
        row = cursor.fetchone()

    return _row_to_model(row) if row else None


def get_subject_by_code(code: str) -> Subject | None:
    """Lấy thông tin môn học theo mã môn học."""
    sql = """
        SELECT id, code, name, credits, description, total_sessions, status, created_at, updated_at
        FROM subjects
        WHERE code = %s
        LIMIT 1
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (code,))
        row = cursor.fetchone()

    return _row_to_model(row) if row else None


def exists_by_code(code: str, exclude_id: str | None = None) -> bool:
    """
    Kiểm tra sự tồn tại của mã môn học.
    Có hỗ trợ loại trừ ID bản ghi hiện tại khi cập nhật.
    """
    if exclude_id:
        sql = "SELECT 1 FROM subjects WHERE code = %s AND id != %s LIMIT 1"
        params = (code, exclude_id)
    else:
        sql = "SELECT 1 FROM subjects WHERE code = %s LIMIT 1"
        params = (code,)

    with _database_cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone() is not None


def get_all_subjects(
    search: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Subject]:
    """
    Lấy danh sách các môn học, hỗ trợ tìm kiếm theo mã/tên và lọc trạng thái.
    """
    sql = """
        SELECT id, code, name, credits, description, total_sessions, status, created_at, updated_at
        FROM subjects
        WHERE 1=1
    """
    params: list[Any] = []

    if search:
        sql += " AND (code LIKE %s OR name LIKE %s)"
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern])

    if status:
        sql += " AND status = %s"
        params.append(status.strip())

    sql += " ORDER BY created_at DESC"

    if limit is not None and limit > 0:
        sql += " LIMIT %s"
        params.append(limit)
        if offset is not None and offset >= 0:
            sql += " OFFSET %s"
            params.append(offset)

    with _database_cursor() as cursor:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

    return [_row_to_model(r) for r in rows]


def count_subjects(search: str | None = None, status: str | None = None) -> int:
    """Đếm tổng số môn học theo bộ lọc tìm kiếm và trạng thái."""
    sql = "SELECT COUNT(*) as total FROM subjects WHERE 1=1"
    params: list[Any] = []

    if search:
        sql += " AND (code LIKE %s OR name LIKE %s)"
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern])

    if status:
        sql += " AND status = %s"
        params.append(status.strip())

    with _database_cursor() as cursor:
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()

    return int(row["total"]) if row else 0


def update_subject(subject: Subject) -> bool:
    """Cập nhật thông tin một môn học trong cơ sở dữ liệu."""
    updated_at = datetime.now(timezone.utc)
    sql = """
        UPDATE subjects
        SET code = %s,
            name = %s,
            credits = %s,
            description = %s,
            total_sessions = %s,
            status = %s,
            updated_at = %s
        WHERE id = %s
    """
    values = (
        subject.code,
        subject.name,
        subject.credits,
        subject.description,
        subject.total_sessions,
        subject.status,
        _to_mysql_datetime(updated_at),
        subject.id,
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)
        return cursor.rowcount > 0


ALLOWED_SUBJECT_UPDATE_FIELDS = {
    "code",
    "name",
    "description",
    "credits",
    "total_sessions",
    "status",
}


def update_subject_fields(
    subject_id: str,
    fields: dict[str, Any],
    updated_at: datetime | None = None,
) -> Subject | None:
    """
    Cập nhật các trường được chỉ định của môn học (SCRUM-123 - Activity A4 - PATCH).
    Chỉ cho phép cập nhật các trường trong whitelist ALLOWED_SUBJECT_UPDATE_FIELDS.
    Tự động cập nhật updated_at theo UTC.
    Sử dụng parameterized query an toàn chống SQL Injection.
    """
    valid_fields = {k: v for k, v in fields.items() if k in ALLOWED_SUBJECT_UPDATE_FIELDS}
    if not valid_fields:
        return get_subject_by_id(subject_id)

    now = updated_at or datetime.now(timezone.utc)
    set_clauses = [f"{col} = %s" for col in valid_fields.keys()]
    set_clauses.append("updated_at = %s")

    values = list(valid_fields.values())
    values.append(_to_mysql_datetime(now))
    values.append(subject_id)

    sql = f"""
        UPDATE subjects
        SET {', '.join(set_clauses)}
        WHERE id = %s
    """

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, tuple(values))

    return get_subject_by_id(subject_id)


def delete_subject(subject_id: str) -> bool:
    """Xóa một môn học theo ID."""
    sql = "DELETE FROM subjects WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (subject_id,))
        return cursor.rowcount > 0


def is_subject_in_use(subject_id: str) -> bool:
    """
    Kiểm tra xem môn học có đang được sử dụng ở bảng liên kết hay không.
    Tương thích tương lai khi triển khai SCRUM-124 (program_subjects).
    """
    sql = """
        SELECT COUNT(*) as cnt
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'program_subjects'
    """
    with _database_cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
        has_table = row and row.get("cnt", 0) > 0

        if not has_table:
            return False

        check_sql = "SELECT 1 FROM program_subjects WHERE subject_id = %s LIMIT 1"
        cursor.execute(check_sql, (subject_id,))
        return cursor.fetchone() is not None
