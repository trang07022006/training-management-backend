"""
Repository truy cập dữ liệu cho SubjectSession (Buổi học của môn học) - SCRUM-129.
Đảm bảo:
1. 100% Parameterized queries chống SQL Injection.
2. Quản lý kết nối, transaction và con trỏ nghiêm ngặt.
3. Hỗ trợ sắp xếp và chuẩn hóa thứ tự buổi học (1..N) không xung đột khóa duy nhất.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.database.connection import get_db_connection
from app.models.subject_session import SubjectSession


ALLOWED_UPDATE_FIELDS = {"topic", "objective"}


def _to_mysql_datetime(value: datetime | None):
    """Chuyển đổi thời gian có múi giờ sang UTC không múi giờ để lưu vào MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu SubjectSession."""
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


def _row_to_model(row: dict) -> SubjectSession:
    """Chuyển đổi dictionary row từ MySQL thành đối tượng SubjectSession."""
    return SubjectSession(
        id=str(row["id"]),
        subject_id=str(row["subject_id"]),
        session_number=int(row["session_number"]),
        topic=str(row["topic"]),
        objective=str(row["objective"]),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def insert_subject_session(session: SubjectSession) -> SubjectSession:
    """
    Thêm một buổi học mới vào cơ sở dữ liệu (SCRUM-129 - Activity A1/A3).
    Sử dụng hoàn toàn parameterized query.
    """
    created_at = session.created_at or datetime.now(timezone.utc)
    updated_at = session.updated_at or created_at

    sql = """
        INSERT INTO subject_sessions (
            id,
            subject_id,
            session_number,
            topic,
            objective,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        session.id,
        session.subject_id,
        session.session_number,
        session.topic,
        session.objective,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, values)

    return SubjectSession(
        id=session.id,
        subject_id=session.subject_id,
        session_number=session.session_number,
        topic=session.topic,
        objective=session.objective,
        created_at=created_at,
        updated_at=updated_at,
    )


def get_subject_session_by_id(session_id: str) -> SubjectSession | None:
    """
    Tìm kiếm buổi học theo ID duy nhất (SCRUM-129).
    Trả về None nếu không tìm thấy.
    """
    sql = """
        SELECT
            id,
            subject_id,
            session_number,
            topic,
            objective,
            created_at,
            updated_at
        FROM subject_sessions
        WHERE id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (session_id,))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_model(row)


def get_subject_session_by_subject_and_number(
    subject_id: str, session_number: int
) -> SubjectSession | None:
    """
    Tìm kiếm buổi học theo mã môn học và số thứ tự buổi (SCRUM-129).
    """
    sql = """
        SELECT
            id,
            subject_id,
            session_number,
            topic,
            objective,
            created_at,
            updated_at
        FROM subject_sessions
        WHERE subject_id = %s AND session_number = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (subject_id, session_number))
        row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_model(row)


def list_subject_sessions_by_subject(subject_id: str) -> list[SubjectSession]:
    """
    Lấy danh sách tất cả các buổi học của một môn học, sắp xếp theo session_number ASC (SCRUM-129 - Activity A2).
    """
    sql = """
        SELECT
            id,
            subject_id,
            session_number,
            topic,
            objective,
            created_at,
            updated_at
        FROM subject_sessions
        WHERE subject_id = %s
        ORDER BY session_number ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (subject_id,))
        rows = cursor.fetchall()

    return [_row_to_model(r) for r in rows]


def count_subject_sessions(subject_id: str) -> int:
    """Đếm tổng số buổi học hiện có của một môn học (SCRUM-129)."""
    sql = "SELECT COUNT(*) as cnt FROM subject_sessions WHERE subject_id = %s"
    with _database_cursor() as cursor:
        cursor.execute(sql, (subject_id,))
        row = cursor.fetchone()

    return int(row["cnt"]) if row else 0


def get_max_session_number(subject_id: str) -> int:
    """
    Lấy số thứ tự buổi học lớn nhất hiện có của môn học.
    Trả về 0 nếu môn học chưa có buổi nào.
    """
    sql = "SELECT MAX(session_number) as max_num FROM subject_sessions WHERE subject_id = %s"
    with _database_cursor() as cursor:
        cursor.execute(sql, (subject_id,))
        row = cursor.fetchone()

    if row and row.get("max_num") is not None:
        return int(row["max_num"])
    return 0


def exists_session_number(
    subject_id: str, session_number: int, exclude_id: str | None = None
) -> bool:
    """Kiểm tra sự tồn tại của số thứ tự buổi học trong môn học."""
    if exclude_id is not None:
        sql = """
            SELECT 1 FROM subject_sessions
            WHERE subject_id = %s AND session_number = %s AND id != %s
            LIMIT 1
        """
        params = (subject_id, session_number, exclude_id)
    else:
        sql = """
            SELECT 1 FROM subject_sessions
            WHERE subject_id = %s AND session_number = %s
            LIMIT 1
        """
        params = (subject_id, session_number)

    with _database_cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()

    return row is not None


def update_subject_session_fields(
    session_id: str, fields: dict[str, Any]
) -> SubjectSession | None:
    """
    Cập nhật các trường được chỉ định của buổi học (topic, objective) - SCRUM-129 Activity A4.
    Chỉ cho phép cập nhật các trường trong whitelist ALLOWED_UPDATE_FIELDS.
    Tự động cập nhật updated_at theo UTC.
    """
    valid_fields = {k: v for k, v in fields.items() if k in ALLOWED_UPDATE_FIELDS}
    if not valid_fields:
        return get_subject_session_by_id(session_id)

    now = datetime.now(timezone.utc)
    set_clauses = [f"{col} = %s" for col in valid_fields.keys()]
    set_clauses.append("updated_at = %s")

    values = list(valid_fields.values())
    values.append(_to_mysql_datetime(now))
    values.append(session_id)

    sql = f"""
        UPDATE subject_sessions
        SET {', '.join(set_clauses)}
        WHERE id = %s
    """

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, tuple(values))

    return get_subject_session_by_id(session_id)


def delete_subject_session(session_id: str) -> bool:
    """
    Xóa một buổi học theo ID (SCRUM-129 Activity A4).
    Trả về True nếu có bản ghi bị xóa, ngược lại False.
    """
    sql = "DELETE FROM subject_sessions WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (session_id,))
        return cursor.rowcount > 0


def normalize_session_numbers(subject_id: str) -> None:
    """
    Chuẩn hóa lại số thứ tự các buổi học của một môn học thành chuỗi liên tục 1..N (SCRUM-129 Activity A4).
    Tránh xung đột khóa unique bằng cơ chế 2 bước (shift offset rồi gán liên tục).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # 1. Lấy danh sách sessions hiện có theo thứ tự tăng dần
            cursor.execute(
                """
                SELECT id FROM subject_sessions
                WHERE subject_id = %s
                ORDER BY session_number ASC, created_at ASC
                """,
                (subject_id,),
            )
            rows = cursor.fetchall()
            if not rows:
                return

            # 2. Shift các số thứ tự để tránh duplicate key
            cursor.execute(
                """
                UPDATE subject_sessions
                SET session_number = session_number + 10000
                WHERE subject_id = %s
                """,
                (subject_id,),
            )

            # 3. Gán lại 1..N
            now = _to_mysql_datetime(datetime.now(timezone.utc))
            for idx, r in enumerate(rows, start=1):
                cursor.execute(
                    """
                    UPDATE subject_sessions
                    SET session_number = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (idx, now, r["id"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def bulk_update_session_numbers(
    subject_id: str, ordered_session_ids: list[str]
) -> list[SubjectSession]:
    """
    Sắp xếp lại các buổi học theo mảng ordered_session_ids truyền vào (SCRUM-129 Activity A4).
    Thực hiện trong 1 transaction an toàn, gán 1..len(ordered_session_ids).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # Shift các số thứ tự để tránh duplicate key
            cursor.execute(
                """
                UPDATE subject_sessions
                SET session_number = session_number + 10000
                WHERE subject_id = %s
                """,
                (subject_id,),
            )

            now = _to_mysql_datetime(datetime.now(timezone.utc))
            for idx, sid in enumerate(ordered_session_ids, start=1):
                cursor.execute(
                    """
                    UPDATE subject_sessions
                    SET session_number = %s, updated_at = %s
                    WHERE id = %s AND subject_id = %s
                    """,
                    (idx, now, sid, subject_id),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return list_subject_sessions_by_subject(subject_id)
