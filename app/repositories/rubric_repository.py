"""
Repository cho RubricTemplate và RubricCriteria - SCRUM-268.

Phụ thuộc project (import từ app hiện có):
  - app.database.connection.get_db_connection
  - app.models.rubric.RubricTemplate, RubricCriteria

100% Parameterized queries, transaction-safe.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
import uuid

from app.database.connection import get_db_connection
from app.models.rubric import RubricCriteria, RubricTemplate


# ---------------------------------------------------------------------------
# Helpers dùng chung
# ---------------------------------------------------------------------------

def _to_utc(dt: datetime | None):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _cursor(write: bool = False):
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            yield cur
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def _map_criteria(row: dict) -> RubricCriteria:
    return RubricCriteria(
        id=str(row["id"]),
        template_id=str(row["template_id"]),
        name=str(row["name"]),
        description=row.get("description"),
        max_score=float(row["max_score"]),
        weight=float(row["weight"]),
        order_index=int(row.get("order_index") or 0),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _map_template(row: dict) -> RubricTemplate:
    return RubricTemplate(
        id=str(row["id"]),
        name=str(row["name"]),
        description=row.get("description"),
        created_by=str(row["created_by"]),
        is_deleted=bool(row.get("is_deleted", False)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# RubricTemplate
# ---------------------------------------------------------------------------

def insert_rubric_template(template: RubricTemplate) -> RubricTemplate | None:
    """Tạo mẫu rubric mới (chưa kèm tiêu chí)."""
    now = _to_utc(datetime.now(timezone.utc))
    sql = """
        INSERT INTO rubric_templates
            (id, name, description, created_by, is_deleted, created_at, updated_at)
        VALUES (%s, %s, %s, %s, 0, %s, %s)
    """
    with _cursor(write=True) as cur:
        cur.execute(sql, (template.id, template.name, template.description,
                          template.created_by, now, now))
    return get_rubric_template_by_id(template.id)


def get_rubric_template_by_id(
    template_id: str,
    include_deleted: bool = False,
) -> RubricTemplate | None:
    """Lấy mẫu rubric kèm danh sách tiêu chí."""
    cond = "" if include_deleted else "AND is_deleted = 0"
    sql = f"""
        SELECT id, name, description, created_by, is_deleted, created_at, updated_at
        FROM rubric_templates
        WHERE id = %s {cond}
    """
    with _cursor() as cur:
        cur.execute(sql, (template_id,))
        row = cur.fetchone()
    if not row:
        return None
    t = _map_template(row)
    t.criteria = list_criteria_by_template(template_id)
    return t


def list_rubric_templates(
    created_by: str | None = None,
    include_deleted: bool = False,
) -> list[RubricTemplate]:
    """Danh sách mẫu rubric, tùy chọn lọc theo người tạo."""
    conds: list[str] = []
    params: list[Any] = []
    if not include_deleted:
        conds.append("is_deleted = 0")
    if created_by:
        conds.append("created_by = %s")
        params.append(created_by)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    sql = f"""
        SELECT id, name, description, created_by, is_deleted, created_at, updated_at
        FROM rubric_templates {where}
        ORDER BY created_at DESC
    """
    with _cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    templates = []
    for row in rows:
        t = _map_template(row)
        t.criteria = list_criteria_by_template(t.id)
        templates.append(t)
    return templates


def update_rubric_template(
    template_id: str, fields: dict[str, Any]
) -> RubricTemplate | None:
    """Cập nhật name / description (whitelist)."""
    allowed = {"name", "description"}
    valid = {k: v for k, v in fields.items() if k in allowed}
    if not valid:
        return get_rubric_template_by_id(template_id)
    now = _to_utc(datetime.now(timezone.utc))
    sets = [f"{k} = %s" for k in valid] + ["updated_at = %s"]
    vals = list(valid.values()) + [now, template_id]
    sql = f"UPDATE rubric_templates SET {', '.join(sets)} WHERE id = %s AND is_deleted = 0"
    with _cursor(write=True) as cur:
        cur.execute(sql, tuple(vals))
    return get_rubric_template_by_id(template_id)


def soft_delete_rubric_template(template_id: str) -> bool:
    """Xóa mềm mẫu rubric."""
    now = _to_utc(datetime.now(timezone.utc))
    sql = "UPDATE rubric_templates SET is_deleted = 1, updated_at = %s WHERE id = %s AND is_deleted = 0"
    with _cursor(write=True) as cur:
        cur.execute(sql, (now, template_id))
        return cur.rowcount > 0


def template_in_use(template_id: str) -> bool:
    """Kiểm tra template đang được gắn với bài tập chưa bị xóa."""
    sql = "SELECT 1 FROM assignments WHERE rubric_template_id = %s AND is_deleted = 0 LIMIT 1"
    with _cursor() as cur:
        cur.execute(sql, (template_id,))
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# RubricCriteria
# ---------------------------------------------------------------------------

def list_criteria_by_template(template_id: str) -> list[RubricCriteria]:
    sql = """
        SELECT id, template_id, name, description, max_score, weight, order_index,
               created_at, updated_at
        FROM rubric_criteria
        WHERE template_id = %s
        ORDER BY order_index ASC, created_at ASC
    """
    with _cursor() as cur:
        cur.execute(sql, (template_id,))
        return [_map_criteria(r) for r in cur.fetchall()]


def get_criteria_by_id(criteria_id: str) -> RubricCriteria | None:
    sql = """
        SELECT id, template_id, name, description, max_score, weight, order_index,
               created_at, updated_at
        FROM rubric_criteria WHERE id = %s
    """
    with _cursor() as cur:
        cur.execute(sql, (criteria_id,))
        row = cur.fetchone()
    return _map_criteria(row) if row else None


def replace_criteria_batch(
    template_id: str,
    criteria_list: list[RubricCriteria],
) -> list[RubricCriteria]:
    """
    Thay toàn bộ tiêu chí của template trong 1 transaction.
    Dùng khi cập nhật lại danh sách tiêu chí rubric.
    """
    now = _to_utc(datetime.now(timezone.utc))
    sql_del = "DELETE FROM rubric_criteria WHERE template_id = %s"
    sql_ins = """
        INSERT INTO rubric_criteria
            (id, template_id, name, description, max_score, weight, order_index,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql_del, (template_id,))
            for c in criteria_list:
                cur.execute(sql_ins, (
                    c.id, template_id, c.name, c.description,
                    c.max_score, c.weight, c.order_index, now, now,
                ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return list_criteria_by_template(template_id)
