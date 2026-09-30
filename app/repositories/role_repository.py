from contextlib import contextmanager
from datetime import datetime, timezone

from app.database.connection import get_db_connection
from app.models.role import Role


def _to_mysql_datetime(value: datetime | None):
    """Chuyển đổi thời gian có múi giờ sang UTC để lưu vào MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu Role."""
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


def insert_role(role: Role) -> Role:
    """
    Thêm một vai trò mới vào cơ sở dữ liệu (SCRUM-60).
    Sử dụng parameterized query để chống SQL injection.
    """
    created_at = role.created_at or datetime.now(timezone.utc)
    updated_at = role.updated_at or created_at

    sql = """
        INSERT INTO roles (
            id,
            code,
            name,
            description,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    values = (
        role.id,
        role.code,
        role.name,
        role.description,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    return Role(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        created_at=created_at,
        updated_at=updated_at,
    )


def get_role_by_id(role_id: str) -> Role | None:
    """
    Tìm kiếm vai trò theo ID (SCRUM-60).
    Trả về None nếu không tìm thấy.
    """
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            created_at,
            updated_at
        FROM roles
        WHERE id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (role_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return Role(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        description=row.get("description"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def get_role_by_code(code: str) -> Role | None:
    """
    Tìm kiếm vai trò theo code định danh (SCRUM-60).
    Trả về None nếu không tìm thấy.
    """
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            created_at,
            updated_at
        FROM roles
        WHERE code = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (code,))
        row = cursor.fetchone()

    if row is None:
        return None

    return Role(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        description=row.get("description"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def get_all_roles() -> list[Role]:
    """Lấy danh sách toàn bộ các vai trò trong hệ thống (SCRUM-60)."""
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            created_at,
            updated_at
        FROM roles
        ORDER BY code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    return [
        Role(
            id=str(row["id"]),
            code=str(row["code"]),
            name=str(row["name"]),
            description=row.get("description"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
        for row in rows
    ]
