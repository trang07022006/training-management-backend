from contextlib import contextmanager
from datetime import datetime, timezone

from app.database.connection import get_db_connection
from app.models.user import User


def _to_mysql_datetime(value: datetime | None) -> datetime | None:
    """Đổi thời gian có múi giờ thành thời gian UTC để lưu vào DATETIME."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


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


def _row_to_user(row: dict) -> User:
    """Chuyển đổi một bản ghi database thành đối tượng User."""
    locked_until = row.get("locked_until")
    if locked_until is not None and hasattr(locked_until, "tzinfo") and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)

    return User(
        id=str(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        role=row.get("role", "user"),
        status=row.get("status", "active"),
        failed_login_attempts=row.get("failed_login_attempts") or 0,
        locked_until=locked_until,
    )


def get_user_by_email(email: str) -> User | None:
    """Đọc người dùng theo email; trả về None nếu không tìm thấy."""

    sql = """
        SELECT
            id,
            email,
            password_hash,
            role,
            status,
            failed_login_attempts,
            locked_until
        FROM users
        WHERE email = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (email,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_user(row)


def get_user_by_id(user_id: str) -> User | None:
    """Đọc người dùng theo ID; trả về None nếu không tìm thấy."""

    sql = """
        SELECT
            id,
            email,
            password_hash,
            role,
            status,
            failed_login_attempts,
            locked_until
        FROM users
        WHERE id = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_user(row)


def update_user_lockout(
    user_id: str,
    failed_login_attempts: int,
    locked_until: datetime | None,
) -> None:
    """Cập nhật số lần đăng nhập sai và thời gian khóa tài khoản."""
    sql = """
        UPDATE users
        SET
            failed_login_attempts = %s,
            locked_until = %s
        WHERE id = %s
    """

    mysql_locked_until = _to_mysql_datetime(locked_until)

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (failed_login_attempts, mysql_locked_until, user_id))


def reset_user_lockout(user_id: str) -> None:
    """Reset số lần đăng nhập sai và hủy thời gian khóa khi đăng nhập thành công."""
    sql = """
        UPDATE users
        SET
            failed_login_attempts = 0,
            locked_until = NULL
        WHERE id = %s
    """

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (user_id,))

