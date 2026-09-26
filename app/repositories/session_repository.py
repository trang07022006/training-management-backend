from contextlib import contextmanager
from datetime import datetime, timezone

from app.database.connection import get_db_connection
from app.models.login_session import LoginSession


def _to_mysql_datetime(value: datetime | None):
    """Đổi thời gian có múi giờ thành thời gian UTC để lưu vào DATETIME."""

    if value is None:
        return None

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Thời gian của phiên phải có thông tin múi giờ.")

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


def insert_session(session: LoginSession) -> None:
    """Lưu một phiên mới vào MySQL."""

    sql = """
        INSERT INTO auth_sessions (
            session_id,
            user_id,
            refresh_jti,
            created_at,
            last_activity_at,
            idle_expires_at,
            absolute_expires_at,
            revoked_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """

    values = (
        session.session_id,
        session.user_id,
        session.refresh_jti,
        _to_mysql_datetime(session.created_at),
        _to_mysql_datetime(session.last_activity_at),
        _to_mysql_datetime(session.idle_expires_at),
        _to_mysql_datetime(session.absolute_expires_at),
        _to_mysql_datetime(session.revoked_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)


def get_session_by_id(session_id: str) -> LoginSession | None:
    """Đọc phiên theo ID; trả về None nếu không tìm thấy."""

    sql = """
        SELECT
            session_id,
            user_id,
            refresh_jti,
            created_at,
            last_activity_at,
            idle_expires_at,
            absolute_expires_at,
            revoked_at
        FROM auth_sessions
        WHERE session_id = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (session_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    datetime_fields = (
        "created_at",
        "last_activity_at",
        "idle_expires_at",
        "absolute_expires_at",
        "revoked_at",
    )

    for field in datetime_fields:
        if row[field] is not None:
            row[field] = row[field].replace(tzinfo=timezone.utc)

    return LoginSession(**row)