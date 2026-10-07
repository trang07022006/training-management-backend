from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.database.connection import get_db_connection
from app.models.training_program import (
    PROGRAM_STATUS_DRAFT,
    TrainingProgram,
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
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu TrainingProgram."""
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


def _row_to_model(row: dict) -> TrainingProgram:
    """Chuyển đổi dictionary row từ MySQL thành đối tượng TrainingProgram."""
    duration = row.get("duration_semesters")
    return TrainingProgram(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        description=row.get("description"),
        duration_semesters=int(duration) if duration is not None else None,
        status=str(row.get("status") or PROGRAM_STATUS_DRAFT),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def insert_training_program(program: TrainingProgram) -> TrainingProgram:
    """
    Thêm một chương trình đào tạo mới vào cơ sở dữ liệu (SCRUM-122).
    Sử dụng hoàn toàn parameterized query để chống SQL injection.
    """
    created_at = program.created_at or datetime.now(timezone.utc)
    updated_at = program.updated_at or created_at

    sql = """
        INSERT INTO training_programs (
            id,
            code,
            name,
            description,
            duration_semesters,
            status,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        program.id,
        program.code,
        program.name,
        program.description,
        program.duration_semesters,
        program.status,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    return TrainingProgram(
        id=program.id,
        code=program.code,
        name=program.name,
        description=program.description,
        duration_semesters=program.duration_semesters,
        status=program.status,
        created_at=created_at,
        updated_at=updated_at,
    )


def get_training_program_by_id(program_id: str) -> TrainingProgram | None:
    """
    Tìm kiếm chương trình đào tạo theo ID (SCRUM-122).
    Trả về None nếu không tìm thấy.
    """
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            duration_semesters,
            status,
            created_at,
            updated_at
        FROM training_programs
        WHERE id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_model(row)


def get_training_program_by_code(code: str) -> TrainingProgram | None:
    """
    Tìm kiếm chương trình đào tạo theo mã định danh duy nhất (SCRUM-122).
    Trả về None nếu không tìm thấy.
    """
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            duration_semesters,
            status,
            created_at,
            updated_at
        FROM training_programs
        WHERE code = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (code,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_model(row)


def exists_by_code(code: str, exclude_id: str | None = None) -> bool:
    """
    Kiểm tra sự tồn tại của mã chương trình đào tạo trong hệ thống.
    Hỗ trợ loại trừ ID cụ thể khi kiểm tra trùng lặp trong kịch bản cập nhật.
    """
    if exclude_id is not None:
        sql = "SELECT 1 FROM training_programs WHERE code = %s AND id != %s LIMIT 1"
        params = (code, exclude_id)
    else:
        sql = "SELECT 1 FROM training_programs WHERE code = %s LIMIT 1"
        params = (code,)

    with _database_cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()

    return row is not None


def get_all_training_programs(
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TrainingProgram]:
    """
    Lấy danh sách các chương trình đào tạo kèm hỗ trợ lọc theo trạng thái, tìm kiếm và phân trang.
    """
    conditions = []
    params: list = []

    if status is not None and status.strip():
        conditions.append("status = %s")
        params.append(status.strip())

    if search is not None and search.strip():
        search_pattern = f"%{search.strip()}%"
        conditions.append("(code LIKE %s OR name LIKE %s)")
        params.extend([search_pattern, search_pattern])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT
            id,
            code,
            name,
            description,
            duration_semesters,
            status,
            created_at,
            updated_at
        FROM training_programs
        {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with _database_cursor() as cursor:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

    return [_row_to_model(row) for row in rows]


def count_training_programs(status: str | None = None, search: str | None = None) -> int:
    """
    Đếm tổng số chương trình đào tạo trong hệ thống, có thể lọc theo trạng thái và tìm kiếm.
    """
    conditions = []
    params: list = []

    if status is not None and status.strip():
        conditions.append("status = %s")
        params.append(status.strip())

    if search is not None and search.strip():
        search_pattern = f"%{search.strip()}%"
        conditions.append("(code LIKE %s OR name LIKE %s)")
        params.extend([search_pattern, search_pattern])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT COUNT(*) AS total FROM training_programs {where_clause}"

    with _database_cursor() as cursor:
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()

    return int(row["total"]) if row else 0


def delete_training_program(program_id: str) -> bool:
    """
    Xóa một chương trình đào tạo theo ID (phục vụ dọn dẹp dữ liệu test và quản trị).
    Trả về True nếu có bản ghi bị xóa, ngược lại False.
    """
    sql = "DELETE FROM training_programs WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (program_id,))
        return cursor.rowcount > 0


ALLOWED_UPDATE_FIELDS = {
    "code",
    "name",
    "description",
    "duration_semesters",
    "status",
}


def update_training_program(program: TrainingProgram) -> TrainingProgram:
    """
    Cập nhật toàn bộ các trường nghiệp vụ của chương trình đào tạo (SCRUM-122 - Activity A4 - PUT).
    Sử dụng hoàn toàn parameterized query để chống SQL injection.
    """
    now = datetime.now(timezone.utc)
    updated_at = program.updated_at or now

    sql = """
        UPDATE training_programs
        SET
            code = %s,
            name = %s,
            description = %s,
            duration_semesters = %s,
            status = %s,
            updated_at = %s
        WHERE id = %s
    """
    values = (
        program.code,
        program.name,
        program.description,
        program.duration_semesters,
        program.status,
        _to_mysql_datetime(updated_at),
        program.id,
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    updated = get_training_program_by_id(program.id)
    return updated or program


def update_training_program_fields(
    program_id: str,
    fields: dict[str, Any],
) -> TrainingProgram | None:
    """
    Cập nhật các trường được chỉ định của chương trình đào tạo (SCRUM-122 - Activity A4 - PATCH).
    Chỉ cho phép cập nhật các trường trong whitelist ALLOWED_UPDATE_FIELDS.
    Tự động cập nhật updated_at theo UTC.
    Sử dụng parameterized query an toàn chống SQL Injection.
    """
    valid_fields = {k: v for k, v in fields.items() if k in ALLOWED_UPDATE_FIELDS}
    if not valid_fields:
        return get_training_program_by_id(program_id)

    now = datetime.now(timezone.utc)
    set_clauses = [f"{col} = %s" for col in valid_fields.keys()]
    set_clauses.append("updated_at = %s")

    values = list(valid_fields.values())
    values.append(_to_mysql_datetime(now))
    values.append(program_id)

    sql = f"""
        UPDATE training_programs
        SET {', '.join(set_clauses)}
        WHERE id = %s
    """

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, tuple(values))

    return get_training_program_by_id(program_id)

