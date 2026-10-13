"""
Repository quản lý Thời khóa biểu lớp học (ClassSchedule Repository) - SCRUM-224.
"""

from datetime import date, datetime, timezone
from typing import Any
import uuid
from app.database.connection import get_db_connection
from app.models.class_schedule import ClassSchedule


def insert_schedules_batch(schedules: list[ClassSchedule]) -> list[ClassSchedule]:
    """Lưu danh sách buổi học theo lô vào cơ sở dữ liệu (SCRUM-224)."""
    if not schedules:
        return []

    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        for s in schedules:
            if not s.id:
                s.id = str(uuid.uuid4())
            s.created_at = s.created_at or now
            s.updated_at = s.updated_at or now

        with conn.cursor() as cursor:
            sql = """
                INSERT INTO class_schedules (
                    id, class_id, class_subject_id, subject_id, subject_session_id,
                    session_number, topic, learning_date, shift, start_time, end_time,
                    room_id, instructor_id, status, cancellation_reason, attendance_checked,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """
            values = [
                (
                    s.id,
                    s.class_id,
                    s.class_subject_id,
                    s.subject_id,
                    s.subject_session_id,
                    s.session_number,
                    s.topic.strip(),
                    s.learning_date,
                    s.shift,
                    s.start_time,
                    s.end_time,
                    s.room_id,
                    s.instructor_id,
                    s.status,
                    s.cancellation_reason,
                    s.attendance_checked,
                    s.created_at,
                    s.updated_at,
                )
                for s in schedules
            ]
            cursor.executemany(sql, values)
            conn.commit()
        return schedules
    finally:
        conn.close()


def list_schedules_by_class_id(class_id: str) -> list[ClassSchedule]:
    """Lấy danh sách thời khóa biểu của một lớp, sắp xếp theo ngày học và giờ học."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, class_id, class_subject_id, subject_id, subject_session_id,
                       session_number, topic, learning_date, shift, start_time, end_time,
                       room_id, instructor_id, status, cancellation_reason, attendance_checked,
                       created_at, updated_at
                FROM class_schedules
                WHERE class_id = %s
                ORDER BY learning_date ASC, start_time ASC, session_number ASC
                """,
                (class_id,),
            )
            rows = cursor.fetchall()
            return [
                ClassSchedule(
                    id=r["id"],
                    class_id=r["class_id"],
                    class_subject_id=r["class_subject_id"],
                    subject_id=r["subject_id"],
                    subject_session_id=r["subject_session_id"],
                    session_number=r["session_number"],
                    topic=r["topic"],
                    learning_date=r["learning_date"],
                    shift=r["shift"],
                    start_time=r["start_time"],
                    end_time=r["end_time"],
                    room_id=r["room_id"],
                    instructor_id=r["instructor_id"],
                    status=r["status"],
                    cancellation_reason=r["cancellation_reason"],
                    attendance_checked=bool(r["attendance_checked"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
    finally:
        conn.close()


def get_schedule_by_id(schedule_id: str) -> ClassSchedule | None:
    """Lấy thông tin chi tiết một buổi học theo ID."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, class_id, class_subject_id, subject_id, subject_session_id,
                       session_number, topic, learning_date, shift, start_time, end_time,
                       room_id, instructor_id, status, cancellation_reason, attendance_checked,
                       created_at, updated_at
                FROM class_schedules
                WHERE id = %s
                """,
                (schedule_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return ClassSchedule(
                id=r["id"],
                class_id=r["class_id"],
                class_subject_id=r["class_subject_id"],
                subject_id=r["subject_id"],
                subject_session_id=r["subject_session_id"],
                session_number=r["session_number"],
                topic=r["topic"],
                learning_date=r["learning_date"],
                shift=r["shift"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                room_id=r["room_id"],
                instructor_id=r["instructor_id"],
                status=r["status"],
                cancellation_reason=r["cancellation_reason"],
                attendance_checked=bool(r["attendance_checked"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    finally:
        conn.close()


def count_schedules_by_class_id(class_id: str) -> int:
    """Đếm số buổi học đã xếp lịch của lớp."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM class_schedules WHERE class_id = %s", (class_id,))
            return cursor.fetchone()[0]
    finally:
        conn.close()


def delete_schedules_by_class_id(class_id: str) -> int:
    """Xóa thời khóa biểu của một lớp (dùng cho test hoặc tái xếp lịch)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM class_schedules WHERE class_id = %s", (class_id,))
            conn.commit()
            return cursor.rowcount
    finally:
        conn.close()


def find_conflicts_for_slot(
    learning_date: date | str,
    start_time: str,
    end_time: str,
    instructor_id: str | None = None,
    room_id: str | None = None,
    exclude_class_id: str | None = None,
    exclude_schedule_id: str | None = None,
) -> list[dict]:
    """
    Truy vấn các buổi học trong DB xung đột thời gian (start < existing.end AND end > existing.start)
    với giảng viên hoặc phòng học đã chỉ định (SCRUM-225 - AC 1, AC 2).
    """
    # Nếu không có cả giảng viên và phòng học thì không có căn cứ xét xung đột GV/phòng
    if not instructor_id and not room_id:
        return []

    conn = get_db_connection()
    try:
        date_str = learning_date.strftime("%Y-%m-%d") if hasattr(learning_date, "strftime") else str(learning_date)
        start_str = str(start_time)
        end_str = str(end_time)

        sql = """
            SELECT cs.id, cs.class_id, cs.session_number, cs.topic, cs.learning_date,
                   cs.shift, cs.start_time, cs.end_time, cs.room_id, cs.instructor_id, cs.status,
                   c.class_code, u.name AS instructor_name
            FROM class_schedules cs
            LEFT JOIN classes c ON cs.class_id = c.id
            LEFT JOIN users u ON cs.instructor_id = u.id
            WHERE cs.learning_date = %s
              AND cs.status != 'cancelled'
              AND (cs.start_time < %s AND cs.end_time > %s)
        """
        params: list[Any] = [date_str, end_str, start_str]

        # Điều kiện giảng viên hoặc phòng học
        target_conditions = []
        if instructor_id:
            target_conditions.append("cs.instructor_id = %s")
            params.append(instructor_id)
        if room_id:
            target_conditions.append("cs.room_id = %s")
            params.append(room_id)

        if target_conditions:
            sql += f" AND ({' OR '.join(target_conditions)})"

        if exclude_class_id:
            sql += " AND cs.class_id != %s"
            params.append(exclude_class_id)

        if exclude_schedule_id:
            sql += " AND cs.id != %s"
            params.append(exclude_schedule_id)

        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

            results = []
            for r in rows:
                learning_date_val = r["learning_date"]
                ld_str = learning_date_val.strftime("%Y-%m-%d") if hasattr(learning_date_val, "strftime") else str(learning_date_val)
                st_str = r["start_time"].strftime("%H:%M:%S") if hasattr(r["start_time"], "strftime") else str(r["start_time"])
                et_str = r["end_time"].strftime("%H:%M:%S") if hasattr(r["end_time"], "strftime") else str(r["end_time"])

                results.append({
                    "id": r["id"],
                    "class_id": r["class_id"],
                    "class_code": r["class_code"] or r["class_id"],
                    "session_number": r["session_number"],
                    "topic": r["topic"],
                    "learning_date": ld_str,
                    "shift": r["shift"],
                    "start_time": st_str,
                    "end_time": et_str,
                    "room_id": r["room_id"],
                    "instructor_id": r["instructor_id"],
                    "instructor_name": r["instructor_name"] or r["instructor_id"],
                    "status": r["status"],
                })
            return results
    finally:
        conn.close()


def get_schedule_by_id(schedule_id: str) -> ClassSchedule | None:
    """Lấy chi tiết một buổi học theo ID (SCRUM-226)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, class_id, class_subject_id, subject_id, subject_session_id,
                       session_number, topic, learning_date, shift, start_time, end_time,
                       room_id, instructor_id, status, cancellation_reason, attendance_checked,
                       created_at, updated_at
                FROM class_schedules
                WHERE id = %s
                """,
                (schedule_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return ClassSchedule(
                id=r["id"],
                class_id=r["class_id"],
                class_subject_id=r["class_subject_id"],
                subject_id=r["subject_id"],
                subject_session_id=r["subject_session_id"],
                session_number=r["session_number"],
                topic=r["topic"],
                learning_date=r["learning_date"],
                shift=r["shift"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                room_id=r["room_id"],
                instructor_id=r["instructor_id"],
                status=r["status"],
                cancellation_reason=r["cancellation_reason"],
                attendance_checked=bool(r["attendance_checked"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    finally:
        conn.close()


def update_schedule_item(schedule: ClassSchedule) -> ClassSchedule:
    """Cập nhật thông tin một buổi học đơn lẻ (SCRUM-226 AC 1, AC 2)."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        schedule.updated_at = now
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE class_schedules
                SET learning_date = %s,
                    start_time = %s,
                    end_time = %s,
                    shift = %s,
                    room_id = %s,
                    instructor_id = %s,
                    topic = %s,
                    status = %s,
                    cancellation_reason = %s,
                    attendance_checked = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    schedule.learning_date,
                    schedule.start_time,
                    schedule.end_time,
                    schedule.shift,
                    schedule.room_id,
                    schedule.instructor_id,
                    schedule.topic,
                    schedule.status,
                    schedule.cancellation_reason,
                    schedule.attendance_checked,
                    now,
                    schedule.id,
                ),
            )
            conn.commit()
        return schedule
    finally:
        conn.close()


def insert_schedule_notifications_batch(notifications: list[dict]) -> list[dict]:
    """Lưu danh sách thông báo thay đổi TKB gửi tới học viên và giảng viên (SCRUM-226 AC 3)."""
    if not notifications:
        return []

    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        for n in notifications:
            if not n.get("id"):
                n["id"] = str(uuid.uuid4())
            n["created_at"] = n.get("created_at") or now

        with conn.cursor() as cursor:
            sql = """
                INSERT INTO schedule_notifications (
                    id, schedule_id, class_id, recipient_type, recipient_id,
                    recipient_name, recipient_email, change_type, title, message, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = [
                (
                    n["id"],
                    n["schedule_id"],
                    n["class_id"],
                    n["recipient_type"],
                    n["recipient_id"],
                    n.get("recipient_name"),
                    n.get("recipient_email"),
                    n["change_type"],
                    n["title"],
                    n["message"],
                    n["created_at"],
                )
                for n in notifications
            ]
            cursor.executemany(sql, values)
            conn.commit()
        return notifications
    finally:
        conn.close()


def list_schedule_notifications(
    schedule_id: str | None = None,
    class_id: str | None = None,
) -> list[dict]:
    """Truy vấn lịch sử thông báo thay đổi thời khóa biểu (SCRUM-226 AC 3)."""
    conn = get_db_connection()
    try:
        conditions = []
        params = []
        if schedule_id:
            conditions.append("schedule_id = %s")
            params.append(schedule_id)
        if class_id:
            conditions.append("class_id = %s")
            params.append(class_id)

        sql = """
            SELECT id, schedule_id, class_id, recipient_type, recipient_id,
                   recipient_name, recipient_email, change_type, title, message, created_at
            FROM schedule_notifications
        """
        if conditions:
            sql += f" WHERE {' AND '.join(conditions)}"
        sql += " ORDER BY created_at DESC"

        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            for r in rows:
                if hasattr(r["created_at"], "isoformat"):
                    r["created_at"] = r["created_at"].isoformat()
            return rows
    finally:
        conn.close()


def get_class_enrollment_recipients(class_id: str) -> list[dict]:
    """Lấy danh sách học viên đang ghi danh của lớp để gửi thông báo (SCRUM-226 AC 3)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT s.id, s.user_id, s.full_name, s.email, 'student' AS recipient_type
                FROM class_enrollments ce
                JOIN students s ON ce.student_id = s.id
                WHERE ce.class_id = %s AND ce.status = 'enrolled'
                """,
                (class_id,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


def get_user_info_by_id(user_id: str) -> dict | None:
    """Lấy thông tin người dùng (tên, email) để gửi thông báo (SCRUM-226 AC 3)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, name, email FROM users WHERE id = %s", (user_id,))
            return cursor.fetchone()
    finally:
        conn.close()


DAY_OF_WEEK_NAMES = {
    0: "Thứ 2",
    1: "Thứ 3",
    2: "Thứ 4",
    3: "Thứ 5",
    4: "Thứ 6",
    5: "Thứ 7",
    6: "Chủ nhật",
}


def list_calendar_schedules(
    date_from: str | None = None,
    date_to: str | None = None,
    class_id: str | None = None,
    instructor_id: str | None = None,
    room_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Lấy danh sách thời khóa biểu dạng lịch theo khoảng ngày và bộ lọc (SCRUM-227 AC 1, 2, 3).
    Hỗ trợ lọc theo:
    - Khoảng ngày: date_from <= learning_date <= date_to
    - Lớp học: class_id
    - Giảng viên: instructor_id
    - Phòng học: room_id
    """
    conn = get_db_connection()
    try:
        sql = """
            SELECT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                   cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                   cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                   c.class_code,
                   u.name AS instructor_name, u.email AS instructor_email,
                   s.subject_name, s.subject_code
            FROM class_schedules cs
            LEFT JOIN classes c ON cs.class_id = c.id
            LEFT JOIN users u ON cs.instructor_id = u.id
            LEFT JOIN subjects s ON cs.subject_id = s.id
            WHERE 1=1
        """
        params: list[Any] = []

        if date_from:
            sql += " AND cs.learning_date >= %s"
            params.append(date_from)
        if date_to:
            sql += " AND cs.learning_date <= %s"
            params.append(date_to)
        if class_id:
            sql += " AND cs.class_id = %s"
            params.append(class_id)
        if instructor_id:
            sql += " AND cs.instructor_id = %s"
            params.append(instructor_id)
        if room_id:
            sql += " AND cs.room_id = %s"
            params.append(room_id)

        sql += " ORDER BY cs.learning_date ASC, cs.start_time ASC, cs.session_number ASC"

        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

            results = []
            for r in rows:
                ld = r["learning_date"]
                ld_str = ld.strftime("%Y-%m-%d") if hasattr(ld, "strftime") else str(ld)
                st = r["start_time"]
                st_str = st.strftime("%H:%M:%S") if hasattr(st, "strftime") else str(st)
                et = r["end_time"]
                et_str = et.strftime("%H:%M:%S") if hasattr(et, "strftime") else str(et)

                day_name = ""
                if hasattr(ld, "weekday"):
                    day_name = DAY_OF_WEEK_NAMES.get(ld.weekday(), "")
                else:
                    try:
                        parsed_d = datetime.strptime(ld_str, "%Y-%m-%d").date()
                        day_name = DAY_OF_WEEK_NAMES.get(parsed_d.weekday(), "")
                    except Exception:
                        pass

                results.append({
                    "id": r["id"],
                    "class_id": r["class_id"],
                    "class_code": r["class_code"] or r["class_id"],
                    "class_subject_id": r["class_subject_id"],
                    "subject_id": r["subject_id"],
                    "subject_name": r["subject_name"] or "",
                    "subject_code": r["subject_code"] or "",
                    "subject_session_id": r["subject_session_id"],
                    "session_number": r["session_number"],
                    "topic": r["topic"],
                    "learning_date": ld_str,
                    "day_of_week": day_name,
                    "shift": r["shift"],
                    "start_time": st_str,
                    "end_time": et_str,
                    "room_id": r["room_id"],
                    "instructor_id": r["instructor_id"],
                    "instructor_name": r["instructor_name"] or r["instructor_id"] or "",
                    "instructor_email": r["instructor_email"] or "",
                    "status": r["status"],
                    "cancellation_reason": r["cancellation_reason"],
                    "attendance_checked": bool(r["attendance_checked"]),
                })
            return results
    finally:
        conn.close()


def get_schedule_detail_by_id(schedule_id: str) -> dict[str, Any] | None:
    """Lấy thông tin chi tiết một buổi học kèm thông tin lớp, GV, môn học (SCRUM-227 AC 3)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.subject_name, s.subject_code
                FROM class_schedules cs
                LEFT JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                WHERE cs.id = %s
                """,
                (schedule_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            ld = r["learning_date"]
            ld_str = ld.strftime("%Y-%m-%d") if hasattr(ld, "strftime") else str(ld)
            st = r["start_time"]
            st_str = st.strftime("%H:%M:%S") if hasattr(st, "strftime") else str(st)
            et = r["end_time"]
            et_str = et.strftime("%H:%M:%S") if hasattr(et, "strftime") else str(et)
            day_name = ""
            if hasattr(ld, "weekday"):
                day_name = DAY_OF_WEEK_NAMES.get(ld.weekday(), "")
            else:
                try:
                    parsed_d = datetime.strptime(ld_str, "%Y-%m-%d").date()
                    day_name = DAY_OF_WEEK_NAMES.get(parsed_d.weekday(), "")
                except Exception:
                    pass

            return {
                "id": r["id"],
                "class_id": r["class_id"],
                "class_code": r["class_code"] or r["class_id"],
                "class_subject_id": r["class_subject_id"],
                "subject_id": r["subject_id"],
                "subject_name": r["subject_name"] or "",
                "subject_code": r["subject_code"] or "",
                "subject_session_id": r["subject_session_id"],
                "session_number": r["session_number"],
                "topic": r["topic"],
                "learning_date": ld_str,
                "day_of_week": day_name,
                "shift": r["shift"],
                "start_time": st_str,
                "end_time": et_str,
                "room_id": r["room_id"],
                "instructor_id": r["instructor_id"],
                "instructor_name": r["instructor_name"] or r["instructor_id"] or "",
                "instructor_email": r["instructor_email"] or "",
                "status": r["status"],
                "cancellation_reason": r["cancellation_reason"],
                "attendance_checked": bool(r["attendance_checked"]),
            }
    finally:
        conn.close()



