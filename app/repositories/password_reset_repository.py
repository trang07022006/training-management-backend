from contextlib import contextmanager
from datetime import datetime, timezone

from app.database.connection import get_db_connection
from app.models.password_reset_token import PasswordResetToken


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


def _row_to_token(row: dict) -> PasswordResetToken:
    """Chuyển đổi một bản ghi database thành đối tượng PasswordResetToken."""
    created_at = row["created_at"]
    if created_at is not None and hasattr(created_at, "tzinfo") and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    expires_at = row["expires_at"]
    if expires_at is not None and hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return PasswordResetToken(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        token_hash=row["token_hash"],
        created_at=created_at,
        expires_at=expires_at,
    )


def insert_reset_token(reset_token: PasswordResetToken) -> None:
    """Lưu reset token mới vào bảng password_reset_tokens."""
    sql = """
        INSERT INTO password_reset_tokens (
            id,
            user_id,
            token_hash,
            created_at,
            expires_at
        )
        VALUES (%s, %s, %s, %s, %s)
    """

    mysql_created_at = _to_mysql_datetime(reset_token.created_at)
    mysql_expires_at = _to_mysql_datetime(reset_token.expires_at)

    with _database_cursor(write=True) as cursor:
        cursor.execute(
            sql,
            (
                reset_token.id,
                reset_token.user_id,
                reset_token.token_hash,
                mysql_created_at,
                mysql_expires_at,
            ),
        )


def get_reset_token_by_hash(token_hash: str) -> PasswordResetToken | None:
    """Đọc reset token theo token_hash; trả về None nếu không tìm thấy."""
    sql = """
        SELECT
            id,
            user_id,
            token_hash,
            created_at,
            expires_at
        FROM password_reset_tokens
        WHERE token_hash = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (token_hash,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_token(row)


def get_latest_reset_token_by_user_id(user_id: str) -> PasswordResetToken | None:
    """Đọc reset token mới nhất của user_id; trả về None nếu không tìm thấy."""
    sql = """
        SELECT
            id,
            user_id,
            token_hash,
            created_at,
            expires_at
        FROM password_reset_tokens
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 1
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_token(row)
