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
    """Quản lý kết nối, cursor và transaction cho bảng user_roles."""
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


def assign_role_to_user(user_id: str, role_id: str) -> None:
    """
    Gán vai trò (role) cho người dùng (user) (SCRUM-63).
    Sử dụng parameterized query.
    """
    now = datetime.now(timezone.utc)
    sql = """
        INSERT INTO user_roles (
            user_id,
            role_id,
            created_at
        )
        VALUES (%s, %s, %s)
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (user_id, role_id, _to_mysql_datetime(now)))


def get_roles_by_user_id(user_id: str) -> list[Role]:
    """
    Lấy danh sách các đối tượng Role của một người dùng (SCRUM-63).
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
        INNER JOIN user_roles ur ON r.id = ur.role_id
        WHERE ur.user_id = %s
        ORDER BY r.code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id,))
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


def get_role_codes_by_user_id(user_id: str) -> list[str]:
    """
    Lấy danh sách mã vai trò (role codes) của người dùng (SCRUM-63).
    """
    sql = """
        SELECT r.code
        FROM roles r
        INNER JOIN user_roles ur ON r.id = ur.role_id
        WHERE ur.user_id = %s
        ORDER BY r.code ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id,))
        rows = cursor.fetchall()

    return [str(row["code"]) for row in rows]


def get_primary_role_code_by_user_id(user_id: str) -> str | None:
    """
    Lấy role chính dạng chuỗi đơn nhằm đảm bảo backward compatibility với SCRUM-18 (Login).
    Nếu user có nhiều role, trả về role có độ ưu tiên cao nhất hoặc role đầu tiên.
    """
    roles = get_role_codes_by_user_id(user_id)
    if not roles:
        return None
    # Thứ tự ưu tiên nếu user có nhiều role
    priority = ["admin", "trainer", "trainee", "user"]
    for p in priority:
        if p in roles:
            return p
    return roles[0]


def get_users_by_role_id(role_id: str) -> list[str]:
    """
    Lấy danh sách user_id được gán một vai trò cụ thể (SCRUM-63).
    """
    sql = """
        SELECT user_id
        FROM user_roles
        WHERE role_id = %s
        ORDER BY user_id ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (role_id,))
        rows = cursor.fetchall()

    return [str(row["user_id"]) for row in rows]


def remove_role_from_user(user_id: str, role_id: str) -> bool:
    """
    Thu hồi một vai trò khỏi người dùng (SCRUM-63).
    """
    sql = """
        DELETE FROM user_roles
        WHERE user_id = %s AND role_id = %s
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (user_id, role_id))
        return cursor.rowcount > 0


def check_user_role_exists(user_id: str, role_id: str) -> bool:
    """
    Kiểm tra xem người dùng đã được gán vai trò này hay chưa (SCRUM-96).
    """
    sql = """
        SELECT 1
        FROM user_roles
        WHERE user_id = %s AND role_id = %s
        LIMIT 1
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id, role_id))
        return cursor.fetchone() is not None

