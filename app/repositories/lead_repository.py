"""
Repository truy xuất cơ sở dữ liệu cho thực thể Lead / Yêu cầu tư vấn (SCRUM-125 - Activity A1).
Tuân thủ các nguyên tắc:
1. 100% Parameterized queries chống SQL injection.
2. Transaction safe với tự động commit/rollback.
3. Đóng kết nối và cursor an toàn bằng contextmanager.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)


def _to_mysql_datetime(value: datetime | None):
    """Chuyển đổi thời gian có múi giờ sang UTC không múi giờ để lưu vào MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu Lead."""
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


def _ensure_utc_datetime(value: datetime | None) -> datetime | None:
    """Đảm bảo datetime từ MySQL (lưu theo UTC) luôn có tzinfo là timezone.utc."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_to_model(row: dict) -> Lead:
    """Chuyển đổi dictionary row từ MySQL thành đối tượng Lead."""
    return Lead(
        id=str(row["id"]),
        full_name=str(row["full_name"]),
        phone=str(row["phone"]),
        email=str(row["email"]) if row.get("email") is not None else None,
        interested_program_id=(
            str(row["interested_program_id"])
            if row.get("interested_program_id") is not None
            else None
        ),
        message=str(row["message"]) if row.get("message") is not None else None,
        source=str(row.get("source") or LEAD_SOURCE_PUBLIC_FORM),
        status=str(row.get("status") or LEAD_STATUS_NEW),
        assigned_to_user_id=(
            str(row["assigned_to_user_id"])
            if row.get("assigned_to_user_id") is not None
            else None
        ),
        assigned_at=_ensure_utc_datetime(row.get("assigned_at")),
        created_at=_ensure_utc_datetime(row.get("created_at")),
        updated_at=_ensure_utc_datetime(row.get("updated_at")),
        interested_program_code=row.get("interested_program_code"),
        interested_program_name=row.get("interested_program_name"),
        assigned_to_name=row.get("assigned_to_name"),
        assigned_to_email=row.get("assigned_to_email"),
    )


def insert_lead(lead: Lead) -> Lead:
    """
    Thêm một yêu cầu tư vấn mới vào bảng leads (SCRUM-125 - Activity A1).
    Tự sinh UUID và thời gian nếu chưa có.
    """
    now = datetime.now(timezone.utc)
    lead_id = lead.id or str(uuid.uuid4())
    created_at = lead.created_at or now
    updated_at = lead.updated_at or now

    sql = """
        INSERT INTO leads (
            id, full_name, phone, email, interested_program_id,
            message, source, status, assigned_to_user_id, assigned_at,
            created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s
        )
    """
    params = (
        lead_id,
        lead.full_name,
        lead.phone,
        lead.email,
        lead.interested_program_id,
        lead.message,
        lead.source or LEAD_SOURCE_PUBLIC_FORM,
        lead.status or LEAD_STATUS_NEW,
        lead.assigned_to_user_id,
        _to_mysql_datetime(lead.assigned_at),
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)

    return get_lead_by_id(lead_id) or Lead(
        id=lead_id,
        full_name=lead.full_name,
        phone=lead.phone,
        email=lead.email,
        interested_program_id=lead.interested_program_id,
        message=lead.message,
        source=lead.source or LEAD_SOURCE_PUBLIC_FORM,
        status=lead.status or LEAD_STATUS_NEW,
        assigned_to_user_id=lead.assigned_to_user_id,
        assigned_at=_ensure_utc_datetime(lead.assigned_at),
        created_at=_ensure_utc_datetime(created_at),
        updated_at=_ensure_utc_datetime(updated_at),
    )


def get_lead_by_id(lead_id: str) -> Lead | None:
    """
    Tra cứu một Lead theo ID (kèm thông tin chương trình đào tạo và nhân sự phụ trách nếu có).
    """
    sql = """
        SELECT
            l.id, l.full_name, l.phone, l.email, l.interested_program_id,
            l.message, l.source, l.status, l.assigned_to_user_id, l.assigned_at,
            l.created_at, l.updated_at,
            tp.code AS interested_program_code,
            tp.name AS interested_program_name,
            u.name AS assigned_to_name,
            u.email AS assigned_to_email
        FROM leads l
        LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
        LEFT JOIN users u ON l.assigned_to_user_id = u.id
        WHERE l.id = %s
    """
    with _database_cursor(write=False) as cursor:
        cursor.execute(sql, (lead_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_model(row)


def get_recent_lead_by_phone_or_email(
    phone: str,
    email: str | None,
    since: datetime,
) -> Lead | None:
    """
    Tra cứu Lead gần nhất có cùng số điện thoại hoặc email được tạo từ thời điểm `since` (SCRUM-125 Anti-Spam Rate Limit).
    Sử dụng hoàn toàn thời gian UTC, parameterized query chống SQL injection.
    """
    clean_phone = phone.strip()
    clean_email = email.strip().lower() if email else None
    since_mysql = _to_mysql_datetime(since)

    if clean_email:
        sql = """
            SELECT
                l.id, l.full_name, l.phone, l.email, l.interested_program_id,
                l.message, l.source, l.status, l.assigned_to_user_id, l.assigned_at,
                l.created_at, l.updated_at,
                tp.code AS interested_program_code,
                tp.name AS interested_program_name,
                u.name AS assigned_to_name,
                u.email AS assigned_to_email
            FROM leads l
            LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
            LEFT JOIN users u ON l.assigned_to_user_id = u.id
            WHERE (l.phone = %s OR l.email = %s)
              AND l.created_at >= %s
            ORDER BY l.created_at DESC
            LIMIT 1
        """
        params = (clean_phone, clean_email, since_mysql)
    else:
        sql = """
            SELECT
                l.id, l.full_name, l.phone, l.email, l.interested_program_id,
                l.message, l.source, l.status, l.assigned_to_user_id, l.assigned_at,
                l.created_at, l.updated_at,
                tp.code AS interested_program_code,
                tp.name AS interested_program_name,
                u.name AS assigned_to_name,
                u.email AS assigned_to_email
            FROM leads l
            LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
            LEFT JOIN users u ON l.assigned_to_user_id = u.id
            WHERE l.phone = %s
              AND l.created_at >= %s
            ORDER BY l.created_at DESC
            LIMIT 1
        """
        params = (clean_phone, since_mysql)

    with _database_cursor(write=False) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_model(row)


def count_leads() -> int:
    """Đếm tổng số lead trong bảng leads."""
    sql = "SELECT COUNT(*) AS total FROM leads"
    with _database_cursor(write=False) as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
        return int(row["total"]) if row else 0


SAFE_LEAD_SORT_COLUMNS: dict[str, str] = {
    "created_at": "l.created_at",
    "updated_at": "l.updated_at",
    "full_name": "l.full_name",
    "status": "l.status",
    "assigned_at": "l.assigned_at",
}


def list_leads(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status: str | None = None,
    interested_program_id: str | None = None,
    assigned_to_user_id: str | None = None,
    source: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: str = "created_at",
    sort_order: str = "DESC",
) -> tuple[list[Lead], int]:
    """
    Lấy danh sách Lead có phân trang, tìm kiếm và lọc đa điều kiện (SCRUM-126/127/128).
    - Hỗ trợ tìm kiếm theo họ tên, số điện thoại, email.
    - Lọc theo status, chương trình quan tâm, người phụ trách, nguồn, khoảng thời gian.
    - Sắp xếp an toàn theo whitelist SAFE_LEAD_SORT_COLUMNS.
    - Hoàn toàn dùng parameterized SQL chống tấn công injection.
    """
    limit = max(1, min(page_size, 100))
    offset = max(0, (page - 1) * limit)

    where_clauses: list[str] = []
    params: list = []

    if search and isinstance(search, str):
        clean_search = search.strip()[:100]
        if clean_search:
            pattern = f"%{clean_search}%"
            where_clauses.append("(l.full_name LIKE %s OR l.phone LIKE %s OR l.email LIKE %s)")
            params.extend([pattern, pattern, pattern])

    if status and isinstance(status, str):
        clean_status = status.strip().lower()
        if clean_status:
            where_clauses.append("l.status = %s")
            params.append(clean_status)

    if interested_program_id and isinstance(interested_program_id, str):
        clean_prog = interested_program_id.strip()
        if clean_prog:
            where_clauses.append("l.interested_program_id = %s")
            params.append(clean_prog)

    if assigned_to_user_id is not None and isinstance(assigned_to_user_id, str):
        clean_assignee = assigned_to_user_id.strip()
        if clean_assignee.lower() == "unassigned":
            where_clauses.append("l.assigned_to_user_id IS NULL")
        elif clean_assignee:
            where_clauses.append("l.assigned_to_user_id = %s")
            params.append(clean_assignee)

    if source and isinstance(source, str):
        clean_source = source.strip()
        if clean_source:
            where_clauses.append("l.source = %s")
            params.append(clean_source)

    if date_from is not None:
        where_clauses.append("l.created_at >= %s")
        params.append(_to_mysql_datetime(date_from))

    if date_to is not None:
        where_clauses.append("l.created_at <= %s")
        params.append(_to_mysql_datetime(date_to))

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sort_col = SAFE_LEAD_SORT_COLUMNS.get(sort_by, "l.created_at")
    sort_dir = "ASC" if str(sort_order).upper() == "ASC" else "DESC"

    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM leads l
        LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
        LEFT JOIN users u ON l.assigned_to_user_id = u.id
        {where_sql}
    """
    data_sql = f"""
        SELECT
            l.id, l.full_name, l.phone, l.email, l.interested_program_id,
            l.message, l.source, l.status, l.assigned_to_user_id, l.assigned_at,
            l.created_at, l.updated_at,
            tp.code AS interested_program_code,
            tp.name AS interested_program_name,
            u.name AS assigned_to_name,
            u.email AS assigned_to_email
        FROM leads l
        LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
        LEFT JOIN users u ON l.assigned_to_user_id = u.id
        {where_sql}
        ORDER BY {sort_col} {sort_dir}, l.id {sort_dir}
        LIMIT %s OFFSET %s
    """

    with _database_cursor(write=False) as cursor:
        cursor.execute(count_sql, tuple(params))
        count_row = cursor.fetchone()
        total = int(count_row["total"]) if count_row else 0

        cursor.execute(data_sql, tuple(params + [limit, offset]))
        rows = cursor.fetchall() or []
        leads = [_row_to_model(row) for row in rows]

    return leads, total



def update_lead_status(
    lead_id: str, new_status: str, updated_at: datetime | None = None
) -> Lead | None:
    """
    Cập nhật trạng thái của một Lead (SCRUM-126 - Activity A1/A3).
    """
    now = datetime.now(timezone.utc)
    target_updated_at = updated_at or now

    sql = """
        UPDATE leads
        SET status = %s, updated_at = %s
        WHERE id = %s
    """
    params = (
        new_status,
        _to_mysql_datetime(target_updated_at),
        lead_id,
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)
        if cursor.rowcount == 0:
            existing = get_lead_by_id(lead_id)
            if not existing:
                return None
            return existing

    return get_lead_by_id(lead_id)


def assign_lead(
    lead_id: str,
    assigned_to_user_id: str | None,
    assigned_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Lead | None:
    """
    Phân công hoặc gỡ phân công nhân sự quản lý Lead (SCRUM-127 - Activity A1/A2).
    Nếu assigned_to_user_id là None, gỡ phân công và đặt assigned_at = NULL.
    """
    now = datetime.now(timezone.utc)
    target_updated_at = updated_at or now
    target_assigned_at = (assigned_at or now) if assigned_to_user_id else None

    sql = """
        UPDATE leads
        SET assigned_to_user_id = %s, assigned_at = %s, updated_at = %s
        WHERE id = %s
    """
    params = (
        assigned_to_user_id,
        _to_mysql_datetime(target_assigned_at),
        _to_mysql_datetime(target_updated_at),
        lead_id,
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)
        if cursor.rowcount == 0:
            existing = get_lead_by_id(lead_id)
            if not existing:
                return None

    return get_lead_by_id(lead_id)


def _is_valid_user_uuid(val: str) -> bool:
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        parsed = uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError, AttributeError):
        return False


def get_assignable_lead_users() -> list[dict]:
    """
    Lấy danh sách người dùng có thể được phân công phụ trách Lead (SCRUM-127 - Activity A4).
    CHỈ lấy người dùng có trạng thái 'active', vai trò Tư vấn tuyển sinh ('consultant'),
    và có UUID hợp lệ (loại trừ các tài khoản demo không thể phân công).
    Không hiển thị: Quản trị viên, Quản lý đào tạo, Giảng viên, Học viên, Người dùng.
    Chỉ trả về các thông tin an toàn: id, name, email, role.
    """
    sql = """
        SELECT DISTINCT u.id, u.name, u.email, 'consultant' AS role
        FROM users u
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        WHERE u.status = 'active'
          AND (
              r.code = 'consultant'
              OR (u.role = 'consultant' AND NOT EXISTS (
                  SELECT 1 FROM user_roles ur2
                  JOIN roles r2 ON ur2.role_id = r2.id
                  WHERE ur2.user_id = u.id AND r2.code != 'consultant'
              ))
          )
          AND NOT EXISTS (
              SELECT 1 FROM user_roles ur3
              JOIN roles r3 ON ur3.role_id = r3.id
              WHERE ur3.user_id = u.id AND r3.code IN ('admin', 'training_manager', 'trainer', 'trainee')
          )
        ORDER BY u.name ASC, u.email ASC
    """
    with _database_cursor(write=False) as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall() or []

    return [
        {
            "id": str(r["id"]),
            "name": str(r["name"] or ""),
            "email": str(r["email"] or ""),
            "role": str(r["role"] or ""),
        }
        for r in rows
        if _is_valid_user_uuid(str(r["id"]))
    ]


def create_lead_assignment_history(
    lead_id: str,
    old_assigned_to_user_id: str | None,
    new_assigned_to_user_id: str | None,
    performed_by_user_id: str | None,
    created_at: datetime | None = None,
) -> dict:
    """
    Ghi nhận lịch sử chuyển giao / phân công Lead (SCRUM-127).
    """
    now = datetime.now(timezone.utc)
    target_created_at = created_at or now
    history_id = str(uuid.uuid4())

    sql = """
        INSERT INTO lead_assignment_history (
            id, lead_id, old_assigned_to_user_id, new_assigned_to_user_id,
            performed_by_user_id, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """
    params = (
        history_id,
        lead_id,
        old_assigned_to_user_id,
        new_assigned_to_user_id,
        performed_by_user_id,
        _to_mysql_datetime(target_created_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)

    return {
        "id": history_id,
        "lead_id": lead_id,
        "old_assigned_to_user_id": old_assigned_to_user_id,
        "new_assigned_to_user_id": new_assigned_to_user_id,
        "performed_by_user_id": performed_by_user_id,
        "created_at": _ensure_utc_datetime(target_created_at),
    }


def get_lead_assignment_history(lead_id: str) -> list[dict]:
    """
    Lấy danh sách lịch sử phân công của một Lead, sắp xếp mới nhất ở trên (SCRUM-127).
    Nạp tên nhân sự cũ, nhân sự mới và người thực hiện thao tác.
    """
    sql = """
        SELECT
            lah.id,
            lah.lead_id,
            lah.old_assigned_to_user_id,
            lah.new_assigned_to_user_id,
            lah.performed_by_user_id,
            lah.created_at,
            u_old.name AS old_assigned_to_name,
            u_new.name AS new_assigned_to_name,
            u_perf.name AS performed_by_name
        FROM lead_assignment_history lah
        LEFT JOIN users u_old ON lah.old_assigned_to_user_id = u_old.id
        LEFT JOIN users u_new ON lah.new_assigned_to_user_id = u_new.id
        LEFT JOIN users u_perf ON lah.performed_by_user_id = u_perf.id
        WHERE lah.lead_id = %s
        ORDER BY lah.seq DESC
    """
    with _database_cursor(write=False) as cursor:
        cursor.execute(sql, (lead_id,))
        rows = cursor.fetchall() or []

    return [
        {
            "id": str(r["id"]),
            "lead_id": str(r["lead_id"]),
            "old_assigned_to_user_id": str(r["old_assigned_to_user_id"]) if r.get("old_assigned_to_user_id") else None,
            "new_assigned_to_user_id": str(r["new_assigned_to_user_id"]) if r.get("new_assigned_to_user_id") else None,
            "performed_by_user_id": str(r["performed_by_user_id"]) if r.get("performed_by_user_id") else None,
            "old_assigned_to_name": r.get("old_assigned_to_name"),
            "new_assigned_to_name": r.get("new_assigned_to_name"),
            "performed_by_name": r.get("performed_by_name"),
            "created_at": _ensure_utc_datetime(r.get("created_at")),
        }
        for r in rows
    ]



def get_lead_by_phone(phone: str, exclude_lead_id: str | None = None) -> Lead | None:
    """
    Tra cứu Lead theo số điện thoại (dùng để kiểm tra trùng SĐT cho SCRUM-126).
    """
    clean_phone = phone.strip()
    if exclude_lead_id:
        sql = """
            SELECT
                l.id, l.full_name, l.phone, l.email, l.interested_program_id,
                l.message, l.source, l.status, l.assigned_to_user_id, l.assigned_at,
                l.created_at, l.updated_at,
                tp.code AS interested_program_code,
                tp.name AS interested_program_name,
                u.name AS assigned_to_name,
                u.email AS assigned_to_email
            FROM leads l
            LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
            LEFT JOIN users u ON l.assigned_to_user_id = u.id
            WHERE l.phone = %s AND l.id != %s
            LIMIT 1
        """
        params = (clean_phone, exclude_lead_id)
    else:
        sql = """
            SELECT
                l.id, l.full_name, l.phone, l.email, l.interested_program_id,
                l.message, l.source, l.status, l.assigned_to_user_id, l.assigned_at,
                l.created_at, l.updated_at,
                tp.code AS interested_program_code,
                tp.name AS interested_program_name,
                u.name AS assigned_to_name,
                u.email AS assigned_to_email
            FROM leads l
            LEFT JOIN training_programs tp ON l.interested_program_id = tp.id
            LEFT JOIN users u ON l.assigned_to_user_id = u.id
            WHERE l.phone = %s
            LIMIT 1
        """
        params = (clean_phone,)

    with _database_cursor(write=False) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_model(row)


def update_lead_info(
    lead_id: str,
    full_name: str,
    phone: str,
    email: str | None,
    source: str,
    interested_program_id: str | None,
    message: str | None = None,
    updated_at: datetime | None = None,
) -> Lead | None:
    """
    Cập nhật thông tin chi tiết một Lead (SCRUM-126 - Tạo và sửa Lead).
    """
    now = datetime.now(timezone.utc)
    target_updated_at = updated_at or now

    sql = """
        UPDATE leads
        SET full_name = %s,
            phone = %s,
            email = %s,
            source = %s,
            interested_program_id = %s,
            message = %s,
            updated_at = %s
        WHERE id = %s
    """
    params = (
        full_name,
        phone,
        email,
        source,
        interested_program_id,
        message,
        _to_mysql_datetime(target_updated_at),
        lead_id,
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)
        if cursor.rowcount == 0:
            existing = get_lead_by_id(lead_id)
            if not existing:
                return None
            return existing

    return get_lead_by_id(lead_id)


def delete_lead(lead_id: str) -> bool:
    """Xóa một lead khỏi cơ sở dữ liệu theo ID (SCRUM-126)."""
    sql = "DELETE FROM leads WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (lead_id,))
        return cursor.rowcount > 0


def delete_lead_for_testing(lead_id: str) -> bool:
    """Xóa một lead khỏi bảng (chỉ dùng cho cleanup trong testing)."""
    return delete_lead(lead_id)



