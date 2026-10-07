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
        assigned_at=row.get("assigned_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
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
        assigned_at=lead.assigned_at,
        created_at=created_at,
        updated_at=updated_at,
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


def get_assignable_lead_users() -> list[dict]:
    """
    Lấy danh sách người dùng có thể được phân công phụ trách Lead (SCRUM-127 - Activity A4).
    Chỉ lấy người dùng có trạng thái 'active' và vai trò 'admin' hoặc 'trainer'.
    Chỉ trả về các thông tin an toàn: id, name, email, role.
    """
    sql = """
        SELECT id, name, email, role
        FROM users
        WHERE status = 'active' AND role IN ('admin', 'trainer')
        ORDER BY name ASC, email ASC
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
    ]


def delete_lead_for_testing(lead_id: str) -> bool:
    """Xóa một lead khỏi bảng (chỉ dùng cho cleanup trong testing)."""
    sql = "DELETE FROM leads WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (lead_id,))
        return cursor.rowcount > 0



