"""
Repository cho Assignment và AssignmentGrade - SCRUM-268.

Phụ thuộc project (import từ app hiện có):
  - app.database.connection.get_db_connection
  - app.models.assignment.*

Join với các bảng hiện có:
  - classes          (class_code)
  - rubric_templates (rubric_template_name)
  - students         (student_code)
  - users            (full_name)
  - rubric_criteria  (name, weight, max_score, order_index)

Công thức tính điểm tổng (thang 10):
  total_score = Σ(score_i / max_score_i * weight_i) / 10
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
import uuid

from app.database.connection import get_db_connection
from app.models.assignment import Assignment, AssignmentCriteriaGrade, AssignmentGrade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_utc(dt: datetime | None):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


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


def _map_assignment(row: dict) -> Assignment:
    return Assignment(
        id=str(row["id"]),
        class_id=str(row["class_id"]),
        title=str(row["title"]),
        description=row.get("description"),
        rubric_template_id=str(row["rubric_template_id"]) if row.get("rubric_template_id") else None,
        rubric_template_name=row.get("rubric_template_name"),
        max_score=float(row.get("max_score") or 10.0),
        created_by=str(row["created_by"]),
        is_deleted=bool(row.get("is_deleted", False)),
        class_code=row.get("class_code"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _map_criteria_grade(row: dict) -> AssignmentCriteriaGrade:
    return AssignmentCriteriaGrade(
        id=str(row["id"]),
        grade_id=str(row["grade_id"]),
        criteria_id=str(row["criteria_id"]),
        score=float(row["score"]),
        comment=row.get("comment"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        criteria_name=row.get("criteria_name"),
        criteria_weight=float(row["criteria_weight"]) if row.get("criteria_weight") is not None else None,
        criteria_max_score=float(row["criteria_max_score"]) if row.get("criteria_max_score") is not None else None,
        criteria_order_index=int(row["criteria_order_index"]) if row.get("criteria_order_index") is not None else None,
    )


def _map_grade(row: dict) -> AssignmentGrade:
    return AssignmentGrade(
        id=str(row["id"]),
        assignment_id=str(row["assignment_id"]),
        student_id=str(row["student_id"]),
        total_score=float(row["total_score"]) if row.get("total_score") is not None else None,
        graded_by=str(row["graded_by"]) if row.get("graded_by") else None,
        graded_at=row.get("graded_at"),
        feedback=row.get("feedback"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        student_code=row.get("student_code"),
        student_name=row.get("student_name"),
        graded_by_name=row.get("graded_by_name"),
    )


# ---------------------------------------------------------------------------
# Assignment CRUD
# ---------------------------------------------------------------------------

def insert_assignment(a: Assignment) -> Assignment | None:
    now = _to_utc(datetime.now(timezone.utc))
    sql = """
        INSERT INTO assignments
            (id, class_id, title, description, rubric_template_id,
             max_score, created_by, is_deleted, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
    """
    with _cursor(write=True) as cur:
        cur.execute(sql, (a.id, a.class_id, a.title, a.description,
                          a.rubric_template_id, a.max_score, a.created_by, now, now))
    return get_assignment_by_id(a.id)


def get_assignment_by_id(assignment_id: str) -> Assignment | None:
    sql = """
        SELECT a.id, a.class_id, a.title, a.description,
               a.rubric_template_id, rt.name AS rubric_template_name,
               a.max_score, a.created_by, a.is_deleted,
               a.created_at, a.updated_at,
               c.class_code
        FROM assignments a
        LEFT JOIN rubric_templates rt ON rt.id = a.rubric_template_id
        LEFT JOIN classes c ON c.id = a.class_id
        WHERE a.id = %s AND a.is_deleted = 0
    """
    with _cursor() as cur:
        cur.execute(sql, (assignment_id,))
        row = cur.fetchone()
    return _map_assignment(row) if row else None


def list_assignments_by_class(class_id: str) -> list[Assignment]:
    sql = """
        SELECT a.id, a.class_id, a.title, a.description,
               a.rubric_template_id, rt.name AS rubric_template_name,
               a.max_score, a.created_by, a.is_deleted,
               a.created_at, a.updated_at, c.class_code
        FROM assignments a
        LEFT JOIN rubric_templates rt ON rt.id = a.rubric_template_id
        LEFT JOIN classes c ON c.id = a.class_id
        WHERE a.class_id = %s AND a.is_deleted = 0
        ORDER BY a.created_at DESC
    """
    with _cursor() as cur:
        cur.execute(sql, (class_id,))
        return [_map_assignment(r) for r in cur.fetchall()]


def update_assignment(assignment_id: str, fields: dict[str, Any]) -> Assignment | None:
    allowed = {"title", "description", "rubric_template_id", "max_score"}
    valid = {k: v for k, v in fields.items() if k in allowed}
    if not valid:
        return get_assignment_by_id(assignment_id)
    now = _to_utc(datetime.now(timezone.utc))
    sets = [f"{k} = %s" for k in valid] + ["updated_at = %s"]
    vals = list(valid.values()) + [now, assignment_id]
    sql = f"UPDATE assignments SET {', '.join(sets)} WHERE id = %s AND is_deleted = 0"
    with _cursor(write=True) as cur:
        cur.execute(sql, tuple(vals))
    return get_assignment_by_id(assignment_id)


def soft_delete_assignment(assignment_id: str) -> bool:
    now = _to_utc(datetime.now(timezone.utc))
    sql = "UPDATE assignments SET is_deleted = 1, updated_at = %s WHERE id = %s AND is_deleted = 0"
    with _cursor(write=True) as cur:
        cur.execute(sql, (now, assignment_id))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# AssignmentGrade - xem điểm
# ---------------------------------------------------------------------------

def get_grade_by_id(grade_id: str) -> AssignmentGrade | None:
    sql = """
        SELECT ag.id, ag.assignment_id, ag.student_id,
               ag.total_score, ag.graded_by, ag.graded_at,
               ag.feedback, ag.created_at, ag.updated_at,
               s.student_code, u.full_name AS student_name,
               gu.full_name AS graded_by_name
        FROM assignment_grades ag
        JOIN students s ON s.id = ag.student_id
        JOIN users u ON u.id = s.user_id
        LEFT JOIN users gu ON gu.id = ag.graded_by
        WHERE ag.id = %s
    """
    with _cursor() as cur:
        cur.execute(sql, (grade_id,))
        row = cur.fetchone()
    if not row:
        return None
    g = _map_grade(row)
    g.criteria_grades = list_criteria_grades_by_grade(g.id)
    return g


def get_grade_by_assignment_and_student(
    assignment_id: str, student_id: str
) -> AssignmentGrade | None:
    sql = """
        SELECT ag.id, ag.assignment_id, ag.student_id,
               ag.total_score, ag.graded_by, ag.graded_at,
               ag.feedback, ag.created_at, ag.updated_at,
               s.student_code, u.full_name AS student_name,
               gu.full_name AS graded_by_name
        FROM assignment_grades ag
        JOIN students s ON s.id = ag.student_id
        JOIN users u ON u.id = s.user_id
        LEFT JOIN users gu ON gu.id = ag.graded_by
        WHERE ag.assignment_id = %s AND ag.student_id = %s
    """
    with _cursor() as cur:
        cur.execute(sql, (assignment_id, student_id))
        row = cur.fetchone()
    if not row:
        return None
    g = _map_grade(row)
    g.criteria_grades = list_criteria_grades_by_grade(g.id)
    return g


def list_grades_by_assignment(assignment_id: str) -> list[AssignmentGrade]:
    """Giảng viên xem điểm tất cả học viên của bài tập."""
    sql = """
        SELECT ag.id, ag.assignment_id, ag.student_id,
               ag.total_score, ag.graded_by, ag.graded_at,
               ag.feedback, ag.created_at, ag.updated_at,
               s.student_code, u.full_name AS student_name,
               gu.full_name AS graded_by_name
        FROM assignment_grades ag
        JOIN students s ON s.id = ag.student_id
        JOIN users u ON u.id = s.user_id
        LEFT JOIN users gu ON gu.id = ag.graded_by
        WHERE ag.assignment_id = %s
        ORDER BY s.student_code ASC
    """
    with _cursor() as cur:
        cur.execute(sql, (assignment_id,))
        rows = cur.fetchall()
    grades = []
    for row in rows:
        g = _map_grade(row)
        g.criteria_grades = list_criteria_grades_by_grade(g.id)
        grades.append(g)
    return grades


def list_grades_by_student(student_id: str) -> list[AssignmentGrade]:
    """Học viên xem tất cả điểm của bản thân."""
    sql = """
        SELECT ag.id, ag.assignment_id, ag.student_id,
               ag.total_score, ag.graded_by, ag.graded_at,
               ag.feedback, ag.created_at, ag.updated_at,
               s.student_code, u.full_name AS student_name,
               gu.full_name AS graded_by_name
        FROM assignment_grades ag
        JOIN students s ON s.id = ag.student_id
        JOIN users u ON u.id = s.user_id
        LEFT JOIN users gu ON gu.id = ag.graded_by
        WHERE ag.student_id = %s
        ORDER BY ag.graded_at DESC
    """
    with _cursor() as cur:
        cur.execute(sql, (student_id,))
        rows = cur.fetchall()
    grades = []
    for row in rows:
        g = _map_grade(row)
        g.criteria_grades = list_criteria_grades_by_grade(g.id)
        grades.append(g)
    return grades


# ---------------------------------------------------------------------------
# AssignmentGrade - chấm điểm (upsert, tính tổng tự động)
# ---------------------------------------------------------------------------

def upsert_grade_with_criteria(
    assignment_id: str,
    student_id: str,
    graded_by: str,
    feedback: str | None,
    criteria_scores: list[dict],   # [{criteria_id, score, comment?}, ...]
    rubric_criteria: list[dict],   # [{id, weight, max_score}, ...] - lấy từ rubric_repository
) -> AssignmentGrade:
    """
    Chấm điểm học viên theo rubric - SCRUM-268.
    Atomic transaction:
      1. Upsert assignment_grades
      2. Upsert từng assignment_criteria_grades
      3. Tính total_score tự động:
         total = Σ(score_i / max_score_i * weight_i) / 10  (quy về thang 10)
    """
    now = _to_utc(datetime.now(timezone.utc))
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            # 1. Upsert assignment_grades
            cur.execute(
                "SELECT id FROM assignment_grades WHERE assignment_id=%s AND student_id=%s",
                (assignment_id, student_id),
            )
            existing = cur.fetchone()

            if existing:
                grade_id = str(existing["id"])
                cur.execute(
                    """UPDATE assignment_grades
                       SET graded_by=%s, graded_at=%s, feedback=%s, updated_at=%s
                       WHERE id=%s""",
                    (graded_by, now, feedback, now, grade_id),
                )
            else:
                grade_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO assignment_grades
                           (id, assignment_id, student_id, graded_by,
                            graded_at, feedback, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (grade_id, assignment_id, student_id, graded_by,
                     now, feedback, now, now),
                )

            # 2. Build lookup maps
            weight_map = {
                c["id"]: (float(c["weight"]), float(c["max_score"]))
                for c in rubric_criteria
            }
            score_map = {s["criteria_id"]: s for s in criteria_scores}

            # 3. Upsert criteria grades + tính tổng
            total = 0.0
            for crit_id, (weight, max_score) in weight_map.items():
                entry = score_map.get(crit_id)
                score = float(entry["score"]) if entry else 0.0
                comment = entry.get("comment") if entry else None

                cur.execute(
                    "SELECT id FROM assignment_criteria_grades WHERE grade_id=%s AND criteria_id=%s",
                    (grade_id, crit_id),
                )
                cg = cur.fetchone()
                if cg:
                    cur.execute(
                        """UPDATE assignment_criteria_grades
                           SET score=%s, comment=%s, updated_at=%s WHERE id=%s""",
                        (score, comment, now, str(cg["id"])),
                    )
                else:
                    cur.execute(
                        """INSERT INTO assignment_criteria_grades
                               (id, grade_id, criteria_id, score, comment, created_at, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (str(uuid.uuid4()), grade_id, crit_id, score, comment, now, now),
                    )
                # Tích lũy điểm: score_i/max_score_i * weight_i (% của 100)
                total += (score / max_score * weight) if max_score > 0 else 0.0

            # Quy về thang 10: tổng trọng số = 100 => chia 10
            computed = round(total / 10.0, 2)

            cur.execute(
                "UPDATE assignment_grades SET total_score=%s, updated_at=%s WHERE id=%s",
                (computed, now, grade_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return get_grade_by_id(grade_id)


# ---------------------------------------------------------------------------
# AssignmentCriteriaGrade
# ---------------------------------------------------------------------------

def list_criteria_grades_by_grade(grade_id: str) -> list[AssignmentCriteriaGrade]:
    sql = """
        SELECT acg.id, acg.grade_id, acg.criteria_id,
               acg.score, acg.comment, acg.created_at, acg.updated_at,
               rc.name AS criteria_name,
               rc.weight AS criteria_weight,
               rc.max_score AS criteria_max_score,
               rc.order_index AS criteria_order_index
        FROM assignment_criteria_grades acg
        JOIN rubric_criteria rc ON rc.id = acg.criteria_id
        WHERE acg.grade_id = %s
        ORDER BY rc.order_index ASC
    """
    with _cursor() as cur:
        cur.execute(sql, (grade_id,))
        return [_map_criteria_grade(r) for r in cur.fetchall()]
