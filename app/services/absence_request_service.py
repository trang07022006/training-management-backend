"""
Service xử lý logic nghiệp vụ Đơn xin phép vắng (SCRUM-255).
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

import io
import os
from pathlib import Path
from flask import current_app

from app.config.absence_attachment_config import (
    ATTACHMENT_MAX_FILE_SIZE,
    ATTACHMENT_UPLOAD_FOLDER,
    AttachmentValidationError,
    is_safe_attachment_path,
    validate_attachment_content,
)
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


class AttachmentNotFoundError(AbsenceServiceError):
    def __init__(self, message: str = "Không tìm thấy tệp minh chứng."):
        super().__init__("ATTACHMENT_NOT_FOUND", message, status_code=404)


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
    file_storages: Optional[list] = None,
) -> dict[str, Any]:
    """
    Học viên nộp đơn xin phép vắng (SCRUM-255 Lát 1 & Lát 2).
    Quy tắc:
    - Bắt buộc ánh xạ học viên từ user_id session.
    - Validate schedule_id.
    - Validate reason: không rỗng, không chỉ khoảng trắng, độ dài 5..1000 ký tự.
    - Kiểm tra tính hợp lệ của buổi học và hạn 48 giờ.
    - Chống gửi lặp nếu đang có đơn pending cho cùng buổi học.
    - Xử lý minh chứng đính kèm (Lát 2):
      + Tối đa 5 tệp, <= 5MB/tệp, định dạng JPG/JPEG/PNG/WEBP/PDF hợp lệ
      + Lưu tệp an toàn bằng UUID ngẫu nhiên
      + Không để tệp mồ côi nếu tạo đơn thất bại (rollback cleanup disk)
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

    # Xử lý tệp minh chứng đính kèm (Lát 2)
    validated_attachments = []
    written_disk_paths = []

    try:
        if file_storages:
            # Lọc bỏ các storage rỗng
            valid_files = [f for f in file_storages if f and getattr(f, "filename", None)]
            if len(valid_files) > 5:
                raise AbsenceServiceError("TOO_MANY_ATTACHMENTS", "Số lượng tệp minh chứng tối đa là 5 tệp.")

            if valid_files:
                upload_folder_str = (
                    current_app.config.get("ABSENCE_ATTACHMENT_UPLOAD_FOLDER", ATTACHMENT_UPLOAD_FOLDER)
                    if current_app
                    else ATTACHMENT_UPLOAD_FOLDER
                )
                upload_folder = Path(upload_folder_str).resolve()
                upload_folder.mkdir(parents=True, exist_ok=True)

                for f in valid_files:
                    f.seek(0)
                    file_bytes = f.read()

                    try:
                        clean_name, mime_type, file_size, internal_name = validate_attachment_content(
                            f.filename, file_bytes
                        )
                    except AttachmentValidationError as err:
                        raise AbsenceServiceError(err.code, err.message, err.status_code)

                    target_path = (upload_folder / internal_name).resolve()
                    if not is_safe_attachment_path(str(upload_folder), str(target_path)):
                        raise AbsenceServiceError("INVALID_PATH", "Đường dẫn tệp minh chứng không an toàn.")

                    target_path.write_bytes(file_bytes)
                    written_disk_paths.append(target_path)

                    validated_attachments.append({
                        "file_name": clean_name,
                        "file_path": f"absence_attachments/{internal_name}",
                        "file_size": file_size,
                        "mime_type": mime_type,
                    })

        # Tạo bản ghi đơn trong cơ sở dữ liệu
        created = absence_request_repository.create_absence_request_record(
            schedule_id=schedule_id,
            student_id=student_id,
            reason=reason,
            attachments=validated_attachments,
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

    except Exception:
        # Cơ chế dọn dẹp an toàn chống tệp mồ côi khi tạo đơn thất bại
        for p in written_disk_paths:
            try:
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception as cleanup_err:
                logger.warning(f"Không thể xóa tệp minh chứng dở dang {p}: {cleanup_err}")
        raise


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


def get_attachment_file_service(
    request_id: str,
    attachment_id: str,
    current_user_id: str,
    current_user_roles: list[str],
) -> tuple[Path, str, str]:
    """
    Truy vấn và xác thực quyền tải/mở tệp minh chứng (SCRUM-255 Lát 2).
    - Kiểm tra sự tồn tại của tệp đính kèm trong đơn.
    - Kiểm soát quyền: Học viên chủ đơn, Giảng viên phụ trách buổi học, hoặc Quản lý đào tạo.
    - Ngăn chặn triệt để Path Traversal và rò rỉ URL công khai không phân quyền.
    - Trả về: (file_path_on_disk, mime_type, original_file_name)
    """
    att = absence_request_repository.get_attachment_by_id(attachment_id)
    if not att or att["request_id"] != request_id:
        raise AttachmentNotFoundError()

    # Kiểm tra quyền truy cập đơn
    get_absence_request_detail_service(
        request_id=request_id,
        current_user_id=current_user_id,
        current_user_roles=current_user_roles,
    )

    # Giải quyết đường dẫn file trên đĩa
    raw_path = att["file_path"].replace("\\", "/").strip()
    if raw_path.startswith("absence_attachments/"):
        internal_name = raw_path[len("absence_attachments/"):]
    else:
        internal_name = Path(raw_path).name

    upload_folder_str = (
        current_app.config.get("ABSENCE_ATTACHMENT_UPLOAD_FOLDER", ATTACHMENT_UPLOAD_FOLDER)
        if current_app
        else ATTACHMENT_UPLOAD_FOLDER
    )
    upload_folder = Path(upload_folder_str).resolve()
    target_file = (upload_folder / internal_name).resolve()

    if not is_safe_attachment_path(str(upload_folder), str(target_file)) or not target_file.is_file():
        raise AbsenceServiceError("FILE_NOT_FOUND_ON_DISK", "Tệp minh chứng không tồn tại trên hệ thống lưu trữ.", status_code=404)

    return target_file, att["mime_type"], att["file_name"]


def list_absence_requests_for_reviewer_service(
    user_id: str,
    roles: list[str],
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    schedule_id: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Lấy danh sách đơn xin phép vắng dành cho Giảng viên hoặc Quản lý đào tạo (SCRUM-255 Lát 3).
    """
    normalized_roles = [r.lower().strip() for r in roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles

    if not is_training_manager and not is_trainer:
        raise ForbiddenAbsenceAccessError("Bạn không có quyền xem danh sách đơn xin phép vắng của lớp/buổi học.")

    items, total = absence_request_repository.list_absence_requests_for_reviewer(
        reviewer_user_id=user_id,
        is_training_manager=is_training_manager,
        status_filter=status_filter,
        search_query=search_query,
        schedule_id=schedule_id,
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


def review_absence_request_service(
    request_id: str,
    reviewer_user_id: str,
    reviewer_roles: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Giảng viên hoặc Quản lý đào tạo xem xét, phê duyệt hoặc từ chối đơn (SCRUM-255 Lát 3).
    - Thẩm quyền:
      + Quản lý đào tạo: được phép duyệt thay.
      + Giảng viên: chỉ được duyệt các đơn thuộc buổi học mình phụ trách.
      + Trợ giảng / Admin thuần túy / Học viên: bị chặn (403).
    - Kiểm tra payload:
      + action bắt buộc: 'approve' hoặc 'reject'
      + rejection_reason bắt buộc khi reject (3-1000 ký tự)
    - Xử lý nguyên tử:
      + Chặn duyệt nếu học viên đã có mặt hoặc đi muộn.
      + Cập nhật điểm danh 'excused' khi duyệt, ghi audit log liên kết đơn.
      + Không bật attendance_checked trên class_schedules buổi tương lai.
    """
    normalized_roles = [r.lower().strip() for r in reviewer_roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles

    if not is_training_manager and not is_trainer:
        raise ForbiddenAbsenceAccessError("Bạn không có quyền xem xét, phê duyệt hoặc từ chối đơn xin phép vắng.")

    # Kiểm tra sự tồn tại của đơn
    req = absence_request_repository.get_absence_request_by_id(request_id)
    if not req:
        raise RequestNotFoundError()

    # Kiểm tra phân công đối với Giảng viên
    if is_trainer and not is_training_manager:
        from app.repositories import attendance_repository
        if not attendance_repository.is_trainer_assigned_to_session(reviewer_user_id, req["schedule_id"]):
            raise ForbiddenAbsenceAccessError("Bạn không được phân công phụ trách buổi học này, không thể duyệt đơn.")

    if not isinstance(payload, dict):
        raise AbsenceServiceError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không hợp lệ.")

    action = payload.get("action")
    if not action or not isinstance(action, str) or action.strip().lower() not in ("approve", "reject"):
        raise AbsenceServiceError("INVALID_ACTION", "Hành động xem xét không hợp lệ. Chỉ chấp nhận 'approve' hoặc 'reject'.")

    action_clean = action.strip().lower()
    rejection_reason = payload.get("rejection_reason")

    if action_clean == "reject":
        if not rejection_reason or not isinstance(rejection_reason, str) or not rejection_reason.strip():
            raise AbsenceServiceError("REJECTION_REASON_REQUIRED", "Vui lòng nhập lý do từ chối đơn xin phép vắng.")
        clean_reason = rejection_reason.strip()
        if len(clean_reason) < 3:
            raise AbsenceServiceError("REJECTION_REASON_TOO_SHORT", "Lý do từ chối phải có ít nhất 3 ký tự.")
        if len(clean_reason) > 1000:
            raise AbsenceServiceError("REJECTION_REASON_TOO_LONG", "Lý do từ chối không được vượt quá 1000 ký tự.")
        rejection_reason = clean_reason
    else:
        rejection_reason = None

    try:
        updated_req = absence_request_repository.review_absence_request_record(
            request_id=request_id,
            reviewer_user_id=reviewer_user_id,
            action=action_clean,
            rejection_reason=rejection_reason,
        )
        return updated_req
    except RuntimeError as err:
        err_msg = str(err)
        if "REQUEST_NOT_FOUND" in err_msg:
            raise RequestNotFoundError()
        if "REQUEST_ALREADY_REVIEWED" in err_msg:
            raise AbsenceServiceError("REQUEST_ALREADY_REVIEWED", "Đơn xin phép vắng này đã được xử lý trước đó.")
        if "ATTENDANCE_CONFLICT_PRESENT_LATE" in err_msg:
            raise AbsenceServiceError(
                "ATTENDANCE_CONFLICT",
                "Học viên đã có mặt hoặc đi muộn tại buổi học này. Không thể duyệt đơn vắng có phép.",
                status_code=400,
            )
        if "SESSION_CANCELLED" in err_msg:
            raise AbsenceServiceError("SESSION_CANCELLED", "Buổi học này đã bị hủy, không thể duyệt đơn.")
        if "REJECTION_REASON_REQUIRED" in err_msg:
            raise AbsenceServiceError("REJECTION_REASON_REQUIRED", "Vui lòng nhập lý do từ chối đơn xin phép vắng.")
        raise AbsenceServiceError("REVIEW_FAILED", f"Không thể xử lý đơn: {err_msg}")


