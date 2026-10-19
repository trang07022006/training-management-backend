"""
Service xử lý logic nghiệp vụ Đơn xin phép vắng (SCRUM-255).
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

from app.models.absence_request import (
    ABSENCE_STATUS_APPROVED,
    ABSENCE_STATUS_PENDING,
    ABSENCE_STATUS_REJECTED,
    ABSENCE_STATUSES,
)
from app.repositories import absence_request_repository
from app.repositories import class_schedule_repository

logger = logging.getLogger(__name__)

VIETNAM_TZ = timezone(timedelta(hours=7))


class AbsenceServiceError(Exception):
    """Lỗi nền tảng của phân hệ đơn xin phép vắng."""
    def __init__(self, code: str, message: str, status_code: int = 400, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data


class NotAStudentError(AbsenceServiceError):
    def __init__(self, message: str = "Tài khoản của bạn không được liên kết với hồ sơ học viên nào."):
        super().__init__("NOT_A_STUDENT", message, status_code=403)


class SessionNotEligibleError(AbsenceServiceError):
    def __init__(self, message: str = "Buổi học không hợp lệ để gửi đơn xin phép vắng."):
        super().__init__("SESSION_NOT_ELIGIBLE", message, status_code=400)


class DuplicatePendingRequestError(AbsenceServiceError):
    def __init__(self, message: str = "Buổi học này đã có đơn xin phép vắng đang chờ duyệt."):
        super().__init__("DUPLICATE_PENDING_REQUEST", message, status_code=400)


class RequestNotFoundError(AbsenceServiceError):
    def __init__(self, message: str = "Không tìm thấy đơn xin phép vắng."):
        super().__init__("REQUEST_NOT_FOUND", message, status_code=404)


class ForbiddenAbsenceAccessError(AbsenceServiceError):
    def __init__(self, message: str = "Bạn không có quyền truy cập hoặc thao tác với đơn này."):
        super().__init__("FORBIDDEN_ABSENCE_ACCESS", message, status_code=403)


def _resolve_student_for_user(user_id: str) -> dict[str, Any]:
    """
    Ánh xạ an toàn từ user_id sang hồ sơ học viên.
    Tuyệt đối không nhận student_id do client truyền lên.
    """
    if not user_id or not str(user_id).strip():
        raise NotAStudentError()

    student = class_schedule_repository.get_student_by_user_id(str(user_id).strip())
    if not student:
        raise NotAStudentError()

    return student


def get_eligible_sessions_for_current_student(user_id: str) -> list[dict[str, Any]]:
    """
    Lấy danh sách các buổi học hợp lệ để học viên chọn xin phép vắng.
    """
    student = _resolve_student_for_user(user_id)
    return absence_request_repository.get_student_eligible_sessions(student["id"])


def submit_absence_request_service(
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Học viên nộp đơn xin phép vắng (SCRUM-255 Lát 1).
    Quy tắc:
    - Bắt buộc ánh xạ học viên từ user_id session.
    - Validate schedule_id.
    - Validate reason: không rỗng, không chỉ khoảng trắng, độ dài 5..1000 ký tự.
    - Kiểm tra tính hợp lệ của buổi học và hạn 48 giờ.
    - Chống gửi lặp nếu đang có đơn pending cho cùng buổi học.
    """
    student = _resolve_student_for_user(user_id)
    student_id = student["id"]

    if not isinstance(payload, dict):
        raise AbsenceServiceError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không hợp lệ.")

    schedule_id = payload.get("schedule_id")
    if not schedule_id or not isinstance(schedule_id, str) or not schedule_id.strip():
        raise AbsenceServiceError("SCHEDULE_ID_REQUIRED", "Vui lòng chọn buổi học cần xin phép vắng.")
    schedule_id = schedule_id.strip()

    raw_reason = payload.get("reason")
    if raw_reason is None or not isinstance(raw_reason, str) or not raw_reason.strip():
        raise AbsenceServiceError("REASON_REQUIRED", "Vui lòng nhập lý do xin phép vắng.")

    reason = raw_reason.strip()
    if len(reason) < 5:
        raise AbsenceServiceError("REASON_TOO_SHORT", "Lý do xin phép vắng phải có ít nhất 5 ký tự.")
    if len(reason) > 1000:
        raise AbsenceServiceError("REASON_TOO_LONG", "Lý do xin phép vắng không được vượt quá 1000 ký tự.")

    # Kiểm tra buổi học hợp lệ
    is_eligible, err_reason, sched_info = absence_request_repository.check_student_session_eligibility(
        student_id, schedule_id
    )
    if not is_eligible:
        raise SessionNotEligibleError(err_reason)

    # Chống gửi lặp nếu đã có đơn pending
    pending_req = absence_request_repository.get_pending_absence_request(student_id, schedule_id)
    if pending_req:
        raise DuplicatePendingRequestError()

    # Tạo bản ghi đơn
    created = absence_request_repository.create_absence_request_record(
        schedule_id=schedule_id,
        student_id=student_id,
        reason=reason,
    )

    # Bổ sung thông tin buổi học và học viên để response đầy đủ
    created["session_number"] = sched_info.get("session_number")
    created["topic"] = sched_info.get("topic")
    created["learning_date"] = sched_info.get("learning_date_str")
    created["class_code"] = sched_info.get("class_code")
    created["subject_name"] = sched_info.get("subject_name")
    created["subject_code"] = sched_info.get("subject_code")
    created["student_code"] = student.get("student_code")
    created["student_name"] = student.get("full_name")

    return created


def list_my_absence_requests_service(
    user_id: str,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Lấy danh sách đơn xin phép vắng của chính học viên đang đăng nhập.
    """
    student = _resolve_student_for_user(user_id)
    items, total = absence_request_repository.list_student_absence_requests(
        student_id=student["id"],
        status_filter=status_filter,
        search_query=search_query,
        page=page,
        limit=limit,
    )

    limit_val = min(max(int(limit), 1), 20)
    page_val = max(int(page), 1)
    total_pages = max(1, (total + limit_val - 1) // limit_val) if total > 0 else 1

    return {
        "items": items,
        "pagination": {
            "page": page_val,
            "limit": limit_val,
            "total_items": total,
            "total_pages": total_pages,
        },
    }


def get_absence_request_detail_service(
    request_id: str,
    current_user_id: str,
    current_user_roles: list[str],
) -> dict[str, Any]:
    """
    Lấy chi tiết đơn xin phép vắng có kiểm tra quyền truy cập.
    - Học viên: chỉ xem đơn của chính mình.
    - Giảng viên / Quản lý đào tạo: xem đơn trong thẩm quyền.
    """
    req = absence_request_repository.get_absence_request_by_id(request_id)
    if not req:
        raise RequestNotFoundError()

    normalized_roles = [r.lower().strip() for r in current_user_roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles
    is_trainee = "trainee" in normalized_roles

    # Nếu là quản lý đào tạo -> toàn quyền xem
    if is_training_manager:
        return req

    # Nếu là học viên -> kiểm tra owner
    student = class_schedule_repository.get_student_by_user_id(current_user_id)
    if student and student["id"] == req["student_id"]:
        return req

    # Nếu là giảng viên -> kiểm tra có phụ trách buổi học không
    if is_trainer:
        from app.repositories import attendance_repository
        if attendance_repository.is_trainer_assigned_to_session(current_user_id, req["schedule_id"]):
            return req

    raise ForbiddenAbsenceAccessError()
