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


def list_leads(page: int = 1, page_size: int = 20) -> tuple[list[Lead], int]:
    """
    Lấy danh sách Lead có phân trang (SCRUM-126/127).
    Mặc định sắp xếp theo created_at DESC.
    """
    limit = max(1, min(page_size, 100))
    offset = max(0, (page - 1) * limit)

    count_sql = "SELECT COUNT(*) AS total FROM leads"
    data_sql = """
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
        ORDER BY l.created_at DESC
        LIMIT %s OFFSET %s
    """

    with _database_cursor(write=False) as cursor:
        cursor.execute(count_sql)
        count_row = cursor.fetchone()
        total = int(count_row["total"]) if count_row else 0

        cursor.execute(data_sql, (limit, offset))
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


def delete_lead_for_testing(lead_id: str) -> bool:
    """Xóa một lead khỏi bảng (chỉ dùng cho cleanup trong testing)."""
    sql = "DELETE FROM leads WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (lead_id,))
        return cursor.rowcount > 0


