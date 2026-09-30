from contextlib import contextmanager

from app.database.connection import get_db_connection
from app.models.user import User


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác."""

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


def get_user_by_email(email: str) -> User | None:
    """Đọc người dùng theo email; trả về None nếu không tìm thấy."""

    sql = """
        SELECT
            id,
            email,
            password_hash,
            role,
            status
        FROM users
        WHERE email = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (email,))
        row = cursor.fetchone()

    if row is None:
        return None

    return User(
        id=str(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        role=row.get("role", "user"),
        status=row.get("status", "active"),
    )


def get_user_by_id(user_id: str) -> User | None:
    """Đọc người dùng theo ID; trả về None nếu không tìm thấy."""

    sql = """
        SELECT
            id,
            email,
            password_hash,
            role,
            status
        FROM users
        WHERE id = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return User(
        id=str(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        role=row.get("role", "user"),
        status=row.get("status", "active"),
    )
