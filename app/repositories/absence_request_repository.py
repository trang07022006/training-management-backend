"""
Repository quản lý dữ liệu Đơn xin phép vắng (SCRUM-255).
"""

from datetime import date, datetime, timedelta, timezone
import logging
import math
from typing import Any, Optional
import uuid

from mysql.connector import Error as MySQLError

from app.database.connection import get_db_connection
from app.models.absence_request import (
    ABSENCE_STATUS_APPROVED,
    ABSENCE_STATUS_PENDING,
    ABSENCE_STATUS_REJECTED,
    ABSENCE_STATUS_LABELS,
)

logger = logging.getLogger(__name__)

# Múi giờ chuẩn nghiệp vụ Việt Nam (UTC+7)
VIETNAM_TZ = timezone(timedelta(hours=7))


def get_vietnam_now() -> datetime:
    """Lấy thời điểm hiện tại theo múi giờ Việt Nam (UTC+7)."""
    return datetime.now(VIETNAM_TZ)


def format_utc_timestamp_iso(dt: Optional[datetime | str]) -> Optional[str]:
    """
    Chuẩn hóa timestamp sang chuỗi ISO 8601 UTC có múi giờ rõ ràng (hậu tố 'Z').
    """
    if not dt:
        return None
    if isinstance(dt, str):
        s = dt.strip()
        if s.endswith("Z") or ("+" in s) or (len(s) > 19 and "-" in s[19:]):
            return s
        return s.replace(" ", "T") + "Z"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        iso_str = dt.isoformat()
        if iso_str.endswith("+00:00"):
            return iso_str[:-6] + "Z"
        if not iso_str.endswith("Z"):
            return iso_str + "Z"
        return iso_str
    return str(dt)


def get_student_eligible_sessions(student_id: str) -> list[dict[str, Any]]:
    """
    Truy vấn danh sách các buổi học mà học viên đủ điều kiện để gửi đơn xin phép vắng (SCRUM-255 Lát 1).
    Quy tắc nghiệp vụ đã xác nhận:
    1. Học viên phải ghi danh vào lớp trước hoặc vào ngày diễn ra buổi học.
    2. Học viên chưa bị bảo lưu/chuyển lớp/thôi học trước ngày học (SCRUM-252).
    3. Buổi học chưa bị hủy (status != 'cancelled').
    4. Thời điểm gửi đơn: Buổi học trong tương lai/hôm nay HOẶC đã diễn ra nhưng chưa quá 48 giờ
       kể từ thời điểm kết thúc buổi học.
    5. Kèm thông tin đơn xin phép vắng gần nhất (nếu có) để frontend biết trạng thái (pending/approved/rejected).
    """
    now_vn = get_vietnam_now()
    cutoff_time_vn = now_vn - timedelta(hours=48)
    cutoff_date = cutoff_time_vn.date()

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    cs.id AS schedule_id,
                    cs.class_id,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    cs.room_id,
                    cs.status AS schedule_status,
                    c.class_code,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    u.name AS instructor_name,
                    COALESCE(cr.room_name, cr.room_code, cs.room_id) AS room_name,
                    (
                        SELECT ar.id 
                        FROM absence_requests ar 
                        WHERE ar.schedule_id = cs.id AND ar.student_id = ce.student_id AND ar.status = 'pending'
                        LIMIT 1
                    ) AS pending_request_id,
                    (
                        SELECT ar.id 
                        FROM absence_requests ar 
                        WHERE ar.schedule_id = cs.id AND ar.student_id = ce.student_id AND ar.status = 'approved'
                        LIMIT 1
                    ) AS approved_request_id,
                    (
                        SELECT ar.status 
                        FROM absence_requests ar 
                        WHERE ar.schedule_id = cs.id AND ar.student_id = ce.student_id 
                        ORDER BY 
                            CASE 
                                WHEN ar.status = 'approved' THEN 1 
                                WHEN ar.status = 'pending' THEN 2 
                                WHEN ar.status = 'rejected' THEN 3 
                                ELSE 4 
                            END ASC,
                            ar.created_at DESC
                        LIMIT 1
                    ) AS latest_request_status
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                JOIN class_schedules cs ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                WHERE ce.student_id = %s
                  AND cs.status != 'cancelled'
                  AND DATE(ce.enrolled_at) <= cs.learning_date
                  AND (
                      ce.lifecycle_status IS NULL
                      OR ce.lifecycle_status NOT IN ('reserved', 'transferred', 'dropped')
                      OR ce.effective_date > cs.learning_date
                  )
                  AND cs.learning_date >= %s
                ORDER BY cs.learning_date ASC, cs.start_time ASC
                """,
                (student_id, cutoff_date),
            )
            rows = cursor.fetchall() or []

            eligible_sessions = []
            for r in rows:
                learning_date = r["learning_date"]
                end_time_val = r["end_time"]
                
                # Tính toán thời điểm kết thúc buổi học chính xác
                if end_time_val:
                    if isinstance(end_time_val, timedelta):
                        total_seconds = int(end_time_val.total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, hours, minutes, tzinfo=VIETNAM_TZ)
                    elif hasattr(end_time_val, "hour"):
                        session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, end_time_val.hour, end_time_val.minute, tzinfo=VIETNAM_TZ)
                    else:
                        session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, 23, 59, 59, tzinfo=VIETNAM_TZ)
                else:
                    session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, 23, 59, 59, tzinfo=VIETNAM_TZ)

                # Kiểm tra quá 48 giờ sau kết thúc buổi học
                deadline = session_end_dt + timedelta(hours=48)
                if now_vn > deadline:
                    continue

                r["learning_date"] = learning_date.isoformat() if learning_date else None
                r["learning_date_str"] = r["learning_date"]
                r["start_time"] = str(r["start_time"]) if r.get("start_time") else None
                r["start_time_str"] = r["start_time"]
                r["end_time"] = str(r["end_time"]) if r.get("end_time") else None
                r["end_time_str"] = r["end_time"]
                r["has_pending_request"] = bool(r.get("pending_request_id"))
                r["has_approved_request"] = bool(r.get("approved_request_id"))
                r["is_selectable"] = not (r["has_pending_request"] or r["has_approved_request"])
                eligible_sessions.append(r)

            return eligible_sessions
    finally:
        conn.close()


def list_student_eligible_sessions_paginated(
    student_id: str,
    search_query: Optional[str] = None,
    class_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Lấy danh sách các buổi học hợp lệ có phân trang, tìm kiếm và bộ lọc (SCRUM-255).
    Áp dụng toàn bộ quy tắc nghiệp vụ:
    - Học viên phải ghi danh vào lớp trước hoặc vào ngày diễn ra buổi học.
    - Học viên chưa bị bảo lưu/chuyển lớp/thôi học trước ngày học (SCRUM-252).
    - Buổi học chưa bị hủy (status != 'cancelled').
    - Thời điểm gửi đơn: Buổi học trong tương lai/hôm nay HOẶC chưa quá 48 giờ sau khi kết thúc.
    - Lọc tìm kiếm theo: tên/mã lớp, tên/mã môn, tên/chủ đề buổi học.
    - Lọc theo: class_id, subject_id, from_date, to_date.
    - Sắp xếp ổn định: cs.learning_date ASC, cs.start_time ASC, cs.id ASC.
    - Trả về filter_options (danh sách classes và subjects của học viên đủ điều kiện) để hỗ trợ frontend bộ lọc tìm kiếm.
    """
    now_vn = get_vietnam_now()
    now_str = now_vn.strftime("%Y-%m-%d %H:%M:%S")

    # Validate pagination
    if page < 1:
        page = 1
    if limit not in (10, 20):
        if limit <= 0:
            limit = 10
        elif limit > 100:
            limit = 100
    offset = (page - 1) * limit

    base_where = """
        WHERE ce.student_id = %s
          AND cs.status != 'cancelled'
          AND DATE(ce.enrolled_at) <= cs.learning_date
          AND (
              ce.lifecycle_status IS NULL
              OR ce.lifecycle_status NOT IN ('reserved', 'transferred', 'dropped')
              OR ce.effective_date > cs.learning_date
          )
          AND TIMESTAMPADD(HOUR, 48, TIMESTAMP(cs.learning_date, COALESCE(cs.end_time, '23:59:59'))) >= %s
    """
    base_params: list[Any] = [student_id, now_str]

    # Additional filters
    filter_where = []
    filter_params: list[Any] = []

    if search_query and str(search_query).strip():
        q_term = f"%{str(search_query).strip()}%"
        filter_where.append("(c.class_code LIKE %s OR s.name LIKE %s OR s.code LIKE %s OR cs.topic LIKE %s)")
        filter_params.extend([q_term, q_term, q_term, q_term])

    if class_id and str(class_id).strip():
        filter_where.append("cs.class_id = %s")
        filter_params.append(str(class_id).strip())

    if subject_id and str(subject_id).strip():
        filter_where.append("cs.subject_id = %s")
        filter_params.append(str(subject_id).strip())

    if from_date and str(from_date).strip():
        filter_where.append("cs.learning_date >= %s")
        filter_params.append(str(from_date).strip())

    if to_date and str(to_date).strip():
        filter_where.append("cs.learning_date <= %s")
        filter_params.append(str(to_date).strip())

    extra_sql = (" AND " + " AND ".join(filter_where)) if filter_where else ""

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # 1. Đếm tổng số kết quả sau khi áp dụng toàn bộ filter
            count_query = f"""
                SELECT COUNT(*) AS total_count
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                JOIN class_schedules cs ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                {base_where}
                {extra_sql}
            """
            cursor.execute(count_query, tuple(base_params + filter_params))
            count_row = cursor.fetchone()
            total_items = count_row["total_count"] if count_row else 0
            total_pages = max(1, math.ceil(total_items / limit)) if total_items > 0 else 1

            # 2. Truy vấn danh sách buổi học của trang hiện tại với sắp xếp ổn định
            data_query = f"""
                SELECT 
                    cs.id AS schedule_id,
                    cs.class_id,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    cs.room_id,
                    cs.status AS schedule_status,
                    c.class_code,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    u.name AS instructor_name,
                    COALESCE(cr.room_name, cr.room_code, cs.room_id) AS room_name,
                    (
                        SELECT ar.id 
                        FROM absence_requests ar 
                        WHERE ar.schedule_id = cs.id AND ar.student_id = ce.student_id AND ar.status = 'pending'
                        LIMIT 1
                    ) AS pending_request_id,
                    (
                        SELECT ar.id 
                        FROM absence_requests ar 
                        WHERE ar.schedule_id = cs.id AND ar.student_id = ce.student_id AND ar.status = 'approved'
                        LIMIT 1
                    ) AS approved_request_id,
                    (
                        SELECT ar.status 
                        FROM absence_requests ar 
                        WHERE ar.schedule_id = cs.id AND ar.student_id = ce.student_id 
                        ORDER BY 
                            CASE 
                                WHEN ar.status = 'approved' THEN 1 
                                WHEN ar.status = 'pending' THEN 2 
                                WHEN ar.status = 'rejected' THEN 3 
                                ELSE 4 
                            END ASC,
                            ar.created_at DESC
                        LIMIT 1
                    ) AS latest_request_status
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                JOIN class_schedules cs ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                {base_where}
                {extra_sql}
                ORDER BY cs.learning_date ASC, cs.start_time ASC, cs.id ASC
                LIMIT %s OFFSET %s
            """
            cursor.execute(data_query, tuple(base_params + filter_params + [limit, offset]))
            rows = cursor.fetchall() or []

            items = []
            for r in rows:
                learning_date = r["learning_date"]
                r["learning_date"] = learning_date.isoformat() if learning_date else None
                r["learning_date_str"] = r["learning_date"]
                r["start_time"] = str(r["start_time"]) if r.get("start_time") else None
                r["start_time_str"] = r["start_time"]
                r["end_time"] = str(r["end_time"]) if r.get("end_time") else None
                r["end_time_str"] = r["end_time"]
                r["has_pending_request"] = bool(r.get("pending_request_id"))
                r["has_approved_request"] = bool(r.get("approved_request_id"))
                r["is_selectable"] = not (r["has_pending_request"] or r["has_approved_request"])
                items.append(r)

            # 3. Lấy filter options (danh sách classes và subjects của học viên trong các buổi học hợp lệ)
            classes_query = f"""
                SELECT DISTINCT
                    c.id AS class_id,
                    c.class_code
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                JOIN class_schedules cs ON cs.class_id = c.id
                {base_where}
                ORDER BY c.class_code ASC
            """
            cursor.execute(classes_query, tuple(base_params))
            classes_rows = cursor.fetchall() or []
            filter_classes = [{"id": row["class_id"], "class_code": row["class_code"]} for row in classes_rows]

            subjects_query = f"""
                SELECT DISTINCT
                    s.id AS subject_id,
                    s.code AS subject_code,
                    s.name AS subject_name
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                JOIN class_schedules cs ON cs.class_id = c.id
                JOIN subjects s ON cs.subject_id = s.id
                {base_where}
                ORDER BY s.name ASC
            """
            cursor.execute(subjects_query, tuple(base_params))
            subjects_rows = cursor.fetchall() or []
            filter_subjects = [
                {
                    "id": row["subject_id"],
                    "code": row["subject_code"],
                    "name": row["subject_name"],
                    "label": f"{row['subject_name']} ({row['subject_code']})" if row.get("subject_code") else row["subject_name"],
                }
                for row in subjects_rows
            ]

            return {
                "items": items,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total_items": total_items,
                    "total_pages": total_pages,
                },
                "filter_options": {
                    "classes": filter_classes,
                    "subjects": filter_subjects,
                },
            }
    finally:
        conn.close()


def check_student_session_eligibility(student_id: str, schedule_id: str) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """
    Kiểm tra một buổi học cụ thể có hợp lệ để học viên gửi đơn hay không.
    Trả về (is_eligible, reason_if_not, schedule_dict).
    """
    now_vn = get_vietnam_now()
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    cs.id AS schedule_id,
                    cs.class_id,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    cs.room_id,
                    cs.status AS schedule_status,
                    c.class_code,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    ce.id AS enrollment_id,
                    ce.enrolled_at,
                    ce.lifecycle_status,
                    ce.effective_date
                FROM class_schedules cs
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN class_enrollments ce ON ce.class_id = c.id AND ce.student_id = %s
                WHERE cs.id = %s
                LIMIT 1
                """,
                (student_id, schedule_id),
            )
            row = cursor.fetchone()
            if not row:
                return False, "Không tìm thấy buổi học trong hệ thống.", None

            if not row.get("enrollment_id"):
                return False, "Bạn không thuộc danh sách học viên của lớp học này.", None

            if row.get("schedule_status") == "cancelled":
                return False, "Buổi học này đã bị hủy, không thể gửi đơn xin phép vắng.", None

            # Kiểm tra ngày ghi danh
            enrolled_at = row.get("enrolled_at")
            learning_date = row.get("learning_date")
            if enrolled_at and learning_date:
                enrolled_date = enrolled_at.date() if isinstance(enrolled_at, datetime) else enrolled_at
                if enrolled_date > learning_date:
                    return False, "Bạn chưa được ghi danh vào thời điểm diễn ra buổi học này.", None

            # Kiểm tra vòng đời học viên (SCRUM-252)
            lifecycle_status = row.get("lifecycle_status")
            effective_date = row.get("effective_date")
            if lifecycle_status in ("reserved", "transferred", "dropped") and effective_date:
                if learning_date >= effective_date:
                    return False, f"Hồ sơ của bạn đã {lifecycle_status} từ ngày {effective_date.isoformat()}, không thể gửi đơn cho buổi học này.", None

            # Kiểm tra thời hạn 48 giờ sau kết thúc buổi học
            end_time_val = row.get("end_time")
            if end_time_val:
                if isinstance(end_time_val, timedelta):
                    total_seconds = int(end_time_val.total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, hours, minutes, tzinfo=VIETNAM_TZ)
                elif hasattr(end_time_val, "hour"):
                    session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, end_time_val.hour, end_time_val.minute, tzinfo=VIETNAM_TZ)
                else:
                    session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, 23, 59, 59, tzinfo=VIETNAM_TZ)
            else:
                session_end_dt = datetime(learning_date.year, learning_date.month, learning_date.day, 23, 59, 59, tzinfo=VIETNAM_TZ)

            deadline = session_end_dt + timedelta(hours=48)
            if now_vn > deadline:
                return False, f"Đã quá thời hạn 48 giờ sau buổi học để gửi đơn xin phép vắng (Hạn chót: {deadline.strftime('%d/%m/%Y %H:%M')}).", None

            row["learning_date_str"] = learning_date.isoformat() if learning_date else None
            return True, "", row
    finally:
        conn.close()


def get_pending_absence_request(student_id: str, schedule_id: str) -> Optional[dict[str, Any]]:
    """
    Kiểm tra xem học viên đã có đơn xin phép vắng ở trạng thái Chờ duyệt (pending) cho buổi học này chưa.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, schedule_id, student_id, reason, status, created_at
                FROM absence_requests
                WHERE student_id = %s AND schedule_id = %s AND status = 'pending'
                LIMIT 1
                """,
                (student_id, schedule_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_existing_active_absence_request(student_id: str, schedule_id: str) -> Optional[dict[str, Any]]:
    """
    Kiểm tra xem học viên đã có đơn xin phép vắng đang chờ duyệt (pending) hoặc đã duyệt (approved) cho buổi học này chưa.
    Ưu tiên trả về đơn approved trước đơn pending nếu tồn tại cả hai.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, schedule_id, student_id, reason, status, created_at
                FROM absence_requests
                WHERE student_id = %s AND schedule_id = %s AND status IN ('approved', 'pending')
                ORDER BY CASE WHEN status = 'approved' THEN 1 ELSE 2 END ASC, created_at DESC
                LIMIT 1
                """,
                (student_id, schedule_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def create_absence_request_record(
    schedule_id: str,
    student_id: str,
    reason: str,
    attachments: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Tạo đơn xin phép vắng trong transaction nguyên tử.
    - Khóa kiểm tra chống tạo trùng đơn pending hoặc approved (an toàn khi 2 request gửi đồng thời).
    - Lưu thông tin đơn vào absence_requests.
    - Lưu danh sách đính kèm vào absence_request_attachments (nếu có).
    """
    req_id = f"ar-{uuid.uuid4().hex}"
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # 0. Khóa hàng học viên trong bảng students bằng FOR UPDATE để tuần tự hóa các yêu cầu gửi đồng thời
            # từ cùng một học viên, loại bỏ hoàn toàn gap lock deadlock (MySQL 1213) khi bảng absence_requests chưa có bản ghi.
            cursor.execute("SELECT id FROM students WHERE id = %s FOR UPDATE", (student_id,))
            cursor.fetchone()

            # 1. Khóa kiểm tra đơn pending hoặc approved hiện có (FOR UPDATE chống concurrency race condition)
            cursor.execute(
                """
                SELECT id, status FROM absence_requests
                WHERE student_id = %s AND schedule_id = %s AND status IN ('approved', 'pending')
                ORDER BY CASE WHEN status = 'approved' THEN 1 ELSE 2 END ASC
                FOR UPDATE
                """,
                (student_id, schedule_id),
            )
            existing = cursor.fetchone()
            if existing:
                if existing["status"] == "approved":
                    raise RuntimeError("DUPLICATE_APPROVED_REQUEST: Buổi học này đã có đơn xin phép vắng được phê duyệt.")
                else:
                    raise RuntimeError("DUPLICATE_PENDING_REQUEST: Buổi học này đã có đơn xin phép vắng đang chờ duyệt.")

            # 2. Tạo bản ghi đơn
            cursor.execute(
                """
                INSERT INTO absence_requests (
                    id, schedule_id, student_id, reason, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                """,
                (req_id, schedule_id, student_id, reason, ABSENCE_STATUS_PENDING),
            )

            # 3. Lưu đính kèm nếu có (Lát 2)
            saved_attachments = []
            if attachments:
                for att in attachments:
                    att_id = f"ara-{uuid.uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO absence_request_attachments (
                            id, request_id, file_name, file_path, file_size, mime_type, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
                        """,
                        (
                            att_id,
                            req_id,
                            att["file_name"],
                            att["file_path"],
                            att["file_size"],
                            att["mime_type"],
                        ),
                    )
                    saved_attachments.append({
                        "id": att_id,
                        "file_name": att["file_name"],
                        "file_size": att["file_size"],
                        "mime_type": att["mime_type"],
                    })

        conn.commit()
        return {
            "id": req_id,
            "schedule_id": schedule_id,
            "student_id": student_id,
            "reason": reason,
            "status": ABSENCE_STATUS_PENDING,
            "status_label": ABSENCE_STATUS_LABELS[ABSENCE_STATUS_PENDING],
            "attachments": saved_attachments,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_absence_request_by_id(request_id: str) -> Optional[dict[str, Any]]:
    """
    Truy vấn chi tiết một đơn xin phép vắng kèm buổi học, thông tin học viên, người duyệt và các tệp đính kèm.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 
                    ar.id,
                    ar.schedule_id,
                    ar.student_id,
                    ar.reason,
                    ar.status,
                    ar.reviewed_by,
                    ar.reviewed_at,
                    ar.rejection_reason,
                    ar.created_at,
                    ar.updated_at,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    cs.status AS schedule_status,
                    c.id AS class_id,
                    c.class_code,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    COALESCE(cr.room_name, cr.room_code, cs.room_id) AS room_name,
                    stu.student_code,
                    stu.user_id AS student_user_id,
                    stu.full_name AS student_name,
                    stu.email AS student_email,
                    reviewer.name AS reviewer_name,
                    reviewer.email AS reviewer_email
                FROM absence_requests ar
                JOIN class_schedules cs ON ar.schedule_id = cs.id
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                JOIN students stu ON ar.student_id = stu.id
                LEFT JOIN users reviewer ON ar.reviewed_by = reviewer.id
                WHERE ar.id = %s
                LIMIT 1
                """,
                (request_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            learning_date = row.get("learning_date")
            row["learning_date"] = learning_date.isoformat() if learning_date else None
            row["learning_date_str"] = row["learning_date"]
            row["start_time"] = str(row["start_time"]) if row.get("start_time") else None
            row["start_time_str"] = row["start_time"]
            row["end_time"] = str(row["end_time"]) if row.get("end_time") else None
            row["end_time_str"] = row["end_time"]
            row["status_label"] = ABSENCE_STATUS_LABELS.get(row["status"], row["status"])
            row["created_at"] = format_utc_timestamp_iso(row.get("created_at"))
            row["updated_at"] = format_utc_timestamp_iso(row.get("updated_at"))
            row["reviewed_at"] = format_utc_timestamp_iso(row.get("reviewed_at"))

            # Lấy attachments
            cursor.execute(
                """
                SELECT id, request_id, file_name, file_path, file_size, mime_type, created_at
                FROM absence_request_attachments
                WHERE request_id = %s
                ORDER BY created_at ASC
                """,
                (request_id,),
            )
            attachments = cursor.fetchall() or []
            for att in attachments:
                att["created_at"] = format_utc_timestamp_iso(att.get("created_at"))
            row["attachments"] = attachments

            return row
    finally:
        conn.close()


def list_student_absence_requests(
    student_id: str,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """
    Truy vấn danh sách đơn xin phép vắng của một học viên có phân trang và bộ lọc phía Backend.
    """
    limit_val = min(max(int(limit), 1), 20)
    page_val = max(int(page), 1)
    offset = (page_val - 1) * limit_val

    where_clauses = ["ar.student_id = %s"]
    params: list[Any] = [student_id]

    if status_filter and status_filter.strip() and status_filter.strip().lower() != "all":
        where_clauses.append("ar.status = %s")
        params.append(status_filter.strip().lower())

    if search_query and str(search_query).strip():
        q = f"%{str(search_query).strip()}%"
        where_clauses.append("(c.class_code LIKE %s OR s.name LIKE %s OR s.code LIKE %s OR ar.reason LIKE %s)")
        params.extend([q, q, q, q])

    where_str = " AND ".join(where_clauses)

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # Đếm tổng số
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM absence_requests ar
                JOIN class_schedules cs ON ar.schedule_id = cs.id
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                WHERE {where_str}
                """,
                tuple(params),
            )
            total = cursor.fetchone()["total"]

            # Lấy danh sách trang
            cursor.execute(
                f"""
                SELECT 
                    ar.id,
                    ar.schedule_id,
                    ar.student_id,
                    ar.reason,
                    ar.status,
                    ar.reviewed_by,
                    ar.reviewed_at,
                    ar.rejection_reason,
                    ar.created_at,
                    ar.updated_at,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    c.class_code,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    u.name AS instructor_name,
                    reviewer.name AS reviewer_name,
                    (
                        SELECT COUNT(*) 
                        FROM absence_request_attachments ara 
                        WHERE ara.request_id = ar.id
                    ) AS attachment_count
                FROM absence_requests ar
                JOIN class_schedules cs ON ar.schedule_id = cs.id
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN users u ON cs.instructor_id = u.id
                LEFT JOIN users reviewer ON ar.reviewed_by = reviewer.id
                WHERE {where_str}
                ORDER BY ar.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [limit_val, offset]),
            )
            rows = cursor.fetchall() or []
            for r in rows:
                learning_date = r.get("learning_date")
                r["learning_date"] = learning_date.isoformat() if learning_date else None
                r["learning_date_str"] = r["learning_date"]
                r["start_time"] = str(r["start_time"]) if r.get("start_time") else None
                r["start_time_str"] = r["start_time"]
                r["end_time"] = str(r["end_time"]) if r.get("end_time") else None
                r["end_time_str"] = r["end_time"]
                r["status_label"] = ABSENCE_STATUS_LABELS.get(r["status"], r["status"])
                r["created_at"] = format_utc_timestamp_iso(r.get("created_at"))
                r["updated_at"] = format_utc_timestamp_iso(r.get("updated_at"))
                r["reviewed_at"] = format_utc_timestamp_iso(r.get("reviewed_at"))

            return rows, total
    finally:
        conn.close()


def get_attachment_by_id(attachment_id: str) -> Optional[dict[str, Any]]:
    """Truy vấn thông tin của một tệp đính kèm theo attachment_id."""
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT ara.id, ara.request_id, ara.file_name, ara.file_path, ara.file_size, ara.mime_type, ara.created_at,
                       ar.student_id, ar.schedule_id
                FROM absence_request_attachments ara
                JOIN absence_requests ar ON ara.request_id = ar.id
                WHERE ara.id = %s
                LIMIT 1
                """,
                (attachment_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            row["created_at"] = format_utc_timestamp_iso(row.get("created_at"))
            return row
    finally:
        conn.close()


def list_absence_requests_for_reviewer(
    reviewer_user_id: str,
    is_training_manager: bool,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    schedule_id: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """
    Truy vấn danh sách đơn xin phép vắng cho giảng viên hoặc quản lý đào tạo (SCRUM-255 Lát 3).
    - Quản lý đào tạo: Xem được toàn bộ đơn trong hệ thống.
    - Giảng viên: Chỉ xem các đơn thuộc các buổi học mình được phân công (instructor_id hoặc class_subject_instructors).
    """
    limit_val = min(max(int(limit), 1), 20)
    page_val = max(int(page), 1)
    offset = (page_val - 1) * limit_val

    where_clauses = []
    params: list[Any] = []

    if not is_training_manager:
        where_clauses.append(
            """(
                cs.instructor_id = %s
                OR EXISTS (
                    SELECT 1 FROM class_subject_instructors csi
                    WHERE csi.class_subject_id = cs.class_subject_id
                      AND csi.instructor_id = %s
                )
            )"""
        )
        params.extend([reviewer_user_id, reviewer_user_id])

    if status_filter and status_filter.strip() and status_filter.strip().lower() != "all":
        where_clauses.append("ar.status = %s")
        params.append(status_filter.strip().lower())

    if schedule_id and str(schedule_id).strip():
        where_clauses.append("ar.schedule_id = %s")
        params.append(str(schedule_id).strip())

    if search_query and str(search_query).strip():
        q = f"%{str(search_query).strip()}%"
        where_clauses.append(
            "(c.class_code LIKE %s OR s.name LIKE %s OR s.code LIKE %s OR stu.full_name LIKE %s OR stu.student_code LIKE %s OR ar.reason LIKE %s)"
        )
        params.extend([q, q, q, q, q, q])

    where_str = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # Đếm tổng số
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM absence_requests ar
                JOIN class_schedules cs ON ar.schedule_id = cs.id
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                JOIN students stu ON ar.student_id = stu.id
                {where_str}
                """,
                tuple(params),
            )
            total = cursor.fetchone()["total"]

            # Lấy danh sách trang
            cursor.execute(
                f"""
                SELECT 
                    ar.id,
                    ar.schedule_id,
                    ar.student_id,
                    ar.reason,
                    ar.status,
                    ar.reviewed_by,
                    ar.reviewed_at,
                    ar.rejection_reason,
                    ar.created_at,
                    ar.updated_at,
                    cs.session_number,
                    cs.topic,
                    cs.learning_date,
                    cs.shift,
                    cs.start_time,
                    cs.end_time,
                    cs.status AS schedule_status,
                    c.id AS class_id,
                    c.class_code,
                    s.name AS subject_name,
                    s.code AS subject_code,
                    COALESCE(cr.room_name, cr.room_code, cs.room_id) AS room_name,
                    stu.student_code,
                    stu.full_name AS student_name,
                    stu.email AS student_email,
                    reviewer.name AS reviewer_name,
                    (
                        SELECT COUNT(*) 
                        FROM absence_request_attachments ara 
                        WHERE ara.request_id = ar.id
                    ) AS attachment_count
                FROM absence_requests ar
                JOIN class_schedules cs ON ar.schedule_id = cs.id
                JOIN classes c ON cs.class_id = c.id
                LEFT JOIN subjects s ON cs.subject_id = s.id
                LEFT JOIN classrooms cr ON (cs.room_id = cr.id OR cs.room_id = cr.room_code)
                JOIN students stu ON ar.student_id = stu.id
                LEFT JOIN users reviewer ON ar.reviewed_by = reviewer.id
                {where_str}
                ORDER BY 
                    CASE WHEN ar.status = 'pending' THEN 0 ELSE 1 END,
                    ar.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params + [limit_val, offset]),
            )
            rows = cursor.fetchall() or []
            for r in rows:
                learning_date = r.get("learning_date")
                r["learning_date"] = learning_date.isoformat() if learning_date else None
                r["learning_date_str"] = r["learning_date"]
                r["start_time"] = str(r["start_time"]) if r.get("start_time") else None
                r["start_time_str"] = r["start_time"]
                r["end_time"] = str(r["end_time"]) if r.get("end_time") else None
                r["end_time_str"] = r["end_time"]
                r["status_label"] = ABSENCE_STATUS_LABELS.get(r["status"], r["status"])
                r["created_at"] = format_utc_timestamp_iso(r.get("created_at"))
                r["updated_at"] = format_utc_timestamp_iso(r.get("updated_at"))
                r["reviewed_at"] = format_utc_timestamp_iso(r.get("reviewed_at"))

            return rows, total
    finally:
        conn.close()


def review_absence_request_record(
    request_id: str,
    reviewer_user_id: str,
    action: str,
    rejection_reason: Optional[str] = None,
) -> dict[str, Any]:
    """
    Xử lý duyệt hoặc từ chối đơn trong một transaction nguyên tử (SCRUM-255 Lát 3).
    - Khóa hàng đơn (FOR UPDATE) để ngăn chặn 2 người xử lý đồng thời tạo mâu thuẫn.
    - Kiểm tra trạng thái: chỉ cho phép duyệt khi đơn đang ở trạng thái 'pending'.
    - Nếu action == 'approve':
      + Kiểm tra điểm danh hiện tại của học viên trên buổi học. Nếu đã 'present' hoặc 'late' -> CHẶN duyệt.
      + Cập nhật đơn thành 'approved', lưu reviewer_user_id và thời điểm UTC.
      + Cập nhật/thêm bản ghi điểm danh học viên thành 'excused' (Vắng có phép).
      + Ghi nhận lịch sử kiểm toán vào attendance_audit_logs với lý do liên kết ID đơn.
      + KHÔNG tự ý bật attendance_checked trên class_schedules (đặc biệt đối với buổi tương lai).
    - Nếu action == 'reject':
      + Kiểm tra lý do từ chối (bắt buộc).
      + Cập nhật đơn thành 'rejected', lưu reviewer_user_id, thời điểm UTC và rejection_reason.
      + KHÔNG thay đổi điểm danh học viên sang vắng không phép.
    - Rollback hoàn toàn nếu có bất kỳ lỗi nào xảy ra.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            # 1. Khóa hàng đơn để chống đồng thời
            cursor.execute(
                """
                SELECT id, schedule_id, student_id, status
                FROM absence_requests
                WHERE id = %s
                FOR UPDATE
                """,
                (request_id,),
            )
            req = cursor.fetchone()
            if not req:
                raise RuntimeError("REQUEST_NOT_FOUND")

            if req["status"] != ABSENCE_STATUS_PENDING:
                raise RuntimeError("REQUEST_ALREADY_REVIEWED")

            schedule_id = req["schedule_id"]
            student_id = req["student_id"]

            # 2. Khóa hàng buổi học
            cursor.execute(
                "SELECT id, status, learning_date FROM class_schedules WHERE id = %s FOR UPDATE",
                (schedule_id,),
            )
            sched = cursor.fetchone()
            if not sched:
                raise RuntimeError("SESSION_NOT_FOUND")
            if sched.get("status") == "cancelled":
                raise RuntimeError("SESSION_CANCELLED")

            # 3. Khóa hàng điểm danh hiện tại của học viên tại buổi học
            cursor.execute(
                """
                SELECT id, status, notes
                FROM session_attendances
                WHERE schedule_id = %s AND student_id = %s
                FOR UPDATE
                """,
                (schedule_id, student_id),
            )
            att_row = cursor.fetchone()

            if action == "approve":
                # Chặn duyệt thêm đơn trùng nếu đã có đơn Đã duyệt cho cùng học viên/buổi
                cursor.execute(
                    """
                    SELECT id FROM absence_requests
                    WHERE student_id = %s AND schedule_id = %s AND status = 'approved' AND id != %s
                    FOR UPDATE
                    """,
                    (student_id, schedule_id, request_id),
                )
                if cursor.fetchone():
                    raise RuntimeError("ALREADY_HAS_APPROVED_REQUEST: Buổi học này đã có đơn xin phép vắng được phê duyệt trước đó.")

                # Chặn nếu học viên đã có mặt hoặc đi muộn
                if att_row and att_row["status"] in ("present", "late"):
                    raise RuntimeError("ATTENDANCE_CONFLICT_PRESENT_LATE")

                # Cập nhật đơn thành approved
                cursor.execute(
                    """
                    UPDATE absence_requests
                    SET status = %s,
                        reviewed_by = %s,
                        reviewed_at = UTC_TIMESTAMP(6),
                        rejection_reason = NULL,
                        updated_at = UTC_TIMESTAMP(6)
                    WHERE id = %s
                    """,
                    (ABSENCE_STATUS_APPROVED, reviewer_user_id, request_id),
                )

                old_status = att_row["status"] if att_row else None
                new_status = "excused"
                note_text = "Nghỉ có phép theo đơn duyệt"

                # Upsert session_attendances
                if att_row:
                    cursor.execute(
                        """
                        UPDATE session_attendances
                        SET status = %s,
                            notes = COALESCE(notes, %s),
                            recorded_by = %s,
                            updated_at = UTC_TIMESTAMP(6)
                        WHERE id = %s
                        """,
                        (new_status, note_text, reviewer_user_id, att_row["id"]),
                    )
                else:
                    new_sa_id = f"sa-{uuid.uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO session_attendances (
                            id, schedule_id, student_id, status, notes, recorded_by, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                        """,
                        (new_sa_id, schedule_id, student_id, new_status, note_text, reviewer_user_id),
                    )

                # Ghi nhận lịch sử attendance_audit_logs
                log_id = f"aal-{uuid.uuid4().hex}"
                audit_reason = f"Duyệt đơn xin phép vắng (Mã đơn: {request_id})"
                cursor.execute(
                    """
                    INSERT INTO attendance_audit_logs (
                        id, schedule_id, student_id, old_status, new_status, reason, performed_by, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
                    """,
                    (log_id, schedule_id, student_id, old_status, new_status, audit_reason, reviewer_user_id),
                )

            elif action == "reject":
                if not rejection_reason or not str(rejection_reason).strip():
                    raise RuntimeError("REJECTION_REASON_REQUIRED")

                clean_rejection_reason = str(rejection_reason).strip()

                cursor.execute(
                    """
                    UPDATE absence_requests
                    SET status = %s,
                        reviewed_by = %s,
                        reviewed_at = UTC_TIMESTAMP(6),
                        rejection_reason = %s,
                        updated_at = UTC_TIMESTAMP(6)
                    WHERE id = %s
                    """,
                    (ABSENCE_STATUS_REJECTED, reviewer_user_id, clean_rejection_reason, request_id),
                )
                # Điểm danh giữ nguyên không đổi

            else:
                raise RuntimeError("INVALID_REVIEW_ACTION")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return get_absence_request_by_id(request_id)


