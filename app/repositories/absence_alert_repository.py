"""
Repository quản lý dữ liệu cờ cảnh báo vắng học viên (SCRUM-257 - AC2).
Bao gồm:
- Truy vấn trạng thái cảnh báo của học viên theo lớp (student_absence_alerts)
- Upsert trạng thái cờ và đợt cảnh báo (alert_round) phục vụ AC2 và AC3
- Lấy danh sách cảnh báo đang bật của học viên trên hồ sơ (Student Profile)
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional
import uuid

from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def get_student_absence_alert(class_id: str, student_id: str, conn=None) -> Optional[dict[str, Any]]:
    """
    Lấy bản ghi trạng thái cảnh báo hiện hành của một học viên trong một lớp.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    id,
                    class_id,
                    student_id,
                    program_id,
                    status,
                    absent_sessions,
                    total_sessions,
                    absence_rate,
                    threshold,
                    alert_round,
                    first_triggered_at,
                    last_evaluated_at,
                    resolved_at
                FROM student_absence_alerts
                WHERE class_id = %s AND student_id = %s
                LIMIT 1
                """,
                (class_id, student_id),
            )
            row = cursor.fetchone()
            if row:
                row["absence_rate"] = float(row["absence_rate"])
                row["threshold"] = float(row["threshold"])
            return row
    finally:
        if should_close:
            conn.close()


def get_class_absence_alerts(class_id: str, conn=None) -> dict[str, dict[str, Any]]:
    """
    Lấy bản đồ trạng thái cảnh báo của tất cả học viên trong một lớp (Key: student_id).
    Single batch query chống N+1.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    id,
                    class_id,
                    student_id,
                    program_id,
                    status,
                    absent_sessions,
                    total_sessions,
                    absence_rate,
                    threshold,
                    alert_round,
                    first_triggered_at,
                    last_evaluated_at,
                    resolved_at
                FROM student_absence_alerts
                WHERE class_id = %s
                """,
                (class_id,),
            )
            rows = cursor.fetchall() or []
            res: dict[str, dict[str, Any]] = {}
            for r in rows:
                r["absence_rate"] = float(r["absence_rate"])
                r["threshold"] = float(r["threshold"])
                res[r["student_id"]] = r
            return res
    finally:
        if should_close:
            conn.close()


def get_active_absence_alerts_by_student(student_id: str, conn=None) -> list[dict[str, Any]]:
    """
    Lấy danh sách tất cả các cảnh báo vắng đang BẬT ('active') của học viên trên hồ sơ (AC2).
    Chỉ lấy các cảnh báo đang hoạt động, kèm thông tin lớp và chương trình đào tạo.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    saa.id AS alert_id,
                    saa.class_id,
                    saa.student_id,
                    saa.program_id,
                    saa.status,
                    saa.absent_sessions,
                    saa.total_sessions,
                    saa.absence_rate,
                    saa.threshold,
                    saa.alert_round,
                    saa.first_triggered_at,
                    saa.last_evaluated_at,
                    c.class_code,
                    tp.code AS program_code,
                    tp.name AS program_name
                FROM student_absence_alerts saa
                JOIN classes c ON saa.class_id = c.id
                LEFT JOIN training_programs tp ON saa.program_id = tp.id
                WHERE saa.student_id = %s AND saa.status = 'active'
                ORDER BY saa.last_evaluated_at DESC
                """,
                (student_id,),
            )
            rows = cursor.fetchall() or []
            for r in rows:
                r["absence_rate"] = float(r["absence_rate"])
                r["threshold"] = float(r["threshold"])
                if r.get("first_triggered_at"):
                    r["first_triggered_at_str"] = r["first_triggered_at"].isoformat()
                if r.get("last_evaluated_at"):
                    r["last_evaluated_at_str"] = r["last_evaluated_at"].isoformat()
            return rows
    finally:
        if should_close:
            conn.close()


def upsert_student_absence_alert(
    class_id: str,
    student_id: str,
    program_id: str,
    status: str,
    absent_sessions: int,
    total_sessions: int,
    absence_rate: float,
    threshold: float,
    conn=None,
) -> dict[str, Any]:
    """
    Cập nhật hoặc thêm mới trạng thái cảnh báo cho một học viên trong lớp.
    - Quản lý vòng đời cờ (active / inactive).
    - Khi chuyển từ inactive -> active hoặc tạo mới active: alert_round tăng thêm 1 và đánh dấu transition newly_triggered=True.
    - Khi chuyển từ active -> inactive: resolved_at được cập nhật.
    - Trả về thông tin bản ghi sau khi lưu cùng cờ newly_triggered (phục vụ AC3 gửi thông báo).
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        now = datetime.now(timezone.utc)
        existing = get_student_absence_alert(class_id, student_id, conn=conn)

        newly_triggered = False
        newly_resolved = False

        if not existing:
            # Chưa từng có bản ghi
            alert_id = str(uuid.uuid4())
            alert_round = 1 if status == "active" else 0
            first_triggered_at = now if status == "active" else now
            resolved_at = now if status == "inactive" else None
            newly_triggered = (status == "active")

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO student_absence_alerts (
                        id, class_id, student_id, program_id, status,
                        absent_sessions, total_sessions, absence_rate, threshold,
                        alert_round, first_triggered_at, last_evaluated_at, resolved_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        alert_id,
                        class_id,
                        student_id,
                        program_id,
                        status,
                        absent_sessions,
                        total_sessions,
                        absence_rate,
                        threshold,
                        alert_round,
                        first_triggered_at,
                        now,
                        resolved_at,
                    ),
                )
        else:
            alert_id = existing["id"]
            old_status = existing["status"]
            old_round = existing["alert_round"]

            if status == "active":
                if old_status == "inactive":
                    # Tắt rồi bật lại -> round mới
                    alert_round = old_round + 1
                    first_triggered_at = now
                    resolved_at = None
                    newly_triggered = True
                else:
                    # Đang active sẵn -> giữ nguyên round
                    alert_round = old_round
                    first_triggered_at = existing["first_triggered_at"]
                    resolved_at = None
            else:
                # inactive
                alert_round = old_round
                first_triggered_at = existing["first_triggered_at"]
                resolved_at = now if old_status == "active" else existing.get("resolved_at")
                if old_status == "active":
                    newly_resolved = True

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE student_absence_alerts
                    SET status = %s,
                        program_id = %s,
                        absent_sessions = %s,
                        total_sessions = %s,
                        absence_rate = %s,
                        threshold = %s,
                        alert_round = %s,
                        first_triggered_at = %s,
                        last_evaluated_at = %s,
                        resolved_at = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        program_id,
                        absent_sessions,
                        total_sessions,
                        absence_rate,
                        threshold,
                        alert_round,
                        first_triggered_at,
                        now,
                        resolved_at,
                        alert_id,
                    ),
                )

        conn.commit()

        return {
            "id": alert_id,
            "class_id": class_id,
            "student_id": student_id,
            "program_id": program_id,
            "status": status,
            "absent_sessions": absent_sessions,
            "total_sessions": total_sessions,
            "absence_rate": absence_rate,
            "threshold": threshold,
            "alert_round": alert_round,
            "first_triggered_at": first_triggered_at,
            "last_evaluated_at": now,
            "resolved_at": resolved_at,
            "newly_triggered": newly_triggered,
            "newly_resolved": newly_resolved,
        }
    finally:
        if should_close:
            conn.close()


def get_alert_recipients_for_class(
    class_id: str, program_id: str | None = None, conn=None
) -> list[dict[str, Any]]:
    """
    Xác định danh sách người nhận thông báo hợp lệ khi cờ cảnh báo vắng được bật (SCRUM-257 AC3):
    1. Giảng viên được phân công cho lớp (qua class_subject_instructors hoặc class_schedules).
    2. Quản lý đào tạo (training_manager) trong phạm vi quản lý chương trình / lớp.
    Chỉ tài khoản active.
    Deduplicate: Người có nhiều vai trò chỉ nhận 1 thông báo cho cùng sự kiện.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            # 1. Giảng viên phân công lớp
            cursor.execute(
                """
                SELECT DISTINCT u.id, COALESCE(u.name, '') AS full_name, u.email, 'trainer' AS recipient_role
                FROM users u
                WHERE (u.status = 'active' OR u.status IS NULL)
                  AND (
                      EXISTS (
                          SELECT 1 FROM class_subjects cs
                          JOIN class_subject_instructors csi ON cs.id = csi.class_subject_id
                          WHERE cs.class_id = %s AND csi.instructor_id = u.id
                      )
                      OR EXISTS (
                          SELECT 1 FROM class_schedules sched
                          WHERE sched.class_id = %s AND sched.instructor_id = u.id
                      )
                  )
                """,
                (class_id, class_id),
            )
            trainers = cursor.fetchall() or []

            # 2. Quản lý đào tạo (training_manager)
            cursor.execute(
                """
                SELECT DISTINCT u.id, COALESCE(u.name, '') AS full_name, u.email, 'training_manager' AS recipient_role
                FROM users u
                LEFT JOIN user_roles ur ON u.id = ur.user_id
                LEFT JOIN roles r ON ur.role_id = r.id
                WHERE (u.status = 'active' OR u.status IS NULL)
                  AND (
                      LOWER(COALESCE(u.role, '')) = 'training_manager'
                      OR LOWER(COALESCE(r.code, '')) = 'training_manager'
                      OR LOWER(COALESCE(r.name, '')) = 'training_manager'
                      OR LOWER(COALESCE(r.id, '')) = 'role-id-training-manager'
                  )
                """
            )
            managers = cursor.fetchall() or []

        # Deduplicate theo user ID (Nếu một người vừa là giảng viên vừa là quản lý thì chỉ nhận 1 thông báo)
        recipients_map: dict[str, dict[str, Any]] = {}
        for t in trainers:
            uid = str(t["id"]).strip()
            if uid:
                recipients_map[uid] = t

        for m in managers:
            uid = str(m["id"]).strip()
            if uid and uid not in recipients_map:
                recipients_map[uid] = m

        return list(recipients_map.values())
    finally:
        if should_close:
            conn.close()


def insert_absence_alert_notification(notif: dict[str, Any], conn=None) -> bool:
    """
    Lưu bản ghi thông báo cảnh báo vắng vào absence_alert_notifications (AC3).
    Dùng UNIQUE KEY uq_alert_round_recipient (alert_id, alert_round, recipient_id) để chống trùng lặp.
    Trả về True nếu chèn mới thành công, False nếu trùng lặp (đã tồn tại).
    """
    notif_id = notif.get("id") or str(uuid.uuid4())
    alert_id = notif["alert_id"]
    alert_round = notif.get("alert_round", 1)
    recipient_id = notif["recipient_id"]
    recipient_role = notif.get("recipient_role", "training_manager")
    title = notif["title"]
    message = notif["message"]
    class_id = notif["class_id"]
    student_id = notif["student_id"]
    created_at = notif.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT IGNORE INTO absence_alert_notifications (
                    id, alert_id, alert_round, recipient_id, recipient_role,
                    title, message, class_id, student_id, created_at, is_read
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                """,
                (
                    notif_id,
                    alert_id,
                    alert_round,
                    recipient_id,
                    recipient_role,
                    title,
                    message,
                    class_id,
                    student_id,
                    created_at,
                ),
            )
            inserted = (cursor.rowcount > 0)
        conn.commit()
        return inserted
    finally:
        if should_close:
            conn.close()


def get_absence_alert_notifications_by_recipient(
    recipient_id: str, unread_only: bool = False, conn=None
) -> list[dict[str, Any]]:
    """
    Lấy danh sách thông báo cảnh báo vắng của một người dùng cụ thể (AC3).
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            query = """
                SELECT n.id, n.alert_id, n.alert_round, n.recipient_id, n.recipient_role,
                       n.title, n.message, n.class_id, n.student_id, n.created_at, n.is_read,
                       c.class_code, c.class_code AS class_name,
                       s.student_code, s.full_name AS student_name
                FROM absence_alert_notifications n
                LEFT JOIN classes c ON n.class_id = c.id
                LEFT JOIN students s ON n.student_id = s.id
                WHERE n.recipient_id = %s
            """
            params: list[Any] = [recipient_id]
            if unread_only:
                query += " AND n.is_read = FALSE"
            query += " ORDER BY n.created_at DESC"
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall() or []
            for r in rows:
                if hasattr(r.get("created_at"), "isoformat"):
                    r["created_at"] = r["created_at"].isoformat()
            return rows
    finally:
        if should_close:
            conn.close()


def mark_absence_alert_notification_as_read(notif_id: str, user_id: str, conn=None) -> bool:
    """
    Đánh dấu thông báo cảnh báo vắng là đã đọc (kiểm tra đúng quyền sở hữu của recipient).
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE absence_alert_notifications
                SET is_read = TRUE
                WHERE id = %s AND recipient_id = %s
                """,
                (notif_id, user_id),
            )
            updated = (cursor.rowcount > 0)
        conn.commit()
        return updated
    finally:
        if should_close:
            conn.close()


def list_absence_alert_notifications_for_alert(
    alert_id: str, alert_round: int | None = None, conn=None
) -> list[dict[str, Any]]:
    """
    Truy vấn lịch sử thông báo đã phát cho một đợt cảnh báo (AC3 phục vụ audit và tests).
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    try:
        with conn.cursor(dictionary=True) as cursor:
            if alert_round is not None:
                cursor.execute(
                    """
                    SELECT id, alert_id, alert_round, recipient_id, recipient_role,
                           title, message, class_id, student_id, created_at, is_read
                    FROM absence_alert_notifications
                    WHERE alert_id = %s AND alert_round = %s
                    ORDER BY created_at ASC
                    """,
                    (alert_id, alert_round),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, alert_id, alert_round, recipient_id, recipient_role,
                           title, message, class_id, student_id, created_at, is_read
                    FROM absence_alert_notifications
                    WHERE alert_id = %s
                    ORDER BY alert_round ASC, created_at ASC
                    """,
                    (alert_id,),
                )
            rows = cursor.fetchall() or []
            for r in rows:
                if hasattr(r.get("created_at"), "isoformat"):
                    r["created_at"] = r["created_at"].isoformat()
            return rows
    finally:
        if should_close:
            conn.close()
