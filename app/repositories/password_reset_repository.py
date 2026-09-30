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



class ResetTokenError(Exception):
    """Lỗi liên quan đến reset token."""
    pass


class ResetTokenNotFoundError(ResetTokenError):
    """Token không tồn tại trong hệ thống."""
    pass


class ResetTokenExpiredError(ResetTokenError):
    """Token đã hết hạn."""
    pass


class ResetTokenAlreadyUsedError(ResetTokenError):
    """Token đã được sử dụng trước đó."""
    pass


def _row_to_token(row: dict) -> PasswordResetToken:
    """Chuyển đổi một bản ghi database thành đối tượng PasswordResetToken."""
    created_at = row["created_at"]
    if created_at is not None and hasattr(created_at, "tzinfo") and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    expires_at = row["expires_at"]
    if expires_at is not None and hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    used_at = row.get("used_at")
    if used_at is not None and hasattr(used_at, "tzinfo") and used_at.tzinfo is None:
        used_at = used_at.replace(tzinfo=timezone.utc)

    return PasswordResetToken(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        token_hash=row["token_hash"],
        created_at=created_at,
        expires_at=expires_at,
        used_at=used_at,
    )


def insert_reset_token(reset_token: PasswordResetToken) -> None:
    """Lưu reset token mới vào bảng password_reset_tokens."""
    sql = """
        INSERT INTO password_reset_tokens (
            id,
            user_id,
            token_hash,
            created_at,
            expires_at,
            used_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    mysql_created_at = _to_mysql_datetime(reset_token.created_at)
    mysql_expires_at = _to_mysql_datetime(reset_token.expires_at)
    mysql_used_at = _to_mysql_datetime(reset_token.used_at)

    with _database_cursor(write=True) as cursor:
        cursor.execute(
            sql,
            (
                reset_token.id,
                reset_token.user_id,
                reset_token.token_hash,
                mysql_created_at,
                mysql_expires_at,
                mysql_used_at,
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
            expires_at,
            used_at
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
            expires_at,
            used_at
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


def mark_reset_token_used(token_id: str, used_at: datetime | None = None) -> None:
    """Đánh dấu reset token đã được sử dụng bằng cách gán used_at."""
    now = used_at or datetime.now(timezone.utc)
    mysql_used_at = _to_mysql_datetime(now)
    sql = """
        UPDATE password_reset_tokens
        SET used_at = %s
        WHERE id = %s
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (mysql_used_at, token_id))


def execute_reset_password_transaction(
    token_hash: str,
    new_password_hash: str,
    current_time: datetime | None = None,
) -> PasswordResetToken:
    """
    Thực thi transaction đặt lại mật khẩu tuân thủ SCRUM-47:
    Luồng:
      1. Validate token (tồn tại, chưa hết hạn, chưa được sử dụng)
      2. Cập nhật mật khẩu người dùng (update users)
      3. Đánh dấu token đã dùng (update password_reset_tokens SET used_at = %s)
      4. Commit transaction

    Nếu bất kỳ bước nào lỗi -> Rollback ngay lập tức.
    Đảm bảo nếu update password lỗi thì token không bao giờ bị consume sai.
    """
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    connection = get_db_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            # 1. Validate token
            select_sql = """
                SELECT
                    id,
                    user_id,
                    token_hash,
                    created_at,
                    expires_at,
                    used_at
                FROM password_reset_tokens
                WHERE token_hash = %s
                FOR UPDATE
            """
            cursor.execute(select_sql, (token_hash,))
            row = cursor.fetchone()

            if row is None:
                raise ResetTokenNotFoundError("Token không tồn tại")

            token = _row_to_token(row)

            if token.is_used:
                raise ResetTokenAlreadyUsedError("Token đã được sử dụng")

            if token.is_expired(current_time=now):
                raise ResetTokenExpiredError("Token đã hết hạn")

            # 2. Cập nhật mật khẩu người dùng và reset lockout
            update_user_sql = """
                UPDATE users
                SET
                    password_hash = %s,
                    failed_login_attempts = 0,
                    locked_until = NULL
                WHERE id = %s
            """
            cursor.execute(update_user_sql, (new_password_hash, token.user_id))

            # 3. Đánh dấu token đã sử dụng (chỉ sau khi cập nhật password thành công)
            update_token_sql = """
                UPDATE password_reset_tokens
                SET used_at = %s
                WHERE id = %s
            """
            mysql_used_at = _to_mysql_datetime(now)
            cursor.execute(update_token_sql, (mysql_used_at, token.id))

            # 4. Commit transaction khi cả 2 bước thành công
            connection.commit()

            token.used_at = now
            return token

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
