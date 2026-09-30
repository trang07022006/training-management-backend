from contextlib import contextmanager
from datetime import datetime, timezone

from app.database.connection import get_db_connection
from app.models.permission import Permission


def _to_mysql_datetime(value: datetime | None):
    """Chuyển đổi thời gian có múi giờ sang UTC để lưu vào MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu Permission."""
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


def insert_permission(permission: Permission) -> Permission:
    """
    Thêm một quyền hạn mới vào cơ sở dữ liệu (SCRUM-61).
    Sử dụng parameterized query để chống SQL injection.
    """
    created_at = permission.created_at or datetime.now(timezone.utc)
    updated_at = permission.updated_at or created_at

    sql = """
        INSERT INTO permissions (
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
        permission.id,
        permission.code,
        permission.name,
        permission.description,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    return Permission(
        id=permission.id,
        code=permission.code,
        name=permission.name,
        description=permission.description,
        created_at=created_at,
        updated_at=updated_at,
    )


def get_permission_by_id(permission_id: str) -> Permission | None:
    """
    Tìm kiếm quyền hạn theo ID (SCRUM-61).
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
        FROM permissions
        WHERE id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (permission_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return Permission(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        description=row.get("description"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def get_permission_by_code(code: str) -> Permission | None:
    """
    Tìm kiếm quyền hạn theo mã code định danh (SCRUM-61).
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
        FROM permissions
        WHERE code = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (code,))
        row = cursor.fetchone()

    if row is None:
        return None

    return Permission(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        description=row.get("description"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def get_all_permissions() -> list[Permission]:
    """Lấy danh sách toàn bộ các quyền trong hệ thống (SCRUM-61)."""
    sql = """
        SELECT
            id,
            code,
            name,
            description,
            created_at,
            updated_at
        FROM permissions
        ORDER BY code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    return [
        Permission(
            id=str(row["id"]),
            code=str(row["code"]),
            name=str(row["name"]),
            description=row.get("description"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
        for row in rows
    ]
