"""
Service xử lý nghiệp vụ cho Lead / Yêu cầu tư vấn công khai (SCRUM-125 - Activity A2).
Bảo đảm:
1. Xác thực dữ liệu đầu vào nghiêm ngặt (tên, số điện thoại, định dạng email, độ dài).
2. Bảo vệ trường quản trị hệ thống (không cho phép client can thiệp id, status, source, timestamps).
3. Kiểm tra tính hợp lệ và tồn tại của chương trình đào tạo quan tâm.
4. Trả về kết quả tối thiểu để bảo vệ quyền riêng tư (PII privacy).
"""

from datetime import datetime, timezone
import math
import re
import uuid
from typing import Any

from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.repositories import lead_repository, training_program_repository


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")
PHONE_CHARS_REGEX = re.compile(r"^\+?[0-9\s\-\.\(\)]{6,30}$")

SYSTEM_CONTROLLED_FIELDS = {
    "id",
    "status",
    "source",
    "assigned_to",
    "created_at",
    "updated_at",
    "owner",
    "created_by",
}


def is_valid_uuid(val: str) -> bool:
    """Kiểm tra chuỗi có đúng định dạng UUID hay không."""
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        parsed = uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError, AttributeError):
        return False


class LeadServiceError(Exception):
    """Ngoại lệ cơ sở cho các lỗi nghiệp vụ của Lead / Tư vấn."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class LeadValidationError(LeadServiceError):
    """Lỗi dữ liệu đầu vào không hợp lệ (400)."""

    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, status_code=400)


class LeadProgramNotFoundError(LeadServiceError):
    """Lỗi không tìm thấy chương trình đào tạo (404)."""

    def __init__(self, message: str = "Không tìm thấy chương trình đào tạo quan tâm."):
        super().__init__(code="PROGRAM_NOT_FOUND", message=message, status_code=404)


class LeadNotFoundError(LeadServiceError):
    """Lỗi không tìm thấy Lead (404)."""

    def __init__(self, message: str = "Không tìm thấy thông tin Lead."):
        super().__init__(code="LEAD_NOT_FOUND", message=message, status_code=404)


ALLOWED_SUBMISSION_FIELDS = {
    "full_name",
    "phone",
    "email",
    "interested_program_id",
    "message",
}


def create_public_consultation_service(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Xử lý tạo yêu cầu tư vấn công khai từ form website (SCRUM-125 - Activity A2/A4).
    - Không yêu cầu đăng nhập.
    - Validate nghiêm ngặt full_name, phone, email, message, interested_program_id.
    - Chặn các trường lạ và trường can thiệp hệ thống.
    - Chuẩn hóa khoảng trắng, line endings, chữ thường cho email.
    """
    if not isinstance(payload, dict):
        raise LeadValidationError("INVALID_JSON", "Dữ liệu yêu cầu phải là đối tượng JSON.")

    # 1. Chặn các trường không thuộc danh sách cho phép (unknown / system-controlled)
    unexpected = set(payload.keys()) - ALLOWED_SUBMISSION_FIELDS
    if unexpected:
        raise LeadValidationError(
            "INVALID_PARAMS",
            f"Không được phép gửi các trường không hợp lệ: {', '.join(sorted(unexpected))}.",
        )

    # 2. Validate Họ và tên (full_name) - bắt buộc
    raw_name = payload.get("full_name")
    if raw_name is None:
        raise LeadValidationError("NAME_REQUIRED", "Họ và tên là bắt buộc.")
    if not isinstance(raw_name, str):
        raise LeadValidationError("INVALID_PARAMS", "Họ và tên phải là chuỗi văn bản.")
    full_name = raw_name.strip()
    if not full_name:
        raise LeadValidationError("NAME_REQUIRED", "Họ và tên là bắt buộc.")
    if len(full_name) > 255:
        raise LeadValidationError("INVALID_PARAMS", "Họ và tên không được vượt quá 255 ký tự.")

    # 3. Validate Số điện thoại (phone) - bắt buộc
    raw_phone = payload.get("phone")
    if raw_phone is None:
        raise LeadValidationError("PHONE_REQUIRED", "Số điện thoại là bắt buộc.")
    if not isinstance(raw_phone, str):
        raise LeadValidationError("INVALID_PARAMS", "Số điện thoại phải là chuỗi văn bản.")
    phone = raw_phone.strip()
    if not phone:
        raise LeadValidationError("PHONE_REQUIRED", "Số điện thoại là bắt buộc.")
    if len(phone) > 30 or not PHONE_CHARS_REGEX.match(phone):
        raise LeadValidationError("INVALID_PARAMS", "Số điện thoại không đúng định dạng hợp lệ.")

    # 4. Validate Email (tùy chọn)
    raw_email = payload.get("email")
    email = None
    if raw_email is not None:
        if not isinstance(raw_email, str):
            raise LeadValidationError("INVALID_EMAIL", "Định dạng email không hợp lệ.")
        trimmed_email = raw_email.strip().lower()
        if trimmed_email:
            if len(trimmed_email) > 255 or not EMAIL_REGEX.match(trimmed_email):
                raise LeadValidationError("INVALID_EMAIL", "Định dạng email không hợp lệ.")
            email = trimmed_email

    # 5. Validate Chương trình đào tạo quan tâm (tùy chọn)
    raw_program_id = payload.get("interested_program_id")
    interested_program_id = None
    if raw_program_id is not None:
        if not isinstance(raw_program_id, str):
            raise LeadValidationError("INVALID_PARAMS", "Mã chương trình đào tạo không hợp lệ.")
        trimmed_pid = raw_program_id.strip()
        if trimmed_pid:
            if not is_valid_uuid(trimmed_pid):
                raise LeadValidationError("INVALID_PARAMS", "Mã chương trình đào tạo phải là UUID hợp lệ.")
            # Kiểm tra chương trình tồn tại
            prog = training_program_repository.get_training_program_by_id(trimmed_pid)
            if not prog:
                raise LeadProgramNotFoundError()
            if prog.status != "active":
                raise LeadValidationError(
                    "INVALID_PROGRAM",
                    "Chương trình đào tạo này hiện không mở đăng ký tư vấn.",
                )
            interested_program_id = trimmed_pid

    # 6. Validate Nội dung cần tư vấn (message - tùy chọn)
    raw_message = payload.get("message")
    message = None
    if raw_message is not None:
        if not isinstance(raw_message, str):
            raise LeadValidationError("INVALID_PARAMS", "Nội dung tin nhắn không hợp lệ.")
        normalized_msg = raw_message.replace("\r\n", "\n").replace("\r", "\n").strip()
        if normalized_msg:
            if len(normalized_msg) > 5000:
                raise LeadValidationError("INVALID_PARAMS", "Nội dung tư vấn không được vượt quá 5000 ký tự.")
            message = normalized_msg

    # 7. Khởi tạo thực thể Lead an toàn
    new_lead = Lead(
        id=str(uuid.uuid4()),
        full_name=full_name,
        phone=phone,
        email=email,
        interested_program_id=interested_program_id,
        message=message,
        source=LEAD_SOURCE_PUBLIC_FORM,
        status=LEAD_STATUS_NEW,
    )

    created_lead = lead_repository.insert_lead(new_lead)

    return {
        "status": "success",
        "message": "Yêu cầu tư vấn của bạn đã được ghi nhận.",
        "data": created_lead.to_public_dict(),
    }


def get_public_training_programs_service() -> list[dict[str, Any]]:
    """
    Lấy danh sách các chương trình đào tạo đang active cho form tư vấn công khai (SCRUM-125 - Activity A3).
    Chỉ trả về id, code, name, description.
    """
    return training_program_repository.get_public_active_training_programs()


def get_leads_service(page_raw: Any = 1, page_size_raw: Any = 20) -> dict[str, Any]:
    """
    Lấy danh sách Lead cho người dùng nội bộ có thẩm quyền (SCRUM-126 - Activity A2).
    - Hỗ trợ phân trang: page >= 1, page_size từ 1 đến 100.
    - Sắp xếp mặc định: created_at DESC.
    """
    try:
        page = int(page_raw)
        if page < 1:
            raise ValueError()
    except (TypeError, ValueError):
        raise LeadValidationError(
            "INVALID_PARAMS",
            "Số trang 'page' phải là số nguyên dương lớn hơn hoặc bằng 1.",
        )

    try:
        page_size = int(page_size_raw)
        if page_size < 1 or page_size > 100:
            raise ValueError()
    except (TypeError, ValueError):
        raise LeadValidationError(
            "INVALID_PARAMS",
            "Số lượng phần tử trên trang 'page_size' phải từ 1 đến 100.",
        )

    leads, total = lead_repository.list_leads(page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return {
        "items": [lead.to_dict() for lead in leads],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_lead_by_id_service(lead_id: str) -> dict[str, Any]:
    """
    Lấy chi tiết một Lead theo ID (SCRUM-126 - Activity A2).
    - Kiểm tra định dạng UUID 36 ký tự.
    - Ném LeadNotFoundError (404) nếu không tìm thấy.
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    lead = lead_repository.get_lead_by_id(lead_id)
    if not lead:
        raise LeadNotFoundError()

    return lead.to_dict()


def update_lead_status_service(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Cập nhật trạng thái của một Lead (SCRUM-126 - Activity A3).
    - Chỉ cho phép sửa trường 'status'.
    - Chặn mọi nỗ lực can thiệp các trường hệ thống (id, created_at, source, v.v.).
    - Xác thực trạng thái nằm trong danh mục VALID_LEAD_STATUSES.
    - Cập nhật thời gian updated_at theo UTC server.
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    if not isinstance(payload, dict):
        raise LeadValidationError("INVALID_JSON", "Dữ liệu yêu cầu phải là đối tượng JSON.")

    disallowed_fields = set(payload.keys()) - {"status"}
    if disallowed_fields:
        raise LeadValidationError(
            "INVALID_PARAMS",
            f"Không được phép sửa đổi các trường: {', '.join(sorted(disallowed_fields))}. Chỉ cho phép cập nhật 'status'.",
        )

    raw_status = payload.get("status")
    if raw_status is None:
        raise LeadValidationError("STATUS_REQUIRED", "Trường 'status' là bắt buộc.")

    if not isinstance(raw_status, str):
        raise LeadValidationError("INVALID_STATUS", "Trạng thái phải là chuỗi văn bản.")

    status = raw_status.strip().lower()
    from app.models.lead import VALID_LEAD_STATUSES

    if status not in VALID_LEAD_STATUSES:
        raise LeadValidationError(
            "INVALID_STATUS",
            f"Trạng thái '{status}' không hợp lệ. Các trạng thái hợp lệ: {', '.join(sorted(VALID_LEAD_STATUSES))}.",
        )

    existing = lead_repository.get_lead_by_id(lead_id)
    if not existing:
        raise LeadNotFoundError()

    now = datetime.now(timezone.utc)
    updated = lead_repository.update_lead_status(lead_id, status, updated_at=now)
    if not updated:
        raise LeadNotFoundError()

    return {
        "status": "success",
        "message": "Cập nhật trạng thái Lead thành công.",
        "data": updated.to_dict(),
    }


