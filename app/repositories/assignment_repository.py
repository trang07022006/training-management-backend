"""
Repository truy xuất cơ sở dữ liệu cho Bài tập và Yêu cầu làm lại (Assignment Repository) - SCRUM-269.
Bao gồm quản lý bài tập, bài nộp, các phiên bản nộp (versions) và lịch sử yêu cầu làm lại (rework requests).
"""

from datetime import datetime, timezone
import logging
from typing import Any
import uuid

from app.database.connection import get_db_connection
from app.models.assignment import (
    Assignment,
    AssignmentSubmission,
    SubmissionReworkRequest,
    SubmissionVersion,
    SUBMISSION_STATUS_NEEDS_REWORK,
    SUBMISSION_STATUS_RESUBMITTED,
    SUBMISSION_STATUS_SUBMITTED,
    REWORK_STATUS_OPEN,
    REWORK_STATUS_FULFILLED,
)

logger = logging.getLogger(__name__)


def get_assignment_by_id(assignment_id: str, connection=None) -> Assignment | None:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT a.*, c.class_code, u.name AS creator_name
                FROM assignments a
                JOIN classes c ON a.class_id = c.id
                LEFT JOIN users u ON a.created_by = u.id
                WHERE a.id = %s
                """,
                (assignment_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Assignment(
                id=row["id"],
                class_id=row["class_id"],
                title=row["title"],
                description=row.get("description"),
                due_date=row.get("due_date"),
                max_score=float(row.get("max_score") or 10.0),
                status=row["status"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                class_code=row.get("class_code"),
                creator_name=row.get("creator_name"),
            )
    finally:
        if should_close and conn:
            conn.close()


def get_submission_by_id(submission_id: str, connection=None) -> AssignmentSubmission | None:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT s.*,
                       st.student_code, st.full_name AS student_name, st.email AS student_email,
                       a.title AS assignment_title, a.max_score AS assignment_max_score
                FROM assignment_submissions s
                JOIN students st ON s.student_id = st.id
                JOIN assignments a ON s.assignment_id = a.id
                WHERE s.id = %s
                """,
                (submission_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            sub = AssignmentSubmission(
                id=row["id"],
                assignment_id=row["assignment_id"],
                student_id=row["student_id"],
                status=row["status"],
                score=float(row["score"]) if row.get("score") is not None else None,
                feedback=row.get("feedback"),
                graded_by=row.get("graded_by"),
                graded_at=row.get("graded_at"),
                rework_count=int(row.get("rework_count") or 0),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                student_code=row.get("student_code"),
                student_name=row.get("student_name"),
                student_email=row.get("student_email"),
                assignment_title=row.get("assignment_title"),
                assignment_max_score=float(row.get("assignment_max_score") or 10.0),
            )

            # Lấy versions và rework history
            sub.versions = list_submission_versions(sub.id, connection=conn)
            sub.rework_history = list_rework_requests(sub.id, connection=conn)
            sub.current_rework_request = get_open_rework_request(sub.id, connection=conn)
            return sub
    finally:
        if should_close and conn:
            conn.close()


def get_submission_for_update(submission_id: str, connection) -> AssignmentSubmission | None:
    """Lấy bài nộp với khóa SELECT ... FOR UPDATE trong transaction."""
    with connection.cursor(dictionary=True) as cursor:
        cursor.execute(
            """
            SELECT s.*,
                   st.student_code, st.full_name AS student_name, st.email AS student_email,
                   a.title AS assignment_title, a.max_score AS assignment_max_score
            FROM assignment_submissions s
            JOIN students st ON s.student_id = st.id
            JOIN assignments a ON s.assignment_id = a.id
            WHERE s.id = %s
            FOR UPDATE
            """,
            (submission_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        sub = AssignmentSubmission(
            id=row["id"],
            assignment_id=row["assignment_id"],
            student_id=row["student_id"],
            status=row["status"],
            score=float(row["score"]) if row.get("score") is not None else None,
            feedback=row.get("feedback"),
            graded_by=row.get("graded_by"),
            graded_at=row.get("graded_at"),
            rework_count=int(row.get("rework_count") or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            student_code=row.get("student_code"),
            student_name=row.get("student_name"),
            student_email=row.get("student_email"),
            assignment_title=row.get("assignment_title"),
            assignment_max_score=float(row.get("assignment_max_score") or 10.0),
        )
        sub.versions = list_submission_versions(sub.id, connection=connection)
        sub.rework_history = list_rework_requests(sub.id, connection=connection)
        sub.current_rework_request = get_open_rework_request(sub.id, connection=connection)
        return sub


def get_submission_by_assignment_and_student(
    assignment_id: str, student_id: str, connection=None
) -> AssignmentSubmission | None:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id FROM assignment_submissions
                WHERE assignment_id = %s AND student_id = %s
                """,
                (assignment_id, student_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return get_submission_by_id(row["id"], connection=conn)
    finally:
        if should_close and conn:
            conn.close()


def list_submissions_by_assignment(assignment_id: str, connection=None) -> list[AssignmentSubmission]:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT s.*,
                       st.student_code, st.full_name AS student_name, st.email AS student_email,
                       a.title AS assignment_title, a.max_score AS assignment_max_score
                FROM assignment_submissions s
                JOIN students st ON s.student_id = st.id
                JOIN assignments a ON s.assignment_id = a.id
                WHERE s.assignment_id = %s
                ORDER BY s.created_at ASC
                """,
                (assignment_id,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                sub = AssignmentSubmission(
                    id=row["id"],
                    assignment_id=row["assignment_id"],
                    student_id=row["student_id"],
                    status=row["status"],
                    score=float(row["score"]) if row.get("score") is not None else None,
                    feedback=row.get("feedback"),
                    graded_by=row.get("graded_by"),
                    graded_at=row.get("graded_at"),
                    rework_count=int(row.get("rework_count") or 0),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    student_code=row.get("student_code"),
                    student_name=row.get("student_name"),
                    student_email=row.get("student_email"),
                    assignment_title=row.get("assignment_title"),
                    assignment_max_score=float(row.get("assignment_max_score") or 10.0),
                )
                sub.versions = list_submission_versions(sub.id, connection=conn)
                sub.current_rework_request = get_open_rework_request(sub.id, connection=conn)
                results.append(sub)
            return results
    finally:
        if should_close and conn:
            conn.close()


def list_submission_versions(submission_id: str, connection=None) -> list[SubmissionVersion]:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT * FROM submission_versions
                WHERE submission_id = %s
                ORDER BY version_number ASC
                """,
                (submission_id,),
            )
            rows = cursor.fetchall()
            return [
                SubmissionVersion(
                    id=r["id"],
                    submission_id=r["submission_id"],
                    version_number=r["version_number"],
                    submission_type=r["submission_type"],
                    content=r.get("content"),
                    file_url=r.get("file_url"),
                    file_name=r.get("file_name"),
                    file_size=r.get("file_size"),
                    repo_url=r.get("repo_url"),
                    submitted_at=r["submitted_at"],
                    rework_request_id=r.get("rework_request_id"),
                )
                for r in rows
            ]
    finally:
        if should_close and conn:
            conn.close()


def get_latest_submission_version(submission_id: str, connection=None) -> SubmissionVersion | None:
    versions = list_submission_versions(submission_id, connection=connection)
    return versions[-1] if versions else None


def list_rework_requests(submission_id: str, connection=None) -> list[SubmissionReworkRequest]:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT r.*, u.name AS requested_by_name, v.version_number AS fulfilled_version_number
                FROM submission_rework_requests r
                LEFT JOIN users u ON r.requested_by = u.id
                LEFT JOIN submission_versions v ON r.fulfilled_version_id = v.id
                WHERE r.submission_id = %s
                ORDER BY r.request_number ASC
                """,
                (submission_id,),
            )
            rows = cursor.fetchall()
            return [
                SubmissionReworkRequest(
                    id=r["id"],
                    submission_id=r["submission_id"],
                    submission_version_id=r.get("submission_version_id"),
                    request_number=r["request_number"],
                    comment=r["comment"],
                    new_deadline=r["new_deadline"],
                    requested_by=r["requested_by"],
                    status=r["status"],
                    created_at=r["created_at"],
                    fulfilled_at=r.get("fulfilled_at"),
                    fulfilled_version_id=r.get("fulfilled_version_id"),
                    requested_by_name=r.get("requested_by_name"),
                    fulfilled_version_number=r.get("fulfilled_version_number"),
                )
                for r in rows
            ]
    finally:
        if should_close and conn:
            conn.close()


def get_open_rework_request(submission_id: str, connection=None) -> SubmissionReworkRequest | None:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT r.*, u.name AS requested_by_name
                FROM submission_rework_requests r
                LEFT JOIN users u ON r.requested_by = u.id
                WHERE r.submission_id = %s AND r.status = 'open'
                LIMIT 1
                """,
                (submission_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return SubmissionReworkRequest(
                id=row["id"],
                submission_id=row["submission_id"],
                submission_version_id=row.get("submission_version_id"),
                request_number=row["request_number"],
                comment=row["comment"],
                new_deadline=row["new_deadline"],
                requested_by=row["requested_by"],
                status=row["status"],
                created_at=row["created_at"],
                fulfilled_at=row.get("fulfilled_at"),
                fulfilled_version_id=row.get("fulfilled_version_id"),
                requested_by_name=row.get("requested_by_name"),
            )
    finally:
        if should_close and conn:
            conn.close()


def insert_rework_request(req: SubmissionReworkRequest, connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO submission_rework_requests (
                id, submission_id, submission_version_id, request_number,
                comment, new_deadline, requested_by, status, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                req.id,
                req.submission_id,
                req.submission_version_id,
                req.request_number,
                req.comment,
                req.new_deadline,
                req.requested_by,
                req.status,
                req.created_at,
            ),
        )


def update_submission_status_and_rework_count(
    submission_id: str, status: str, rework_count: int, connection
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE assignment_submissions
            SET status = %s, rework_count = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (status, rework_count, submission_id),
        )


def insert_submission_version(ver: SubmissionVersion, connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO submission_versions (
                id, submission_id, version_number, submission_type,
                content, file_url, file_name, file_size, repo_url,
                submitted_at, rework_request_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                ver.id,
                ver.submission_id,
                ver.version_number,
                ver.submission_type,
                ver.content,
                ver.file_url,
                ver.file_name,
                ver.file_size,
                ver.repo_url,
                ver.submitted_at,
                ver.rework_request_id,
            ),
        )


def fulfill_rework_request(
    rework_request_id: str, fulfilled_version_id: str, connection
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE submission_rework_requests
            SET status = 'fulfilled', fulfilled_at = NOW(), fulfilled_version_id = %s
            WHERE id = %s
            """,
            (fulfilled_version_id, rework_request_id),
        )


def is_instructor_assigned_to_class(
    instructor_id: str, class_id: str, connection=None
) -> bool:
    """Kiểm tra giảng viên có được phân công giảng dạy bất kỳ môn nào của lớp."""
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM class_subject_instructors csi
                JOIN class_subjects cs ON csi.class_subject_id = cs.id
                WHERE cs.class_id = %s AND csi.instructor_id = %s
                """,
                (class_id, instructor_id),
            )
            count = cursor.fetchone()[0]
            return count > 0
    finally:
        if should_close and conn:
            conn.close()


def get_student_by_user_id(user_id: str, connection=None) -> dict | None:
    """Lấy thông tin học viên dựa trên user_id của tài khoản."""
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT * FROM students WHERE user_id = %s
                """,
                (user_id,),
            )
            return cursor.fetchone()
    finally:
        if should_close and conn:
            conn.close()


def is_student_enrolled_in_class(
    student_id: str, class_id: str, connection=None
) -> bool:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM class_enrollments
                WHERE class_id = %s AND student_id = %s AND status = 'enrolled'
                """,
                (class_id, student_id),
            )
            count = cursor.fetchone()[0]
            return count > 0
    finally:
        if should_close and conn:
            conn.close()


def create_assignment(assignment: Assignment, connection=None) -> Assignment:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assignments (
                    id, class_id, title, description, due_date, max_score,
                    status, created_by, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    assignment.id,
                    assignment.class_id,
                    assignment.title,
                    assignment.description,
                    assignment.due_date,
                    assignment.max_score,
                    assignment.status,
                    assignment.created_by,
                    assignment.created_at,
                    assignment.updated_at,
                ),
            )
            if should_close:
                conn.commit()
            return assignment
    finally:
        if should_close and conn:
            conn.close()


def create_submission(submission: AssignmentSubmission, initial_version: SubmissionVersion | None = None, connection=None) -> AssignmentSubmission:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO assignment_submissions (
                    id, assignment_id, student_id, status, score, feedback,
                    graded_by, graded_at, rework_count, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    submission.id,
                    submission.assignment_id,
                    submission.student_id,
                    submission.status,
                    submission.score,
                    submission.feedback,
                    submission.graded_by,
                    submission.graded_at,
                    submission.rework_count,
                    submission.created_at,
                    submission.updated_at,
                ),
            )
            if initial_version:
                insert_submission_version(initial_version, conn)
            if should_close:
                conn.commit()
            return submission
    finally:
        if should_close and conn:
            conn.close()


def list_assignments_by_class(class_id: str, connection=None) -> list[Assignment]:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT a.*, c.class_code, u.name AS creator_name
                FROM assignments a
                JOIN classes c ON a.class_id = c.id
                LEFT JOIN users u ON a.created_by = u.id
                WHERE a.class_id = %s
                ORDER BY a.created_at DESC
                """,
                (class_id,),
            )
            rows = cursor.fetchall()
            return [
                Assignment(
                    id=r["id"],
                    class_id=r["class_id"],
                    title=r["title"],
                    description=r.get("description"),
                    due_date=r.get("due_date"),
                    max_score=float(r.get("max_score") or 10.0),
                    status=r["status"],
                    created_by=r["created_by"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    class_code=r.get("class_code"),
                    creator_name=r.get("creator_name"),
                )
                for r in rows
            ]
    finally:
        if should_close and conn:
            conn.close()


def grade_submission(
    submission_id: str,
    score: float,
    feedback: str | None,
    graded_by: str,
    connection=None,
) -> AssignmentSubmission | None:
    should_close = False
    conn = connection
    if conn is None:
        conn = get_db_connection()
        should_close = True

    now_utc = datetime.now(timezone.utc)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE assignment_submissions
                SET score = %s, feedback = %s, graded_by = %s, graded_at = %s, status = 'graded', updated_at = %s
                WHERE id = %s
                """,
                (score, feedback, graded_by, now_utc, now_utc, submission_id),
            )
            if should_close:
                conn.commit()
        return get_submission_by_id(submission_id, conn)
    finally:
        if should_close and conn:
            conn.close()
