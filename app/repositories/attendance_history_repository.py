"""
Repository truy vấn Lịch sử điểm danh cá nhân của Học viên (SCRUM-258).
Bao gồm danh sách buổi học, trạng thái điểm danh, tỷ lệ chuyên cần và số liệu cảnh báo ngưỡng vắng.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import logging
import math
from typing import Any, Optional

from app.database.connection import get_db_connection
from app.repositories import attendance_summary_repository, training_program_repository

logger = logging.getLogger(__name__)

VIETNAM_TZ = timezone(timedelta(hours=7))

CELL_STATUS_CONFIG = {
    "present": {
        "status_label": "Có mặt",
        "symbol": "P",
        "color_token": "green",
    },
    "late": {
        "status_label": "Đi muộn",
        "symbol": "L",
        "color_token": "yellow",
    },
    "excused": {
        "status_label": "Vắng có phép",
        "symbol": "E",
        "color_token": "blue",
    },
    "unexcused": {
        "status_label": "Vắng không phép",
        "symbol": "U",
        "color_token": "red",
    },
    "not_recorded": {
        "status_label": "Chưa điểm danh",
        "symbol": "—",
        "color_token": "grey",
    },
    "future": {
        "status_label": "Chưa diễn ra",
        "symbol": "—",
        "color_token": "grey",
    },
    "cancelled": {
        "status_label": "Đã hủy",
        "symbol": "C",
        "color_token": "cancelled",
    },
    "not_applicable": {
        "status_label": "Không áp dụng",
        "symbol": "N/A",
        "color_token": "grey",
    },
}


def _parse_time_value(val: Any) -> Optional[time]:
    """Chuyển đổi time / timedelta / str từ database sang đối tượng time chuẩn."""
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, timedelta):
        total_seconds = int(val.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return time(hours, minutes, seconds)
    if isinstance(val, str):
        parts = val.strip().split(":")
        if len(parts) >= 2:
            try:
                h = int(parts[0])
                m = int(parts[1])
                s = int(parts[2]) if len(parts) > 2 else 0
                return time(h, m, s)
            except ValueError:
                return None
    return None


def get_student_by_user_id(user_id: str) -> Optional[dict[str, Any]]:
    """
    Tìm thông tin học viên theo user_id từ JWT.
    Hỗ trợ ánh xạ qua s.user_id hoặc s.id hoặc email của user.
    """
    if not user_id:
        return None
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


def get_student_enrolled_classes(student_id: str) -> list[dict[str, Any]]:
    """
    Lấy danh sách các lớp học mà học viên đã ghi danh hợp lệ hoặc từng có lịch sử điểm danh.
    """
    if not student_id:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT
                    c.id AS class_id,
                    c.class_code,
                    c.learning_mode,
                    c.status AS class_status,
                    ce.status AS enrollment_status,
                    tp.id AS program_id,
                    tp.name AS program_name,
                    tp.code AS program_code,
                    COALESCE(tp.absence_alert_threshold, 20.0) AS absence_alert_threshold
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE ce.student_id = %s
                  AND ce.status IN ('enrolled', 'active', 'studying', 'completed')
                ORDER BY ce.created_at DESC
                """,
                (student_id,),
            )
            rows = cursor.fetchall() or []
            for r in rows:
                if r.get("absence_alert_threshold") is not None:
                    r["absence_alert_threshold"] = float(r["absence_alert_threshold"])
                else:
                    r["absence_alert_threshold"] = 20.0
            return rows
    finally:
        conn.close()


def is_student_enrolled_in_class(student_id: str, class_id: str) -> bool:
    """
    Kiểm tra học viên có quyền truy cập thông tin lớp học (có ghi danh hoặc có điểm danh thực tế).
    """
    if not student_id or not class_id:
        return False
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM class_enrollments ce
                WHERE ce.student_id = %s AND ce.class_id = %s
                LIMIT 1
                """,
                (student_id, class_id),
            )
            if cursor.fetchone():
                return True
            cursor.execute(
                """
                SELECT 1
                FROM session_attendances sa
                JOIN class_schedules cs ON sa.schedule_id = cs.id
                WHERE sa.student_id = %s AND cs.class_id = %s
                LIMIT 1
                """,
                (student_id, class_id),
            )
            return cursor.fetchone() is not None
    finally:
        conn.close()


def get_student_enrollment_lifecycle(student_id: str, class_id: str) -> Optional[dict[str, Any]]:
    """
    Lấy thông tin ghi danh và vòng đời của học viên trong lớp cụ thể.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT ce.id, ce.enrolled_at, ce.status AS enrollment_status,
                       ce.lifecycle_status, ce.effective_date
                FROM class_enrollments ce
                WHERE ce.student_id = %s AND ce.class_id = %s
                LIMIT 1
                """,
                (student_id, class_id),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def get_student_class_attendances(class_id: str, student_id: str) -> dict[str, dict[str, Any]]:
    """
    Lấy danh sách các bản ghi điểm danh thực tế của học viên trong lớp theo schedule_id.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT sa.id, sa.schedule_id, sa.student_id, sa.status, sa.notes, sa.updated_at
                FROM session_attendances sa
                JOIN class_schedules cs ON sa.schedule_id = cs.id
                WHERE cs.class_id = %s AND sa.student_id = %s
                """,
                (class_id, student_id),
            )
            rows = cursor.fetchall() or []
            return {r["schedule_id"]: r for r in rows}
    finally:
        conn.close()


def get_student_attendance_history(
    student_id: str,
    class_id: str,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "learning_date",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """
    Truy xuất lịch sử điểm danh đầy đủ của học viên trong một lớp (SCRUM-258).
    - Tính toán tổng quan chuyên cần toàn lớp độc lập với phân trang / bộ lọc (AC1).
    - Tính toán cảnh báo vắng và số buổi còn lại theo công thức SCRUM-257 (AC2).
    - Lọc và phân trang danh sách buổi học theo yêu cầu client.
    """
    class_info = attendance_summary_repository.get_class_details(class_id)
    if not class_info:
        return {}

    program_id = class_info.get("program_id")
    threshold = 20.0
    if program_id:
        program = training_program_repository.get_training_program_by_id(program_id)
        if program and program.absence_alert_threshold is not None:
            threshold = float(program.absence_alert_threshold)

    # Thời gian server
    now_vn = datetime.now(VIETNAM_TZ)
    today_vn = now_vn.date()
    now_time = now_vn.time()

    # Vòng đời ghi danh của học viên
    enrollment = get_student_enrollment_lifecycle(student_id, class_id)
    enrolled_date = None
    lifecycle_status = None
    effective_date_val = None

    if enrollment:
        lifecycle_status = enrollment.get("lifecycle_status")
        enrolled_at = enrollment.get("enrolled_at")
        if enrolled_at:
            if isinstance(enrolled_at, (datetime, date)):
                enrolled_date = enrolled_at.date() if isinstance(enrolled_at, datetime) else enrolled_at
            else:
                enrolled_date = date.fromisoformat(str(enrolled_at)[:10])

        effective_date = enrollment.get("effective_date")
        if effective_date:
            if isinstance(effective_date, (datetime, date)):
                effective_date_val = effective_date.date() if isinstance(effective_date, datetime) else effective_date
            else:
                effective_date_val = date.fromisoformat(str(effective_date)[:10])

    # Toàn bộ buổi học thực tế của lớp (sắp xếp ASC theo thời gian)
    schedules = attendance_summary_repository.get_class_schedules_for_summary(class_id)
    att_map = get_student_class_attendances(class_id, student_id)

    # Thống kê toàn lớp
    present_count = 0
    late_count = 0
    excused_count = 0
    unexcused_count = 0
    unrecorded_ended_count = 0
    future_count = 0
    cancelled_count = 0

    N = 0  # Tổng số buổi học viên phải tham dự (AC2)
    A = 0  # Số buổi vắng đã kết thúc (có phép + không phép) (AC2)

    all_processed_sessions: list[dict[str, Any]] = []

    for s in schedules:
        sched_id = s["id"]
        learning_date = s["learning_date"]
        if isinstance(learning_date, str):
            learning_date_val = date.fromisoformat(learning_date)
        elif isinstance(learning_date, (datetime, date)):
            learning_date_val = learning_date.date() if isinstance(learning_date, datetime) else learning_date
        else:
            learning_date_val = today_vn

        end_time_val = _parse_time_value(s.get("end_time"))
        start_time_val = _parse_time_value(s.get("start_time"))

        is_cancelled = (s.get("status") == "cancelled")
        is_past = (learning_date_val < today_vn)
        is_future = (learning_date_val > today_vn)

        if is_past:
            has_ended = True
        elif is_future:
            has_ended = False
        else:
            # Hôm nay
            if s.get("attendance_checked"):
                has_ended = True
            elif end_time_val:
                has_ended = (now_time >= end_time_val)
            else:
                has_ended = False

        # Kiểm tra tính áp dụng của học viên
        is_eligible = True
        if enrolled_date and enrolled_date > learning_date_val:
            is_eligible = False
        elif lifecycle_status in ("reserved", "transferred", "dropped") and effective_date_val:
            if learning_date_val >= effective_date_val:
                is_eligible = False

        sa = att_map.get(sched_id)

        # Xác định trạng thái buổi học
        is_pre_approved = False
        if is_cancelled:
            final_status = "cancelled"
            cancelled_count += 1
        elif not is_eligible and not sa:
            final_status = "not_applicable"
        elif sa:
            raw_st = sa.get("status", "present")
            final_status = raw_st
            if not has_ended:
                is_pre_approved = (raw_st == "excused")
            else:
                if raw_st == "present":
                    present_count += 1
                elif raw_st == "late":
                    late_count += 1
                elif raw_st == "excused":
                    excused_count += 1
                elif raw_st == "unexcused":
                    unexcused_count += 1
        else:
            if has_ended:
                final_status = "not_recorded"
                unrecorded_ended_count += 1
            else:
                final_status = "future"
                future_count += 1

        # AC2 Metrics:
        # N = Tổng số buổi học thực tế của lớp đã xếp lịch, không bị hủy, học viên phải tham dự
        if is_eligible and not is_cancelled:
            N += 1
            if has_ended and sa:
                st = sa.get("status")
                if st in ("excused", "unexcused"):
                    A += 1

        cfg = CELL_STATUS_CONFIG.get(final_status, {
            "status_label": final_status,
            "symbol": final_status[:1].upper(),
            "color_token": "grey",
        })

        # Ghi chú an toàn cho học viên: sa.notes nếu có, hoặc lý do hủy
        safe_notes = sa.get("notes") if sa else None
        if is_cancelled and not safe_notes:
            safe_notes = s.get("cancellation_reason") or "Buổi học đã bị hủy"

        status_label_display = cfg["status_label"]
        if is_pre_approved:
            status_label_display = "Đã duyệt nghỉ"

        session_item = {
            "schedule_id": sched_id,
            "class_id": class_id,
            "session_number": s.get("session_number"),
            "topic": s.get("topic"),
            "learning_date": learning_date_val.isoformat(),
            "shift": s.get("shift"),
            "start_time": str(s.get("start_time")) if s.get("start_time") else None,
            "end_time": str(s.get("end_time")) if s.get("end_time") else None,
            "subject_id": s.get("subject_id"),
            "subject_name": s.get("subject_name"),
            "subject_code": s.get("subject_code"),
            "room_name": s.get("room_name"),
            "instructor_name": s.get("instructor_name"),
            "status": final_status,
            "status_label": status_label_display,
            "symbol": cfg["symbol"],
            "color_token": cfg["color_token"],
            "notes": safe_notes,
            "is_pre_approved": is_pre_approved,
            "is_eligible": is_eligible,
            "is_cancelled": is_cancelled,
            "has_ended": has_ended,
            "is_future": is_future,
            "_learning_date_val": learning_date_val,
            "_start_time_val": start_time_val or time(0, 0),
        }
        all_processed_sessions.append(session_item)

    # 1. Tính toán Tỷ lệ chuyên cần (AC1)
    attended_count = present_count + late_count
    total_absent = excused_count + unexcused_count
    valid_sessions_count = attended_count + total_absent  # D = P + L + E + U

    if valid_sessions_count > 0:
        attendance_rate_raw = (attended_count / valid_sessions_count) * 100.0
        attendance_rate = round(attendance_rate_raw, 2)
        attendance_rate_formatted = f"{attendance_rate:.2f}".rstrip("0").rstrip(".") + "%"
    else:
        attendance_rate_raw = None
        attendance_rate = None
        attendance_rate_formatted = "Chưa có dữ liệu"

    # 2. Tính toán Cảnh báo vắng & Số buổi còn lại (AC2)
    # Quy tắc SCRUM-257: A * 100 > threshold * N
    # K = floor(threshold * N / 100) (số buổi vắng tối đa chưa vượt ngưỡng)
    # R = max(0, K - A) (số buổi vắng có thể tăng thêm mà chưa vượt ngưỡng)
    if N == 0:
        insufficient_data = True
        is_flagged = False
        K = None
        R = None
        warning_status = "insufficient_data"
        warning_level = "info"
        warning_message = "Chưa đủ dữ liệu để tính ngưỡng."
    else:
        insufficient_data = False
        K = math.floor((threshold * N) / 100.0)
        is_exceeded = (A * 100 > threshold * N)
        is_flagged = is_exceeded

        threshold_display = f"{threshold:.2f}".rstrip("0").rstrip(".")
        absence_pct = round((A / N) * 100.0, 2)
        absence_pct_display = f"{absence_pct:.2f}".rstrip("0").rstrip(".")

        if is_exceeded:
            R = 0
            warning_status = "exceeded"
            warning_level = "danger"
            warning_message = (
                f"Bạn đã vắng {A}/{N} buổi, tương đương {absence_pct_display}%, vượt ngưỡng {threshold_display}%. "
                f"Vui lòng liên hệ giảng viên hoặc Quản lý đào tạo."
            )
        elif A == K:
            R = 0
            warning_status = "at_limit"
            warning_level = "warning"
            warning_message = (
                f"Bạn đã vắng {A}/{N} buổi, bằng mức tối đa cho phép theo ngưỡng {threshold_display}%. "
                f"Vắng thêm 1 buổi sẽ vượt ngưỡng."
            )
        elif A >= 1 and (K - A) <= 1:
            R = K - A
            warning_status = "approaching"
            warning_level = "warning"
            warning_message = (
                f"Bạn đang gần ngưỡng vắng. Hiện đã vắng {A}/{N} buổi; "
                f"còn {R} buổi vắng trước khi chạm mức tối đa chưa vượt ngưỡng."
            )
        else:
            R = max(0, K - A)
            warning_status = "normal"
            warning_level = "success"
            warning_message = (
                f"Bạn đã vắng {A}/{N} buổi. Theo ngưỡng {threshold_display}% và lịch hiện tại, "
                f"bạn có thể vắng thêm {R} buổi mà chưa vượt ngưỡng."
            )

    # 3. Lọc danh sách buổi hiển thị
    filtered = all_processed_sessions
    if status_filter and status_filter.strip() and status_filter.strip().lower() != "all":
        st_norm = status_filter.strip().lower()
        filtered = [s for s in filtered if s["status"] == st_norm]

    if date_from and date_from.strip():
        try:
            df = date.fromisoformat(date_from.strip())
            filtered = [s for s in filtered if s["_learning_date_val"] >= df]
        except Exception:
            pass

    if date_to and date_to.strip():
        try:
            dt = date.fromisoformat(date_to.strip())
            filtered = [s for s in filtered if s["_learning_date_val"] <= dt]
        except Exception:
            pass

    # 4. Sắp xếp danh sách
    reverse_sort = (sort_order.lower() == "desc")
    filtered.sort(
        key=lambda x: (x["_learning_date_val"], x["_start_time_val"], x["schedule_id"]),
        reverse=reverse_sort,
    )

    # 5. Phân trang
    total_items = len(filtered)
    page_size = max(1, min(page_size, 100))
    total_pages = max(1, math.ceil(total_items / page_size))
    current_page = max(1, min(page, total_pages))

    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    paged_sessions = filtered[start_idx:end_idx]

    # Loại bỏ các key tạm
    cleaned_sessions = []
    for s in paged_sessions:
        item = dict(s)
        item.pop("_learning_date_val", None)
        item.pop("_start_time_val", None)
        cleaned_sessions.append(item)

    return {
        "class_info": {
            "id": class_info["id"],
            "class_code": class_info.get("class_code"),
            "program_id": program_id,
            "program_name": class_info.get("program_name"),
            "program_code": class_info.get("program_code"),
            "status": class_info.get("status"),
            "threshold": threshold,
        },
        "summary": {
            "scope": "class_wide",
            "present_count": present_count,
            "late_count": late_count,
            "excused_count": excused_count,
            "unexcused_count": unexcused_count,
            "unrecorded_ended_count": unrecorded_ended_count,
            "future_count": future_count,
            "cancelled_count": cancelled_count,
            "valid_sessions_count": valid_sessions_count,
            "attendance_rate": attendance_rate,
            "attendance_rate_formatted": attendance_rate_formatted,
        },
        "absence_warning": {
            "total_sessions_N": N,
            "absent_sessions_A": A,
            "threshold_T": threshold,
            "max_allowed_absences_K": K,
            "remaining_absences_R": R,
            "warning_status": warning_status,
            "warning_level": warning_level,
            "warning_message": warning_message,
            "is_flagged": is_flagged,
            "insufficient_data": insufficient_data,
        },
        "sessions": cleaned_sessions,
        "pagination": {
            "page": current_page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
        },
    }
