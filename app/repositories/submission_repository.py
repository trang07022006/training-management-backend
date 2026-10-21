"""
Repository cho Bài nộp và Chấm điểm nhanh (Speed Grading) - SCRUM-267.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from app.database.connection import get_db_connection
from app.models.submission import AssignmentSubmission, SubmissionGradeAuditLog


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


def _map_submission(row: dict) -> AssignmentSubmission:
    return AssignmentSubmission(
        id=str(row["id"]),
        assignment_id=str(row["assignment_id"]),
        student_id=str(row["student_id"]),
        submission_type=str(row.get("submission_type") or "both"),
        file_url=row.get("file_url"),
        file_name=row.get("file_name"),
        file_size=int(row["file_size"]) if row.get("file_size") is not None else None,
        repo_url=row.get("repo_url"),
        note=row.get("note"),
        submitted_at=row.get("submitted_at"),
        status=str(row.get("status") or "submitted"),
        score=float(row["score"]) if row.get("score") is not None else None,
        feedback=row.get("feedback"),
        graded_by=str(row["graded_by"]) if row.get("graded_by") else None,
        graded_at=row.get("graded_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        student_code=row.get("student_code"),
        student_name=row.get("student_name"),
        student_email=row.get("student_email"),
        assignment_title=row.get("assignment_title"),
        assignment_max_score=float(row.get("assignment_max_score") or 10.0),
        assignment_is_published=bool(row.get("assignment_is_published", False)),
        graded_by_name=row.get("graded_by_name"),
    )


def _map_audit_log(row: dict) -> SubmissionGradeAuditLog:
    return SubmissionGradeAuditLog(
        id=str(row["id"]),
        submission_id=str(row["submission_id"]),
        performed_by=str(row["performed_by"]),
        old_score=float(row["old_score"]) if row.get("old_score") is not None else None,
        new_score=float(row["new_score"]),
        old_feedback=row.get("old_feedback"),
        new_feedback=row.get("new_feedback"),
        change_reason=row.get("change_reason"),
        created_at=row.get("created_at"),
        performer_name=row.get("performer_name"),
    )


def get_submission_by_id(submission_id: str) -> AssignmentSubmission | None:
    sql = """
        SELECT s.*, 
               st.student_code, u.full_name AS student_name, u.email AS student_email,
               a.title AS assignment_title, a.max_score AS assignment_max_score, a.is_published AS assignment_is_published,
               gu.full_name AS graded_by_name
        FROM assignment_submissions s
        JOIN students st ON st.id = s.student_id
        JOIN users u ON u.id = st.user_id
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN users gu ON gu.id = s.graded_by
        WHERE s.id = %s
    """
    with _cursor() as cur:
        cur.execute(sql, (submission_id,))
        row = cur.fetchone()
    return _map_submission(row) if row else None


def list_submissions_by_assignment(assignment_id: str) -> list[AssignmentSubmission]:
    sql = """
        SELECT s.*, 
               st.student_code, u.full_name AS student_name, u.email AS student_email,
               a.title AS assignment_title, a.max_score AS assignment_max_score, a.is_published AS assignment_is_published,
               gu.full_name AS graded_by_name
        FROM assignment_submissions s
        JOIN students st ON st.id = s.student_id
        JOIN users u ON u.id = st.user_id
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN users gu ON gu.id = s.graded_by
        WHERE s.assignment_id = %s
        ORDER BY st.student_code ASC
    """
    with _cursor() as cur:
        cur.execute(sql, (assignment_id,))
        rows = cur.fetchall()
    return [_map_submission(r) for r in rows]


def get_speed_grading_navigation(assignment_id: str, current_submission_id: str) -> dict:
    """
    Tính toán ID bài nộp trước và tiếp theo để chuyển nhanh không cần quay lại danh sách.
    """
    sql = """
        SELECT id FROM assignment_submissions 
        WHERE assignment_id = %s 
        ORDER BY id ASC
    """
    with _cursor() as cur:
        cur.execute(sql, (assignment_id,))
        rows = cur.fetchall()

    ids = [str(r["id"]) for r in rows]
    total = len(ids)
    try:
        idx = ids.index(current_submission_id)
    except ValueError:
        return {"prev_id": None, "next_id": None, "index": 0, "total": total}

    prev_id = ids[idx - 1] if idx > 0 else None
    next_id = ids[idx + 1] if idx < total - 1 else None

    return {
        "prev_id": prev_id,
        "next_id": next_id,
        "index": idx + 1,
        "total": total,
    }


def grade_submission_with_audit(
    submission_id: str,
    new_score: float,
    feedback: str | None,
    performed_by: str,
    change_reason: str | None = None,
) -> AssignmentSubmission | None:
    """
    Chấm điểm hoặc sửa điểm bài nộp kèm ghi nhật ký (Audit Log) trong 1 Transaction.
    """
    now = _to_utc(datetime.now(timezone.utc))
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cur:
            # 1. Lấy bài nộp hiện tại
            cur.execute("SELECT score, feedback FROM assignment_submissions WHERE id = %s", (submission_id,))
            current = cur.fetchone()
            if not current:
                return None

            old_score = float(current["score"]) if current["score"] is not None else None
            old_feedback = current["feedback"]

            # 2. Cập nhật bài nộp
            cur.execute(
                """
                UPDATE assignment_submissions
                SET score = %s, feedback = %s, graded_by = %s, graded_at = %s, status = 'graded', updated_at = %s
                WHERE id = %s
                """,
                (new_score, feedback, performed_by, now, now, submission_id),
            )

            # 3. Ghi audit log nếu đây là lần sửa điểm hoặc chấm điểm lần đầu
            log_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO submission_grade_audit_logs
                    (id, submission_id, performed_by, old_score, new_score, old_feedback, new_feedback, change_reason, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (log_id, submission_id, performed_by, old_score, new_score, old_feedback, feedback, change_reason, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return get_submission_by_id(submission_id)


def publish_assignment_grades(assignment_id: str, published_by: str) -> bool:
    """
    Công bố điểm bài tập cho học viên (SCRUM-267).
    """
    now = _to_utc(datetime.now(timezone.utc))
    sql = """
        UPDATE assignments
        SET is_published = 1, published_at = %s, published_by = %s, updated_at = %s
        WHERE id = %s AND is_deleted = 0
    """
    with _cursor(write=True) as cur:
        cur.execute(sql, (now, published_by, now, assignment_id))
        return cur.rowcount > 0


def list_audit_logs_by_submission(submission_id: str) -> list[SubmissionGradeAuditLog]:
    sql = """
        SELECT l.*, u.full_name AS performer_name
        FROM submission_grade_audit_logs l
        JOIN users u ON u.id = l.performed_by
        WHERE l.submission_id = %s
        ORDER BY l.created_at DESC
    """
    with _cursor() as cur:
        cur.execute(sql, (submission_id,))
        rows = cur.fetchall()
    return [_map_audit_log(r) for r in rows]


def get_student_submission(assignment_id: str, student_id: str) -> AssignmentSubmission | None:
    sql = """
        SELECT s.*, 
               st.student_code, u.full_name AS student_name, u.email AS student_email,
               a.title AS assignment_title, a.max_score AS assignment_max_score, a.is_published AS assignment_is_published,
               gu.full_name AS graded_by_name
        FROM assignment_submissions s
        JOIN students st ON st.id = s.student_id
        JOIN users u ON u.id = st.user_id
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN users gu ON gu.id = s.graded_by
        WHERE s.assignment_id = %s AND s.student_id = %s
    """
    with _cursor() as cur:
        cur.execute(sql, (assignment_id, student_id))
        row = cur.fetchone()
    return _map_submission(row) if row else None
