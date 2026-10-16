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


def count_attendance_checked_by_class_id(class_id: str) -> int:
    """Đếm số buổi học đã được điểm danh của lớp (SCRUM-224/226)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM class_schedules WHERE class_id = %s AND attendance_checked = 1",
                (class_id,),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)
    finally:
        conn.close()


def replace_schedules_in_transaction(class_id: str, schedules: list[ClassSchedule]) -> list[ClassSchedule]:
    """
    Xóa lịch cũ và lưu danh sách lịch mới trong CÙNG một transaction với khóa hàng (FOR UPDATE).
    Rollback toàn bộ nếu có bất kỳ lỗi nào xảy ra để bảo vệ dữ liệu lịch cũ không bị mất (SCRUM-224/226).
    Chặn ghi đè nếu lớp học đã có buổi học được điểm danh.
    """
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        for s in schedules:
            if not s.id:
                s.id = str(uuid.uuid4())
            s.created_at = s.created_at or now
            s.updated_at = s.updated_at or now

        with conn.cursor() as cursor:
            # 1. Khóa hàng lớp học để bảo vệ chống cập nhật đồng thời
            cursor.execute("SELECT id FROM classes WHERE id = %s FOR UPDATE", (class_id,))
            cursor.fetchone()

            # 2. Kiểm tra xem có buổi học nào đã điểm danh chưa
            cursor.execute(
                "SELECT COUNT(*) FROM class_schedules WHERE class_id = %s AND attendance_checked = 1",
                (class_id,),
            )
            attended_count = cursor.fetchone()[0]
            if attended_count > 0:
                raise RuntimeError("ATTENDANCE_CHECKED_LOCK: Không thể ghi đè lịch của lớp đã có buổi học được điểm danh.")

            # 3. Xóa lịch cũ
            cursor.execute("DELETE FROM class_schedules WHERE class_id = %s", (class_id,))

            # 4. Chèn danh sách buổi học mới
            if schedules:
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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_schedules_by_class_id(class_id: str) -> list[ClassSchedule]:
    """Lấy danh sách thời khóa biểu của một lớp kèm tên GV, phòng học, môn học (SCRUM-224/226)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       cs.created_at, cs.updated_at,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link
                FROM class_schedules cs
                LEFT JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE cs.class_id = %s
                ORDER BY cs.learning_date ASC, cs.start_time ASC, cs.session_number ASC
                """,
                (class_id,),
            )
            rows = cursor.fetchall()
            results = []
            for r in rows:
                cr_id = r.get("cr_classroom_id")
                cr_room_type = r.get("room_type")
                cr_online_link = r.get("online_link")
                cr_room_name = r.get("room_name") or r.get("room_code")
                cr_room_code = r.get("room_code")
                room_val = r.get("room_id") or ""

                if cr_id:
                    is_legacy_room = False
                    legacy_room_raw = None
                    classroom_id = cr_id
                    room_code = cr_room_code
                    is_online = (cr_room_type == "online")
                    online_url = cr_online_link if is_online else None
                    room_name = cr_room_name or (room_val if not is_online else "Phòng học trực tuyến")
                    active_room_id = cr_id
                else:
                    classroom_id = None
                    room_code = None
                    active_room_id = room_val or None
                    if room_val:
                        is_legacy_room = True
                        legacy_room_raw = room_val
                        is_online = bool(
                            room_val.startswith("http://")
                            or room_val.startswith("https://")
                            or "meet.google.com" in room_val
                            or "zoom.us" in room_val
                            or "teams.microsoft.com" in room_val
                        )
                        online_url = room_val if is_online else None
                        room_name = None if is_online else room_val
                    else:
                        is_legacy_room = False
                        legacy_room_raw = None
                        is_online = False
                        online_url = None
                        room_name = None

                results.append(
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
                        room_id=active_room_id,
                        room_code=room_code,
                        classroom_id=classroom_id,
                        instructor_id=r["instructor_id"],
                        status=r["status"],
                        cancellation_reason=r["cancellation_reason"],
                        attendance_checked=bool(r["attendance_checked"]),
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                        instructor_name=r.get("instructor_name"),
                        instructor_email=r.get("instructor_email"),
                        room_name=room_name,
                        room_type=cr_room_type,
                        online_link=cr_online_link,
                        is_online=is_online,
                        online_url=online_url,
                        is_legacy_room=is_legacy_room,
                        legacy_room_raw=legacy_room_raw,
                        subject_name=r.get("subject_name"),
                        subject_code=r.get("subject_code"),
                        class_code=r.get("class_code"),
                    )
                )
            return results
    finally:
        conn.close()


def get_schedule_by_id(schedule_id: str) -> ClassSchedule | None:
    """Lấy thông tin chi tiết một buổi học theo ID kèm liên kết GV và phòng học (SCRUM-226)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       cs.created_at, cs.updated_at,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link
                FROM class_schedules cs
                LEFT JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE cs.id = %s
                """,
                (schedule_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None

            cr_id = r.get("cr_classroom_id")
            cr_room_type = r.get("room_type")
            cr_online_link = r.get("online_link")
            cr_room_name = r.get("room_name") or r.get("room_code")
            cr_room_code = r.get("room_code")
            room_val = r.get("room_id") or ""

            if cr_id:
                is_legacy_room = False
                legacy_room_raw = None
                classroom_id = cr_id
                room_code = cr_room_code
                is_online = (cr_room_type == "online")
                online_url = cr_online_link if is_online else None
                room_name = cr_room_name or (room_val if not is_online else "Phòng học trực tuyến")
                active_room_id = cr_id
            else:
                classroom_id = None
                room_code = None
                active_room_id = room_val or None
                if room_val:
                    is_legacy_room = True
                    legacy_room_raw = room_val
                    is_online = bool(
                        room_val.startswith("http://")
                        or room_val.startswith("https://")
                        or "meet.google.com" in room_val
                        or "zoom.us" in room_val
                        or "teams.microsoft.com" in room_val
                    )
                    online_url = room_val if is_online else None
                    room_name = None if is_online else room_val
                else:
                    is_legacy_room = False
                    legacy_room_raw = None
                    is_online = False
                    online_url = None
                    room_name = None

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
                room_id=active_room_id,
                room_code=room_code,
                classroom_id=classroom_id,
                instructor_id=r["instructor_id"],
                status=r["status"],
                cancellation_reason=r["cancellation_reason"],
                attendance_checked=bool(r["attendance_checked"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                instructor_name=r.get("instructor_name"),
                instructor_email=r.get("instructor_email"),
                room_name=room_name,
                room_type=cr_room_type,
                online_link=cr_online_link,
                is_online=is_online,
                online_url=online_url,
                is_legacy_room=is_legacy_room,
                legacy_room_raw=legacy_room_raw,
                subject_name=r.get("subject_name"),
                subject_code=r.get("subject_code"),
                class_code=r.get("class_code"),
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
    """Xóa thời khóa biểu của một lớp (dùng cho test hoặc xóa toàn bộ lịch khi chưa điểm danh)."""
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
                   c.class_code, u.name AS instructor_name,
                   cr.room_name, cr.room_code
            FROM class_schedules cs
            LEFT JOIN classes c ON cs.class_id = c.id
            LEFT JOIN users u ON cs.instructor_id = u.id
            LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
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
            from app.repositories import classroom_repository
            room_keys = [room_id]
            cr = classroom_repository.get_classroom_by_id(room_id)
            if cr:
                if cr.room_code and cr.room_code not in room_keys:
                    room_keys.append(cr.room_code)
            else:
                cr_by_code = classroom_repository.get_classroom_by_code(room_id)
                if cr_by_code and cr_by_code.id not in room_keys:
                    room_keys.append(cr_by_code.id)

            if len(room_keys) == 1:
                target_conditions.append("cs.room_id = %s")
                params.append(room_keys[0])
            else:
                target_conditions.append("(cs.room_id = %s OR cs.room_id = %s)")
                params.extend(room_keys[:2])

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

                r_room = r.get("room_id")
                r_cr_code = r.get("room_code")
                is_room = bool(room_id and (r_room == room_id or r_cr_code == room_id or (r_room in room_keys if "room_keys" in locals() else False)))
                is_inst = bool(instructor_id and r.get("instructor_id") == instructor_id)
                conflict_type = "room" if is_room else ("instructor" if is_inst else "room")

                results.append({
                    "id": r["id"],
                    "conflict_type": conflict_type,
                    "class_id": r["class_id"],
                    "class_code": r["class_code"] or r["class_id"],
                    "session_number": r["session_number"],
                    "topic": r["topic"],
                    "learning_date": ld_str,
                    "shift": r["shift"],
                    "start_time": st_str,
                    "end_time": et_str,
                    "room_id": r["room_id"],
                    "room_name": r.get("room_name") or r.get("room_code") or r["room_id"],
                    "room_code": r.get("room_code"),
                    "instructor_id": r["instructor_id"],
                    "instructor_name": r["instructor_name"] or r["instructor_id"],
                    "status": r["status"],
                    "message": f"Trùng {'phòng học' if conflict_type == 'room' else 'giảng viên'} với Buổi #{r['session_number']} của Lớp {r['class_code'] or r['class_id']} ({st_str} - {et_str}).",
                })
            return results
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
        return get_schedule_by_id(schedule.id) or schedule
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
    trainer_scope_user_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Lấy danh sách thời khóa biểu dạng lịch theo khoảng ngày và bộ lọc (SCRUM-227 AC 1, 2, 3).
    Hỗ trợ lọc theo:
    - Khoảng ngày: date_from <= learning_date <= date_to
    - Lớp học: class_id
    - Giảng viên: instructor_id
    - Phòng học: room_id
    - Giới hạn phạm vi giảng viên (trainer_scope_user_id): chỉ xem buổi học được phân công.
    """
    conn = get_db_connection()
    try:
        sql = """
            SELECT DISTINCT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                   cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                   cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                   c.class_code,
                   u.name AS instructor_name, u.email AS instructor_email,
                   s.name AS subject_name, s.code AS subject_code,
                   cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link
            FROM class_schedules cs
            LEFT JOIN classes c ON cs.class_id = c.id
            LEFT JOIN users u ON cs.instructor_id = u.id
            LEFT JOIN subjects s ON cs.subject_id = s.id
            LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
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
            from app.repositories import classroom_repository
            room_keys = [room_id]
            cr = classroom_repository.get_classroom_by_id(room_id)
            if cr:
                if cr.room_code and cr.room_code not in room_keys:
                    room_keys.append(cr.room_code)
            else:
                cr_by_code = classroom_repository.get_classroom_by_code(room_id)
                if cr_by_code and cr_by_code.id not in room_keys:
                    room_keys.append(cr_by_code.id)

            if len(room_keys) == 1:
                sql += " AND cs.room_id = %s"
                params.append(room_keys[0])
            else:
                sql += " AND (cs.room_id = %s OR cs.room_id = %s)"
                params.extend(room_keys[:2])
        if trainer_scope_user_id:
            sql += """
                AND (
                    cs.instructor_id = %s
                    OR cs.class_subject_id IN (
                        SELECT class_subject_id FROM class_subject_instructors WHERE instructor_id = %s
                    )
                )
            """
            params.extend([trainer_scope_user_id, trainer_scope_user_id])

        sql += " ORDER BY cs.learning_date ASC, cs.start_time ASC, cs.session_number ASC"

        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [_format_schedule_dict(r) for r in rows]
    finally:
        conn.close()


def _format_schedule_dict(r: dict[str, Any]) -> dict[str, Any]:
    """Helper chuyển đổi bản ghi SQL thành dictionary lịch học chuẩn (SCRUM-221/227/228)."""
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

    cr_id = r.get("cr_classroom_id") or r.get("classroom_id")
    cr_room_type = r.get("room_type")
    cr_online_link = r.get("online_link")
    cr_room_name = r.get("room_name") or r.get("room_code")
    cr_room_code = r.get("room_code")
    room_val = r.get("room_id") or ""

    if cr_id:
        is_legacy_room = False
        legacy_room_raw = None
        classroom_id = cr_id
        room_code = cr_room_code
        is_online = (cr_room_type == "online")
        online_url = cr_online_link if is_online else None
        room_name = cr_room_name or (room_val if not is_online else "Phòng học trực tuyến")
        active_room_id = cr_id
    else:
        classroom_id = None
        room_code = None
        active_room_id = room_val or None
        if room_val:
            is_legacy_room = True
            legacy_room_raw = room_val
            is_online = bool(
                room_val.startswith("http://")
                or room_val.startswith("https://")
                or "meet.google.com" in room_val
                or "zoom.us" in room_val
                or "teams.microsoft.com" in room_val
            )
            online_url = room_val if is_online else None
            room_name = None if is_online else room_val
        else:
            is_legacy_room = False
            legacy_room_raw = None
            is_online = False
            online_url = None
            room_name = None

    return {
        "id": r["id"],
        "class_id": r["class_id"],
        "class_code": r.get("class_code") or r["class_id"],
        "class_subject_id": r.get("class_subject_id"),
        "subject_id": r.get("subject_id"),
        "subject_name": r.get("subject_name") or "",
        "subject_code": r.get("subject_code") or "",
        "subject_session_id": r.get("subject_session_id"),
        "session_number": r["session_number"],
        "topic": r["topic"],
        "learning_date": ld_str,
        "day_of_week": day_name,
        "shift": r["shift"],
        "start_time": st_str,
        "end_time": et_str,
        "room_id": active_room_id,
        "room_code": room_code,
        "classroom_id": classroom_id,
        "room_name": room_name,
        "room_type": cr_room_type,
        "online_link": cr_online_link,
        "is_online": is_online,
        "online_url": online_url,
        "is_legacy_room": is_legacy_room,
        "legacy_room_raw": legacy_room_raw,
        "instructor_id": r.get("instructor_id"),
        "instructor_name": r.get("instructor_name") or "",
        "instructor_email": r.get("instructor_email") or "",
        "status": r["status"],
        "cancellation_reason": r.get("cancellation_reason"),
        "attendance_checked": bool(r.get("attendance_checked")),
    }


def get_schedule_detail_by_id(schedule_id: str) -> dict[str, Any] | None:
    """Lấy thông tin chi tiết một buổi học kèm thông tin lớp, GV, môn học, phòng học (SCRUM-227 AC 3)."""
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
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link
                FROM class_schedules cs
                LEFT JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE cs.id = %s
                """,
                (schedule_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return _format_schedule_dict(r)
    finally:
        conn.close()


def get_student_by_user_id(user_id: str) -> dict[str, Any] | None:
    """Tìm thông tin học viên theo user_id (SCRUM-228)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT s.id, s.student_code, s.user_id, s.full_name, s.email, s.phone, s.program_id,
                       tp.name AS program_name, tp.code AS program_code
                FROM students s
                LEFT JOIN training_programs tp ON s.program_id = tp.id
                WHERE s.user_id = %s OR s.id = %s
                LIMIT 1
                """,
                (user_id, user_id),
            )
            row = cursor.fetchone()
            if row:
                return row
            cursor.execute(
                """
                SELECT s.id, s.student_code, s.user_id, s.full_name, s.email, s.phone, s.program_id,
                       tp.name AS program_name, tp.code AS program_code
                FROM students s
                LEFT JOIN training_programs tp ON s.program_id = tp.id
                JOIN users u ON s.email = u.email
                WHERE u.id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_enrolled_classes_for_student(student_id: str) -> list[dict[str, Any]]:
    """Lấy danh sách các lớp học mà học viên đã ghi danh hợp lệ (SCRUM-228)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT ce.class_id, ce.status AS enrollment_status,
                       c.class_code, c.learning_mode, c.status AS class_status,
                       tp.name AS program_name, tp.code AS program_code
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE ce.student_id = %s
                  AND ce.status IN ('enrolled', 'active', 'studying', 'completed')
                ORDER BY ce.created_at DESC
                """,
                (student_id,),
            )
            return cursor.fetchall() or []
    finally:
        conn.close()


def get_student_next_session(class_ids: list[str], current_date: str, current_time: str) -> dict[str, Any] | None:
    """Lấy buổi học kế tiếp sắp diễn ra của học viên theo thời gian thực (SCRUM-228 AC 1)."""
    if not class_ids:
        return None
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            placeholders = ", ".join(["%s"] * len(class_ids))
            query = f"""
                SELECT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link
                FROM class_schedules cs
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE cs.class_id IN ({placeholders})
                  AND cs.status != 'cancelled'
                  AND (cs.learning_date > %s OR (cs.learning_date = %s AND cs.end_time >= %s))
                ORDER BY cs.learning_date ASC, cs.start_time ASC
                LIMIT 1
            """
            params = list(class_ids) + [current_date, current_date, current_time]
            cursor.execute(query, tuple(params))
            r = cursor.fetchone()
            if not r:
                return None
            return _format_schedule_dict(r)
    finally:
        conn.close()


def get_student_week_sessions(class_ids: list[str], date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Lấy danh sách các buổi học trong tuần của học viên (SCRUM-228 AC 1)."""
    if not class_ids:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            placeholders = ", ".join(["%s"] * len(class_ids))
            query = f"""
                SELECT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link
                FROM class_schedules cs
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE cs.class_id IN ({placeholders})
                  AND cs.learning_date >= %s
                  AND cs.learning_date <= %s
                ORDER BY cs.learning_date ASC, cs.start_time ASC
            """
            params = list(class_ids) + [date_from, date_to]
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall() or []
            return [_format_schedule_dict(r) for r in rows]
    finally:
        conn.close()


def get_student_by_student_id(student_id: str) -> dict[str, Any] | None:
    """Tìm thông tin học viên theo ID hồ sơ học viên (phục vụ quản lý xem lịch)."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT s.id, s.student_code, s.user_id, s.full_name, s.email, s.phone, s.program_id,
                       tp.name AS program_name, tp.code AS program_code
                FROM students s
                LEFT JOIN training_programs tp ON s.program_id = tp.id
                WHERE s.id = %s
                LIMIT 1
                """,
                (student_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_trainer_next_session(instructor_id: str, current_date: str, current_time: str) -> dict[str, Any] | None:
    """Lấy buổi học kế tiếp sắp tới do giảng viên phụ trách (Lịch giảng dạy)."""
    if not instructor_id:
        return None
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            query = """
                SELECT DISTINCT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link,
                       (
                            SELECT csi.role_type FROM class_subject_instructors csi 
                            WHERE csi.class_subject_id = cs.class_subject_id AND csi.instructor_id = %s
                            LIMIT 1
                       ) AS assigned_role_type
                FROM class_schedules cs
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE (
                    cs.instructor_id = %s
                    OR cs.class_subject_id IN (
                        SELECT class_subject_id FROM class_subject_instructors WHERE instructor_id = %s AND role_type = 'assistant'
                    )
                )
                  AND cs.status != 'cancelled'
                  AND (cs.learning_date > %s OR (cs.learning_date = %s AND cs.end_time >= %s))
                ORDER BY cs.learning_date ASC, cs.start_time ASC
                LIMIT 1
            """
            cursor.execute(query, (instructor_id, instructor_id, instructor_id, current_date, current_date, current_time))
            r = cursor.fetchone()
            if not r:
                return None
            formatted = _format_schedule_dict(r)
            # Gán nhãn vai trò giảng dạy
            _annotate_teaching_role(formatted, r, instructor_id)
            return formatted
    finally:
        conn.close()


def _annotate_teaching_role(formatted: dict[str, Any], raw_row: dict[str, Any], instructor_id: str) -> None:
    """Helper gán vai trò: Giảng viên chính, Trợ giảng, hoặc Giảng viên dạy thay."""
    session_instructor_id = raw_row.get("instructor_id")
    assigned_role_type = raw_row.get("assigned_role_type")
    
    if session_instructor_id == instructor_id:
        if assigned_role_type == "assistant":
            formatted["teaching_role"] = "assistant"
            formatted["teaching_role_label"] = "Trợ giảng"
        elif assigned_role_type == "main":
            formatted["teaching_role"] = "main"
            formatted["teaching_role_label"] = "Giảng viên chính"
        else:
            formatted["teaching_role"] = "substitute"
            formatted["teaching_role_label"] = "Giảng viên dạy thay"
    else:
        # Giảng viên là trợ giảng hoặc là giảng viên môn nhưng buổi này có người khác dạy thay
        if assigned_role_type == "assistant":
            formatted["teaching_role"] = "assistant"
            formatted["teaching_role_label"] = "Trợ giảng"
        else:
            substitute_name = raw_row.get("instructor_name") or "giảng viên khác"
            formatted["teaching_role"] = "main_delegated"
            formatted["teaching_role_label"] = f"Giảng viên môn (Dạy thay bởi {substitute_name})"


def get_trainer_week_sessions(instructor_id: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Lấy danh sách các buổi học trong tuần do giảng viên phụ trách (Lịch giảng dạy)."""
    if not instructor_id:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            query = """
                SELECT DISTINCT cs.id, cs.class_id, cs.class_subject_id, cs.subject_id, cs.subject_session_id,
                       cs.session_number, cs.topic, cs.learning_date, cs.shift, cs.start_time, cs.end_time,
                       cs.room_id, cs.instructor_id, cs.status, cs.cancellation_reason, cs.attendance_checked,
                       c.class_code,
                       u.name AS instructor_name, u.email AS instructor_email,
                       s.name AS subject_name, s.code AS subject_code,
                       cr.id AS cr_classroom_id, cr.room_name, cr.room_code, cr.room_type, cr.online_link,
                       (
                            SELECT csi.role_type FROM class_subject_instructors csi 
                            WHERE csi.class_subject_id = cs.class_subject_id AND csi.instructor_id = %s
                            LIMIT 1
                       ) AS assigned_role_type
                FROM class_schedules cs
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE (
                    cs.instructor_id = %s
                    OR cs.class_subject_id IN (
                        SELECT class_subject_id FROM class_subject_instructors WHERE instructor_id = %s
                    )
                )
                  AND cs.learning_date >= %s
                  AND cs.learning_date <= %s
                ORDER BY cs.learning_date ASC, cs.start_time ASC
            """
            cursor.execute(query, (instructor_id, instructor_id, instructor_id, date_from, date_to))
            rows = cursor.fetchall() or []
            results = []
            for r in rows:
                formatted = _format_schedule_dict(r)
                _annotate_teaching_role(formatted, r, instructor_id)
                results.append(formatted)
            return results
    finally:
        conn.close()


def get_trainer_assigned_classes(instructor_id: str) -> list[dict[str, Any]]:
    """Lấy danh sách các lớp học mà giảng viên được phân công giảng dạy."""
    if not instructor_id:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            query = """
                SELECT DISTINCT c.id AS class_id, c.class_code, c.learning_mode, c.status AS class_status,
                                tp.name AS program_name, tp.code AS program_code
                FROM classes c
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE c.id IN (
                    SELECT DISTINCT class_id FROM class_schedules WHERE instructor_id = %s
                    UNION
                    SELECT DISTINCT cs.class_id FROM class_subjects cs
                    JOIN class_subject_instructors csi ON cs.id = csi.class_subject_id
                    WHERE csi.instructor_id = %s
                )
                ORDER BY c.class_code ASC
            """
            cursor.execute(query, (instructor_id, instructor_id))
            return cursor.fetchall() or []
    finally:
        conn.close()



