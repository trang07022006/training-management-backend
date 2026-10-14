from contextlib import contextmanager
from datetime import datetime
import json

from app.database.connection import get_db_connection


@contextmanager
def _cursor(write=False):
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


SESSION_SELECT = """
SELECT s.id, s.class_id, s.topic, s.starts_at, s.ends_at, s.classroom_id,
       s.status, s.cancellation_reason, s.created_at, s.updated_at,
       c.name AS class_name, co.id AS course_id, co.code AS course_code,
       co.name AS course_name, i.id AS instructor_id, i.name AS instructor_name,
       i.email AS instructor_email, r.name AS classroom_name, c.delivery_mode
FROM class_sessions s
JOIN training_classes c ON c.id = s.class_id
JOIN courses co ON co.id = c.course_id
JOIN instructors i ON i.id = c.instructor_id
LEFT JOIN classrooms r ON r.id = s.classroom_id
"""


def list_sessions(status=None):
    sql = SESSION_SELECT
    params = ()
    if status:
        sql += " WHERE s.status = %s"
        params = (status,)
    sql += " ORDER BY s.starts_at, s.id"
    with _cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def get_session(session_id, for_update=False, cursor=None):
    sql = SESSION_SELECT + " WHERE s.id = %s"
    if for_update:
        sql += " FOR UPDATE"
    own_cursor = cursor is None
    if own_cursor:
        with _cursor() as active_cursor:
            active_cursor.execute(sql, (session_id,))
            return active_cursor.fetchone()
    cursor.execute(sql, (session_id,))
    return cursor.fetchone()


def get_notification_status(session_id):
    with _cursor() as cursor:
        cursor.execute("""
            SELECT n.id, n.recipient_email, n.status, n.error_code,
                   n.attempted_at, n.created_at, l.action, l.created_at AS change_created_at
            FROM schedule_notification_log n
            JOIN schedule_change_log l ON l.id = n.change_id
            WHERE l.session_id = %s
            ORDER BY n.id
        """, (session_id,))
        return cursor.fetchall()


def apply_change(session_id, actor_user_id, action, changes, request_key=None):
    connection = get_db_connection()
    notification_rows = []
    try:
        with connection.cursor(dictionary=True) as cursor:
            if request_key:
                cursor.execute("SELECT id, session_id, action FROM schedule_change_log WHERE request_key = %s", (request_key,))
                prior = cursor.fetchone()
                if prior:
                    if prior["session_id"] != session_id or prior["action"] != action:
                        connection.rollback()
                        return {"conflict": "IDEMPOTENCY_CONFLICT"}
                    existing = get_session(prior["session_id"], cursor=cursor)
                    cursor.execute("""
                        SELECT id, recipient_email FROM schedule_notification_log
                        WHERE change_id = %s AND status = 'pending'
                    """, (prior["id"],))
                    pending_notifications = cursor.fetchall()
                    connection.rollback()
                    return {"session": existing, "change_id": prior["id"],
                            "notifications": pending_notifications, "duplicate": True}

            old_session = get_session(session_id, for_update=True, cursor=cursor)
            if old_session is None:
                connection.rollback()
                return None
            if old_session["status"] != "scheduled":
                connection.rollback()
                return {"conflict": "SESSION_NOT_SCHEDULED"}

            next_values = {
                "topic": changes.get("topic", old_session["topic"]),
                "starts_at": changes.get("starts_at", old_session["starts_at"]),
                "ends_at": changes.get("ends_at", old_session["ends_at"]),
                "classroom_id": changes.get("classroom_id", old_session["classroom_id"]),
                "status": "cancelled" if action == "cancelled" else old_session["status"],
                "cancellation_reason": changes.get("cancellation_reason", old_session["cancellation_reason"]),
            }
            if next_values["ends_at"] <= next_values["starts_at"]:
                connection.rollback()
                return {"conflict": "INVALID_TIME_RANGE"}

            if next_values["classroom_id"] is not None:
                cursor.execute("SELECT id FROM classrooms WHERE id = %s", (next_values["classroom_id"],))
                if cursor.fetchone() is None:
                    connection.rollback()
                    return {"conflict": "INVALID_CLASSROOM"}

            if action in {"edited", "rescheduled"}:
                cursor.execute("""
                    SELECT s.id FROM class_sessions s
                    JOIN training_classes c ON c.id = s.class_id
                    JOIN training_classes target_class ON target_class.id = %s
                    WHERE s.id <> %s AND s.status = 'scheduled'
                      AND s.starts_at < %s AND s.ends_at > %s
                      AND (c.instructor_id = target_class.instructor_id
                           OR (s.classroom_id IS NOT NULL AND s.classroom_id = %s))
                    FOR UPDATE
                """, (old_session["class_id"], session_id, next_values["ends_at"],
                      next_values["starts_at"], next_values["classroom_id"]))
                if cursor.fetchone():
                    connection.rollback()
                    return {"conflict": "SCHEDULE_CONFLICT"}

            old_values = {key: old_session[key] for key in ("topic", "starts_at", "ends_at", "classroom_id", "status", "cancellation_reason")}
            cursor.execute("""
                UPDATE class_sessions
                SET topic = %s, starts_at = %s, ends_at = %s, classroom_id = %s,
                    status = %s, cancellation_reason = %s
                WHERE id = %s
            """, (next_values["topic"], next_values["starts_at"], next_values["ends_at"],
                  next_values["classroom_id"], next_values["status"],
                  next_values["cancellation_reason"], session_id))
            cursor.execute("""
                INSERT INTO schedule_change_log
                    (session_id, actor_user_id, action, old_values, new_values, request_key)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (session_id, actor_user_id, action, json.dumps(old_values, default=str),
                  json.dumps(next_values, default=str), request_key))
            change_id = cursor.lastrowid
            cursor.execute("""
                SELECT DISTINCT email FROM (
                    SELECT i.email AS email FROM training_classes c
                    JOIN instructors i ON i.id = c.instructor_id WHERE c.id = %s
                    UNION
                    SELECT st.email AS email FROM class_enrollments e
                    JOIN students st ON st.id = e.student_id WHERE e.class_id = %s
                ) affected
            """, (old_session["class_id"], old_session["class_id"]))
            recipients = [row["email"] for row in cursor.fetchall()]
            for email in recipients:
                cursor.execute("""
                    INSERT INTO schedule_notification_log (change_id, recipient_email, status)
                    VALUES (%s, %s, 'pending')
                """, (change_id, email))
                notification_rows.append({"id": cursor.lastrowid, "recipient_email": email})
            new_session = get_session(session_id, cursor=cursor)
        connection.commit()
        return {"session": new_session, "change_id": change_id, "notifications": notification_rows, "duplicate": False}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_notification(notification_id, status, error_code=None):
    with _cursor(write=True) as cursor:
        cursor.execute("""
            UPDATE schedule_notification_log
            SET status = %s, error_code = %s, attempted_at = %s
            WHERE id = %s AND status = 'pending'
        """, (status, error_code, datetime.utcnow(), notification_id))
