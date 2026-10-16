"""
Repository quản lý Ngày nghỉ lễ (Holiday Repository) - SCRUM-224.
"""

from datetime import date, datetime, timezone
import uuid
from app.database.connection import get_db_connection
from app.models.holiday import Holiday


def insert_holiday(holiday: Holiday) -> Holiday:
    """Thêm mới ngày nghỉ lễ vào cơ sở dữ liệu (SCRUM-224)."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        if not holiday.id:
            holiday.id = str(uuid.uuid4())
        holiday.created_at = holiday.created_at or now
        holiday.updated_at = holiday.updated_at or now

        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO holidays (id, holiday_date, name, description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    holiday.id,
                    holiday.holiday_date,
                    holiday.name.strip(),
                    holiday.description.strip() if holiday.description else None,
                    holiday.created_at,
                    holiday.updated_at,
                ),
            )
            conn.commit()
        return holiday
    finally:
        conn.close()


def get_holiday_by_id(holiday_id: str) -> Holiday | None:
    """Tìm ngày nghỉ lễ theo ID."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, holiday_date, name, description, created_at, updated_at FROM holidays WHERE id = %s",
                (holiday_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Holiday(
                id=row["id"],
                holiday_date=row["holiday_date"],
                name=row["name"],
                description=row["description"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    finally:
        conn.close()


def get_holiday_by_date(holiday_date: date | str) -> Holiday | None:
    """Tìm ngày nghỉ lễ theo ngày cụ thể (YYYY-MM-DD)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, holiday_date, name, description, created_at, updated_at FROM holidays WHERE holiday_date = %s",
                (holiday_date,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Holiday(
                id=row["id"],
                holiday_date=row["holiday_date"],
                name=row["name"],
                description=row["description"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
    finally:
        conn.close()


def list_holidays(
    from_date: date | str | None = None,
    to_date: date | str | None = None,
) -> list[Holiday]:
    """Lấy danh sách các ngày nghỉ lễ, sắp xếp theo ngày tăng dần."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            conditions = []
            params = []
            if from_date:
                conditions.append("holiday_date >= %s")
                params.append(from_date)
            if to_date:
                conditions.append("holiday_date <= %s")
                params.append(to_date)

            sql = "SELECT id, holiday_date, name, description, created_at, updated_at FROM holidays"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY holiday_date ASC"

            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [
                Holiday(
                    id=row["id"],
                    holiday_date=row["holiday_date"],
                    name=row["name"],
                    description=row["description"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
    finally:
        conn.close()


def delete_holiday(holiday_id: str) -> bool:
    """Xóa ngày nghỉ lễ theo ID."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM holidays WHERE id = %s", (holiday_id,))
            conn.commit()
            return cursor.rowcount > 0
    finally:
        conn.close()
