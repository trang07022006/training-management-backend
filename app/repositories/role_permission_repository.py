from contextlib import contextmanager
from datetime import datetime, timezone

from app.database.connection import get_db_connection
from app.models.permission import Permission
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
    """Quản lý kết nối, cursor và transaction cho bảng role_permissions."""
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


def assign_permission_to_role(role_id: str, permission_id: str) -> None:
    """
    Gán quyền hạn (permission) cho một vai trò (role) (SCRUM-62).
    Sử dụng parameterized query và kiểm tra ràng buộc toàn vẹn.
    """
    now = datetime.now(timezone.utc)
    sql = """
        INSERT INTO role_permissions (
            role_id,
            permission_id,
            created_at
        )
        VALUES (%s, %s, %s)
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (role_id, permission_id, _to_mysql_datetime(now)))


def get_permissions_by_role_id(role_id: str) -> list[Permission]:
    """
    Lấy danh sách đối tượng Permission được gán cho một role cụ thể (SCRUM-62).
    """
    sql = """
        SELECT
            p.id,
            p.code,
            p.name,
            p.description,
            p.created_at,
            p.updated_at
        FROM permissions p
        INNER JOIN role_permissions rp ON p.id = rp.permission_id
        WHERE rp.role_id = %s
        ORDER BY p.code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (role_id,))
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


def get_permission_codes_by_role_id(role_id: str) -> list[str]:
    """
    Lấy danh sách mã code của các quyền hạn thuộc vai trò (SCRUM-62).
    """
    sql = """
        SELECT p.code
        FROM permissions p
        INNER JOIN role_permissions rp ON p.id = rp.permission_id
        WHERE rp.role_id = %s
        ORDER BY p.code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (role_id,))
        rows = cursor.fetchall()

    return [str(row["code"]) for row in rows]


def get_roles_by_permission_id(permission_id: str) -> list[Role]:
    """
    Lấy danh sách các vai trò (roles) sở hữu một quyền hạn nhất định (SCRUM-62).
    """
    sql = """
        SELECT
            r.id,
            r.code,
            r.name,
            r.description,
            r.created_at,
            r.updated_at
        FROM roles r
        INNER JOIN role_permissions rp ON r.id = rp.role_id
        WHERE rp.permission_id = %s
        ORDER BY r.code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (permission_id,))
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


def remove_permission_from_role(role_id: str, permission_id: str) -> bool:
    """
    Thu hồi một quyền hạn khỏi vai trò (SCRUM-62).
    """
    sql = """
        DELETE FROM role_permissions
        WHERE role_id = %s AND permission_id = %s
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (role_id, permission_id))
        return cursor.rowcount > 0
