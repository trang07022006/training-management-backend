from contextlib import contextmanager

from app.database.connection import get_db_connection
from app.models.user import User


@contextmanager
def _database_cursor(write: bool = False):
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


def get_user_by_id(user_id: str) -> User | None:
    """Lấy thông tin người dùng theo user_id từ database MySQL."""
    sql = """
        SELECT id, password_hash, email, role, status
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
        password_hash=str(row.get("password_hash") or ""),
        email=row.get("email"),
        role=row.get("role"),
        status=row.get("status", "active"),
    )


def update_user_password(user_id: str, new_password_hash: str) -> bool:
    """
    Cập nhật mật khẩu băm của người dùng vào MySQL (SCRUM-56).
    Sử dụng parameterized query để chống SQL Injection và đảm bảo an toàn.
    """
    sql = """
        UPDATE users
        SET password_hash = %s
        WHERE id = %s
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (new_password_hash, user_id))
        return cursor.rowcount == 1
