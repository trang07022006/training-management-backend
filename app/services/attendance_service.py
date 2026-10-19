"""
Service xử lý logic nghiệp vụ Điểm danh học viên theo buổi học (SCRUM-254).
"""

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Optional

from app.models.session_attendance import (
    ATTENDANCE_STATUSES,
    ATTENDANCE_STATUS_LABELS,
)
from app.repositories import attendance_repository
from app.repositories import student_lifecycle_repository

logger = logging.getLogger(__name__)

# Múi giờ chuẩn nghiệp vụ Việt Nam (UTC+7)
VIETNAM_TZ = timezone(timedelta(hours=7))


class AttendanceServiceError(Exception):
    """Lỗi nền tảng của phân hệ điểm danh."""
    def __init__(self, code: str, message: str, status_code: int = 400, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data


class SessionNotFoundError(AttendanceServiceError):
    def __init__(self, message: str = "Không tìm thấy buổi học."):
        super().__init__("SESSION_NOT_FOUND", message, status_code=404)


class ForbiddenAttendanceAccessError(AttendanceServiceError):
    def __init__(self, message: str = "Bạn không có quyền truy cập hoặc điểm danh cho buổi học này."):
        super().__init__("FORBIDDEN_ATTENDANCE_ACCESS", message, status_code=403)


class PastSessionEditForbiddenError(AttendanceServiceError):
    def __init__(self, message: str = "Chỉ Quản lý đào tạo mới được phép chỉnh sửa điểm danh của buổi học trong quá khứ."):
        super().__init__("PAST_SESSION_EDIT_FORBIDDEN", message, status_code=403)


class FutureSessionAttendanceError(AttendanceServiceError):
    def __init__(self, message: str = "Không thể điểm danh trước cho buổi học trong tương lai."):
        super().__init__("FUTURE_SESSION_ATTENDANCE_BLOCKED", message, status_code=400)


class SessionCancelledError(AttendanceServiceError):
    def __init__(self, message: str = "Buổi học đã bị hủy, không thể thực hiện điểm danh."):
        super().__init__("SESSION_CANCELLED", message, status_code=400)


def get_vietnam_today() -> date:
    """Lấy ngày hiện tại theo múi giờ nghiệp vụ Việt Nam (UTC+7)."""
    return datetime.now(VIETNAM_TZ).date()


def get_session_attendance_sheet(
    schedule_id: str,
    current_user_id: str,
    current_user_roles: list[str],
    page: int = 1,
    limit: int = 10,
    search_query: Optional[str] = None,
) -> dict[str, Any]:
    """
    Truy xuất sổ điểm danh của một buổi học (Lát 1 — SCRUM-254).
    Quy tắc:
    - Xác thực buổi học tồn tại.
    - Giảng viên (trainer) chỉ được xem/điểm danh buổi học mà mình được phân công.
    - Quản lý đào tạo (training_manager) được xem/sửa toàn bộ.
    - Admin thuần túy không tự có quyền nghiệp vụ đào tạo.
    - Trạng thái học viên chưa điểm danh trả về status: null (không tự tạo bản ghi vắng).
    - Danh sách học viên được xét theo ngày buổi học thông qua student_lifecycle_repository.
    - Phân trang Backend: Mặc định 10 bản ghi/trang, tối đa 20 bản ghi/trang.
    - Sắp xếp ổn định theo mã học viên và ID để không trùng lặp hay bỏ sót.
    - Thống kê sĩ số/trạng thái phản ánh toàn buổi học, không phụ thuộc trang hay từ khóa tìm kiếm.
    """
    schedule = attendance_repository.get_schedule_details_for_attendance(schedule_id)
    if not schedule:
        raise SessionNotFoundError()

    # 1. Kiểm tra phân quyền truy cập
    normalized_roles = [r.lower().strip() for r in current_user_roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles

    if not is_training_manager and not is_trainer:
        raise ForbiddenAttendanceAccessError(
            "Tài khoản của bạn không có quyền truy cập sổ điểm danh của hệ thống."
        )

    # Nếu là giảng viên thuần túy (không phải quản lý đào tạo), phải được phân công vào buổi học
    if is_trainer and not is_training_manager:
        if not attendance_repository.is_trainer_assigned_to_session(current_user_id, schedule_id):
            raise ForbiddenAttendanceAccessError(
                "Bạn không được phân công phụ trách buổi học này."
            )

    # 2. Phân tích ngày và quyền chỉnh sửa
    today = get_vietnam_today()
    learning_date = schedule["learning_date"]

    is_today = (learning_date == today)
    is_past = (learning_date < today)
    is_future = (learning_date > today)
    is_cancelled = (schedule["status"] == "cancelled")

    can_edit = False
    edit_restriction_reason = None

    if is_cancelled:
        can_edit = False
        edit_restriction_reason = "Buổi học đã bị hủy, không thể điểm danh."
    elif is_future:
        can_edit = False
        edit_restriction_reason = "Buổi học diễn ra trong tương lai, chưa thể điểm danh."
    elif is_past:
        if is_training_manager:
            can_edit = True
        else:
            can_edit = False
            edit_restriction_reason = "Chỉ Quản lý đào tạo mới được phép chỉnh sửa điểm danh của buổi học trong quá khứ."
    else:
        # Buổi hôm nay
        can_edit = True

    # 3. Lấy danh sách học viên đủ điều kiện theo ngày của buổi học (SCRUM-252 integration)
    eligible_students = student_lifecycle_repository.get_eligible_attendance_students(
        class_id=schedule["class_id"],
        session_date_val=learning_date,
    )

    # 4. Lấy các bản ghi điểm danh đã lưu
    saved_attendances = attendance_repository.get_session_attendances(schedule_id)
    saved_map = {row["student_id"]: row for row in saved_attendances}

    # 5. Kết hợp danh sách: Phân biệt rõ chưa điểm danh (null) với vắng
    combined_students: list[dict[str, Any]] = []
    processed_student_ids = set()

    for student in eligible_students:
        s_id = student["student_id"]
        processed_student_ids.add(s_id)
        saved = saved_map.get(s_id)

        if saved:
            combined_students.append({
                "student_id": s_id,
                "student_code": student["student_code"],
                "full_name": student["full_name"],
                "email": student["email"],
                "phone": student["phone"],
                "status": saved["status"],
                "status_label": ATTENDANCE_STATUS_LABELS.get(saved["status"], saved["status"]),
                "notes": saved["notes"],
                "recorded_by": saved["recorded_by"],
                "recorded_by_name": saved.get("recorded_by_name"),
                "updated_at": saved["updated_at"].isoformat() if saved.get("updated_at") else None,
                "is_eligible": True,
            })
        else:
            combined_students.append({
                "student_id": s_id,
                "student_code": student["student_code"],
                "full_name": student["full_name"],
                "email": student["email"],
                "phone": student["phone"],
                "status": None,  # Chưa điểm danh
                "status_label": "Chưa điểm danh",
                "notes": None,
                "recorded_by": None,
                "recorded_by_name": None,
                "updated_at": None,
                "is_eligible": True,
            })

    # Giữ lại học viên có dữ liệu điểm danh lịch sử nhưng hiện tại không còn trong eligible (bảo toàn lịch sử)
    for saved in saved_attendances:
        s_id = saved["student_id"]
        if s_id not in processed_student_ids:
            combined_students.append({
                "student_id": s_id,
                "student_code": saved.get("student_code") or "—",
                "full_name": saved.get("student_name") or "Học viên (đã biến động hồ sơ)",
                "email": saved.get("email"),
                "phone": saved.get("phone"),
                "status": saved["status"],
                "status_label": ATTENDANCE_STATUS_LABELS.get(saved["status"], saved["status"]),
                "notes": saved["notes"],
                "recorded_by": saved["recorded_by"],
                "recorded_by_name": saved.get("recorded_by_name"),
                "updated_at": saved["updated_at"].isoformat() if saved.get("updated_at") else None,
                "is_eligible": False,
                "is_historical_record": True,
            })

    # Sắp xếp ổn định theo mã học viên và ID để các trang phân trang nhất quán
    combined_students.sort(key=lambda s: ((s.get("student_code") or "").upper(), str(s.get("student_id") or "")))

    # 6. Tính toán thống kê toàn bộ buổi học (không phụ thuộc bộ lọc tìm kiếm hay trang)
    present_count = sum(1 for s in combined_students if s["status"] == "present")
    late_count = sum(1 for s in combined_students if s["status"] == "late")
    excused_count = sum(1 for s in combined_students if s["status"] == "excused")
    unexcused_count = sum(1 for s in combined_students if s["status"] == "unexcused")
    unmarked_count = sum(1 for s in combined_students if s["status"] is None)

    # 7. Bộ lọc tìm kiếm theo mã, họ tên hoặc email
    if search_query and str(search_query).strip():
        q = str(search_query).strip().lower()
        filtered_students = [
            s for s in combined_students
            if (
                q in (s.get("student_code") or "").lower()
                or q in (s.get("full_name") or "").lower()
                or q in (s.get("email") or "").lower()
            )
        ]
    else:
        filtered_students = combined_students

    # 8. Phân trang dữ liệu phía Backend (tối đa 20 bản ghi mỗi lần tải)
    try:
        limit_val = int(limit)
    except (ValueError, TypeError):
        limit_val = 10
    limit_val = min(max(limit_val, 1), 20)

    try:
        page_val = int(page)
    except (ValueError, TypeError):
        page_val = 1
    page_val = max(page_val, 1)

    total_items = len(filtered_students)
    total_pages = max(1, (total_items + limit_val - 1) // limit_val) if total_items > 0 else 1

    start_idx = (page_val - 1) * limit_val
    end_idx = start_idx + limit_val
    paged_students = filtered_students[start_idx:end_idx]

    return {
        "session_info": {
            "schedule_id": schedule["id"],
            "class_id": schedule["class_id"],
            "class_code": schedule["class_code"],
            "class_name": schedule["class_name"],
            "subject_name": schedule["subject_name"] or schedule["topic"],
            "subject_code": schedule["subject_code"],
            "session_number": schedule["session_number"],
            "topic": schedule["topic"],
            "learning_date": schedule["learning_date_str"],
            "shift": schedule["shift"],
            "start_time": schedule["start_time_str"],
            "end_time": schedule["end_time_str"],
            "room_id": schedule.get("room_id"),
            "room_name": (str(schedule.get("room_name") or schedule.get("room_id")).strip() if (schedule.get("room_name") or schedule.get("room_id")) else "Chưa xếp phòng"),
            "instructor_id": schedule["instructor_id"],
            "instructor_name": schedule["instructor_name"] or "Chưa phân công",
            "instructor_email": schedule["instructor_email"],
            "status": schedule["status"],
            "attendance_checked": schedule["attendance_checked"],
            "is_today": is_today,
            "is_past": is_past,
            "is_future": is_future,
            "can_edit": can_edit,
            "edit_restriction_reason": edit_restriction_reason,
        },
        "stats": {
            "total_students": len(combined_students),
            "present_count": present_count,
            "late_count": late_count,
            "excused_count": excused_count,
            "unexcused_count": unexcused_count,
            "unmarked_count": unmarked_count,
        },
        "pagination": {
            "page": page_val,
            "limit": limit_val,
            "total_items": total_items,
            "total_pages": total_pages,
        },
        "students": paged_students,
    }


def save_session_attendance_service(
    schedule_id: str,
    payload: dict[str, Any],
    current_user_id: str,
    current_user_roles: list[str],
) -> dict[str, Any]:
    """
    Lưu kết quả điểm danh cho buổi học theo cơ chế nguyên tử (SCRUM-254 Lát 2 & 3).
    - Hỗ trợ lưu danh sách thủ công hoặc đánh dấu tất cả có mặt hàng loạt (mark_all_present).
    - Kiểm tra tính hợp lệ của buổi học, ngày học và quyền hạn.
    - Giảng viên chỉ điểm danh hôm nay; Quản lý đào tạo được sửa quá khứ.
    - Kiểm tra học viên thuộc lớp/buổi học.
    - Cập nhật cờ attendance_checked trên class_schedules.
    - Ghi lịch sử thay đổi vào attendance_audit_logs.
    """
    if not isinstance(payload, dict):
        raise AttendanceServiceError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không đúng định dạng.")

    mark_all_present = bool(payload.get("mark_all_present", False))
    attendance_list = payload.get("attendances")

    if not mark_all_present:
        if not isinstance(attendance_list, list) or len(attendance_list) == 0:
            raise AttendanceServiceError("EMPTY_ATTENDANCE_LIST", "Vui lòng chọn trạng thái điểm danh cho ít nhất một học viên.")

    schedule = attendance_repository.get_schedule_details_for_attendance(schedule_id)
    if not schedule:
        raise SessionNotFoundError()

    # 1. Phân quyền và phạm vi phụ trách
    normalized_roles = [r.lower().strip() for r in current_user_roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles

    if not is_training_manager and not is_trainer:
        raise ForbiddenAttendanceAccessError("Tài khoản của bạn không có quyền lưu điểm danh.")

    if is_trainer and not is_training_manager:
        if not attendance_repository.is_trainer_assigned_to_session(current_user_id, schedule_id):
            raise ForbiddenAttendanceAccessError("Bạn không được phân công phụ trách buổi học này.")

    # 2. Kiểm tra ràng buộc ngày và trạng thái buổi học
    today = get_vietnam_today()
    learning_date = schedule["learning_date"]

    if schedule["status"] == "cancelled":
        raise SessionCancelledError()

    if learning_date > today:
        raise FutureSessionAttendanceError()

    if learning_date < today and not is_training_manager:
        raise PastSessionEditForbiddenError()

    # 3. Kiểm tra danh sách học viên hợp lệ
    eligible_students = student_lifecycle_repository.get_eligible_attendance_students(
        class_id=schedule["class_id"],
        session_date_val=learning_date,
    )
    existing_attendances = attendance_repository.get_session_attendances(schedule_id)
    valid_student_ids = {s["student_id"] for s in eligible_students} | {s["student_id"] for s in existing_attendances}

    clean_items: list[dict[str, Any]] = []

    if mark_all_present:
        # Thao tác hàng loạt: Mặc định tất cả học viên đủ điều kiện là 'present'
        # Các bản ghi trong attendance_list đóng vai trò overrides (người dùng sửa riêng)
        override_map: dict[str, dict[str, Any]] = {}
        if isinstance(attendance_list, list):
            for item in attendance_list:
                if not isinstance(item, dict):
                    continue
                s_id = item.get("student_id")
                st_val = item.get("status")
                notes_val = item.get("notes")
                if not s_id or s_id not in valid_student_ids:
                    raise AttendanceServiceError(
                        "STUDENT_NOT_IN_SESSION",
                        f"Học viên '{s_id}' không thuộc danh sách lớp hoặc buổi học này.",
                    )
                if st_val not in ATTENDANCE_STATUSES:
                    raise AttendanceServiceError(
                        "INVALID_ATTENDANCE_STATUS",
                        f"Trạng thái '{st_val}' không hợp lệ. Chỉ chấp nhận: Có mặt (present), Đi muộn (late), Vắng có phép (excused), Vắng không phép (unexcused).",
                    )
                override_map[s_id] = {
                    "student_id": s_id,
                    "status": st_val,
                    "notes": str(notes_val).strip() if notes_val else None,
                }

        for st in eligible_students:
            s_id = st["student_id"]
            if s_id in override_map:
                clean_items.append(override_map[s_id])
            else:
                clean_items.append({
                    "student_id": s_id,
                    "status": "present",
                    "notes": None,
                })
    else:
        seen_student_ids = set()
        for item in attendance_list:
            if not isinstance(item, dict):
                continue
            student_id = item.get("student_id")
            status = item.get("status")
            notes = item.get("notes")

            if not student_id or student_id not in valid_student_ids:
                raise AttendanceServiceError(
                    "STUDENT_NOT_IN_SESSION",
                    f"Học viên '{student_id}' không thuộc danh sách lớp hoặc buổi học này.",
                )

            if status not in ATTENDANCE_STATUSES:
                raise AttendanceServiceError(
                    "INVALID_ATTENDANCE_STATUS",
                    f"Trạng thái '{status}' không hợp lệ. Chỉ chấp nhận: Có mặt (present), Đi muộn (late), Vắng có phép (excused), Vắng không phép (unexcused).",
                )

            if student_id in seen_student_ids:
                continue
            seen_student_ids.add(student_id)

            clean_items.append({
                "student_id": student_id,
                "status": status,
                "notes": str(notes).strip() if notes else None,
            })

    # 4. Thực thi lưu nguyên tử trong Transaction
    reason = payload.get("reason")
    try:
        updated_count = attendance_repository.save_session_attendance_batch(
            schedule_id=schedule_id,
            attendance_items=clean_items,
            performed_by=current_user_id,
            reason=str(reason).strip() if reason else None,
        )
    except RuntimeError as r_err:
        if str(r_err) == "SESSION_CANCELLED":
            raise SessionCancelledError()
        if str(r_err) == "SESSION_NOT_FOUND":
            raise SessionNotFoundError()
        raise

    # 5. Đọc lại sổ điểm danh sau khi lưu
    updated_sheet = get_session_attendance_sheet(schedule_id, current_user_id, current_user_roles)

    return {
        "updated_count": updated_count,
        "sheet": updated_sheet,
    }


def get_session_attendance_history_service(
    schedule_id: str,
    current_user_id: str,
    current_user_roles: list[str],
) -> list[dict[str, Any]]:
    """
    Truy vấn lịch sử chỉnh sửa điểm danh của một buổi học (SCRUM-254 Lát 3).
    """
    schedule = attendance_repository.get_schedule_details_for_attendance(schedule_id)
    if not schedule:
        raise SessionNotFoundError()

    normalized_roles = [r.lower().strip() for r in current_user_roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles

    if not is_training_manager and not is_trainer:
        raise ForbiddenAttendanceAccessError("Tài khoản của bạn không có quyền xem lịch sử điểm danh.")

    if is_trainer and not is_training_manager:
        if not attendance_repository.is_trainer_assigned_to_session(current_user_id, schedule_id):
            raise ForbiddenAttendanceAccessError("Bạn không được phân công phụ trách buổi học này.")

    raw_logs = attendance_repository.get_attendance_audit_logs(schedule_id)
    formatted = []
    for log in raw_logs:
        old_status = log.get("old_status")
        new_status = log.get("new_status")
        formatted.append({
            "id": log["id"],
            "schedule_id": log["schedule_id"],
            "student_id": log["student_id"],
            "student_name": log.get("student_name"),
            "student_code": log.get("student_code"),
            "old_status": old_status,
            "old_status_label": ATTENDANCE_STATUS_LABELS.get(old_status, "Chưa điểm danh") if old_status else "Chưa điểm danh",
            "new_status": new_status,
            "new_status_label": ATTENDANCE_STATUS_LABELS.get(new_status, new_status),
            "reason": log.get("reason"),
            "performed_by": log["performed_by"],
            "performer_name": log.get("performer_name"),
            "performer_email": log.get("performer_email"),
            "created_at": log["created_at"].isoformat() if log.get("created_at") else None,
        })
    return formatted

