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
        email=row.get("email"),
        password_hash=row.get("password_hash", ""),
        role=row.get("role", "user"),
        status=row.get("status", "active"),
        failed_login_attempts=row.get("failed_login_attempts") or 0,
        locked_until=locked_until,
        name=row.get("name"),
        phone=row.get("phone"),
        date_of_birth=row.get("date_of_birth"),
        address=row.get("address"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


SAFE_SORT_COLUMNS = {
    "created_at": "created_at",
    "email": "email",
    "id": "id",
    "status": "status",
    "role": "role",
}


def list_users(
    page: int = 1,
    page_size: int = 10,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> tuple[list[User], int]:
    """
    Truy xuất danh sách người dùng có phân trang, tìm kiếm và lọc (SCRUM-82, SCRUM-87).
    - Mặc định 10 bản ghi/trang nếu không quy định khác.
    - Tìm kiếm theo tên, email, số điện thoại (tối đa 100 ký tự, tự động trim).
    - Lọc theo vai trò (role) và trạng thái (status).
    - Sắp xếp xác định (deterministic sort) kết hợp tie-breaker id.
    - SQL sử dụng hoàn toàn parameterized query tuyệt đối chống SQL injection.
    """
    safe_page = page if isinstance(page, int) and page >= 1 else 1
    safe_page_size = page_size if isinstance(page_size, int) and 1 <= page_size <= 100 else 10
    offset = (safe_page - 1) * safe_page_size

    sort_col = SAFE_SORT_COLUMNS.get(sort_by, "created_at")
    sort_dir = "ASC" if str(sort_order).upper() == "ASC" else "DESC"

    where_clauses: list[str] = []
    params: list = []

    if search and isinstance(search, str):
        clean_search = search.strip()[:100]
        if clean_search:
            search_pattern = f"%{clean_search}%"
            where_clauses.append("(name LIKE %s OR email LIKE %s OR phone LIKE %s)")
            params.extend([search_pattern, search_pattern, search_pattern])

    if role and isinstance(role, str):
        clean_role = role.strip().lower()
        if clean_role:
            where_clauses.append("role = %s")
            params.append(clean_role)

    if status and isinstance(status, str):
        clean_status = status.strip().lower()
        if clean_status:
            where_clauses.append("status = %s")
            params.append(clean_status)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_sql = f"SELECT COUNT(*) AS total FROM users {where_sql}"
    data_sql = f"""
        SELECT
            id,
            email,
            password_hash,
            role,
            status,
            failed_login_attempts,
            locked_until,
            name,
            phone,
            date_of_birth,
            address,
            created_at,
            updated_at
        FROM users
        {where_sql}
        ORDER BY {sort_col} {sort_dir}, id {sort_dir}
        LIMIT %s OFFSET %s
    """

    with _database_cursor() as cursor:
        cursor.execute(count_sql, tuple(params))
        count_row = cursor.fetchone()
        total = count_row["total"] if count_row and "total" in count_row else 0

        if total == 0 or offset >= total:
            return [], total

        cursor.execute(data_sql, tuple(params + [safe_page_size, offset]))
        rows = cursor.fetchall() or []

    return [_row_to_user(r) for r in rows], total


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
            locked_until,
            name,
            phone,
            date_of_birth,
            address,
            created_at,
            updated_at
        FROM users
        WHERE email = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (email,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_user(row)


def check_email_exists(email: str, exclude_user_id: str | None = None) -> bool:
    """
    Kiểm tra email đã tồn tại hay chưa, có thể loại trừ user_id cụ thể (SCRUM-85).
    Chống trùng lặp email không phân biệt chữ hoa/thường (case-insensitive).
    """
    norm_email = email.strip().lower() if isinstance(email, str) else ""
    if not norm_email:
        return False

    existing = get_user_by_email(norm_email)
    if existing is None:
        return False
    if exclude_user_id and str(existing.id) == str(exclude_user_id):
        return False
    return True


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
            locked_until,
            name,
            phone,
            date_of_birth,
            address,
            created_at,
            updated_at
        FROM users
        WHERE id = %s
    """

    with _database_cursor() as cursor:
        cursor.execute(sql, (user_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_user(row)


def create_user(user: User) -> User:
    """
    Tạo người dùng mới vào cơ sở dữ liệu MySQL (SCRUM-84).
    Sử dụng hoàn toàn parameterized query để chống SQL Injection.
    """
    now = datetime.now(timezone.utc)
    created_at = user.created_at or now
    updated_at = user.updated_at or now

    sql = """
        INSERT INTO users (
            id,
            email,
            password_hash,
            name,
            phone,
            role,
            status,
            failed_login_attempts,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        user.id,
        user.email,
        user.password_hash,
        user.name,
        user.phone,
        user.role,
        user.status,
        user.failed_login_attempts or 0,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    user.created_at = created_at
    user.updated_at = updated_at
    return user


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


def update_user(user: User) -> bool:
    """
    Cập nhật thông tin người dùng vào MySQL (SCRUM-86).
    Sử dụng hoàn toàn parameterized query để chống SQL Injection.
    Chỉ cho phép cập nhật các trường được phê duyệt: name, phone, email, status.
    """
    now = datetime.now(timezone.utc)
    updated_at = user.updated_at or now

    sql = """
        UPDATE users
        SET
            name = %s,
            phone = %s,
            email = %s,
            status = %s,
            updated_at = %s
        WHERE id = %s
    """
    values = (
        user.name,
        user.phone,
        user.email,
        user.status,
        _to_mysql_datetime(updated_at),
        user.id,
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)
        user.updated_at = updated_at
        return cursor.rowcount > 0


def update_user_status(user_id: str, status: str) -> bool:
    """
    Cập nhật trạng thái tài khoản người dùng (SCRUM-104).
    Sử dụng hoàn toàn parameterized query để chống SQL Injection.
    """
    now = datetime.now(timezone.utc)
    sql = """
        UPDATE users
        SET status = %s, updated_at = %s
        WHERE id = %s
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (status, _to_mysql_datetime(now), user_id))
        return cursor.rowcount > 0

