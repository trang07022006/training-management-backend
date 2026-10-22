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
