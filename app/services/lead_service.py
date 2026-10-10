"""
Service xử lý nghiệp vụ cho Lead / Yêu cầu tư vấn công khai (SCRUM-125 - Activity A2).
Bảo đảm:
1. Xác thực dữ liệu đầu vào nghiêm ngặt (tên, số điện thoại, định dạng email, độ dài).
2. Bảo vệ trường quản trị hệ thống (không cho phép client can thiệp id, status, source, timestamps).
3. Kiểm tra tính hợp lệ và tồn tại của chương trình đào tạo quan tâm.
4. Trả về kết quả tối thiểu để bảo vệ quyền riêng tư (PII privacy).
"""

from datetime import datetime, timedelta, timezone
import math
import re
import uuid
from typing import Any

from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.repositories import lead_repository, training_program_repository, user_repository


CONSULTATION_COOLDOWN_SECONDS = 60
CONSULTATION_RATE_LIMIT_MESSAGE = (
    "Bạn đã gửi yêu cầu tư vấn gần đây. Vui lòng chờ một chút trước khi gửi lại."
)

_consultation_rate_limits: dict[str, datetime] = {}


def clear_consultation_rate_limits() -> None:
    """Xóa sạch bộ nhớ rate limit tư vấn công khai (dùng cho testing)."""
    global _consultation_rate_limits
    _consultation_rate_limits.clear()


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


class LeadRateLimitError(LeadServiceError):
    """Lỗi gửi yêu cầu tư vấn quá nhanh / spam (429 Too Many Requests)."""

    def __init__(
        self,
        code: str = "CONSULTATION_RATE_LIMITED",
        message: str = CONSULTATION_RATE_LIMIT_MESSAGE,
        retry_after_seconds: int = CONSULTATION_COOLDOWN_SECONDS,
    ):
        super().__init__(code=code, message=message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class LeadProgramNotFoundError(LeadServiceError):
    """Lỗi không tìm thấy chương trình đào tạo (404)."""

    def __init__(self, message: str = "Không tìm thấy chương trình đào tạo quan tâm."):
        super().__init__(code="PROGRAM_NOT_FOUND", message=message, status_code=404)


class LeadNotFoundError(LeadServiceError):
    """Lỗi không tìm thấy Lead (404)."""

    def __init__(self, message: str = "Không tìm thấy thông tin Lead."):
        super().__init__(code="LEAD_NOT_FOUND", message=message, status_code=404)


def _normalize_phone_key(phone: str) -> str:
    """Chuẩn hóa số điện thoại thành chuỗi ký tự số liền mạch để so sánh chống spam."""
    return re.sub(r"[\s\-\.\(\)]", "", phone.strip()).lower()


def _prune_stale_rate_limits(now: datetime) -> None:
    """Dọn dẹp các mục rate limit đã quá 10 phút khỏi bộ nhớ đệm."""
    cutoff = now - timedelta(minutes=10)
    for k in list(_consultation_rate_limits.keys()):
        val = _consultation_rate_limits[k]
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        if val < cutoff:
            del _consultation_rate_limits[k]


def _check_consultation_rate_limit(
    phone: str,
    email: str | None,
    client_ip: str | None,
    now: datetime,
) -> None:
    """
    Kiểm tra xem số điện thoại, email hoặc IP có đang trong thời gian cooldown 60s hay không (SCRUM-125).
    Kiểm tra cả 2 lớp:
    1. Lớp In-Memory: Phát hiện siêu tốc theo Phone, Email, IP.
    2. Lớp MySQL Database: Đối chiếu created_at thực tế trong bảng leads.
    """
    norm_phone = _normalize_phone_key(phone)
    norm_email = email.strip().lower() if email else None
    norm_ip = client_ip.strip() if client_ip else None

    is_testing = False
    try:
        from flask import current_app
        if current_app:
            is_testing = bool(current_app.config.get("TESTING"))
    except Exception:
        pass

    # 1. Kiểm tra bộ nhớ In-Memory
    keys_to_check: list[str] = [f"phone:{norm_phone}"]
    if norm_email:
        keys_to_check.append(f"email:{norm_email}")

    # Với IP:
    # Trong môi trường testing, chỉ kiểm tra IP nếu IP đó khác localhost/127.0.0.1
    # hoặc được chỉ định rõ qua header X-Forwarded-For để tránh xung đột giữa các test case độc lập.
    # Trong môi trường thực tế (dev/production), luôn kiểm tra IP.
    if norm_ip:
        if not is_testing or norm_ip not in ("127.0.0.1", "localhost", "testclient"):
            keys_to_check.append(f"ip:{norm_ip}")

    for k in keys_to_check:
        prev_time = _consultation_rate_limits.get(k)
        if prev_time is not None:
            if prev_time.tzinfo is None:
                prev_time = prev_time.replace(tzinfo=timezone.utc)
            elapsed = (now - prev_time).total_seconds()
            if elapsed < CONSULTATION_COOLDOWN_SECONDS:
                remaining = max(1, int(CONSULTATION_COOLDOWN_SECONDS - elapsed))
                raise LeadRateLimitError(
                    code="CONSULTATION_RATE_LIMITED",
                    message=CONSULTATION_RATE_LIMIT_MESSAGE,
                    retry_after_seconds=remaining,
                )

    # 2. Kiểm tra trong cơ sở dữ liệu MySQL (Database check)
    since = now - timedelta(seconds=CONSULTATION_COOLDOWN_SECONDS)
    recent_lead = lead_repository.get_recent_lead_by_phone_or_email(
        phone=phone,
        email=email,
        since=since,
    )
    if recent_lead is not None and recent_lead.created_at is not None:
        c_time = recent_lead.created_at
        if c_time.tzinfo is None:
            c_time = c_time.replace(tzinfo=timezone.utc)
        elapsed = (now - c_time).total_seconds()
        if elapsed < CONSULTATION_COOLDOWN_SECONDS:
            remaining = max(1, int(CONSULTATION_COOLDOWN_SECONDS - elapsed))
            raise LeadRateLimitError(
                code="CONSULTATION_RATE_LIMITED",
                message=CONSULTATION_RATE_LIMIT_MESSAGE,
                retry_after_seconds=remaining,
            )


ALLOWED_SUBMISSION_FIELDS = {
    "full_name",
    "phone",
    "email",
    "interested_program_id",
    "message",
}


def create_public_consultation_service(
    payload: dict[str, Any],
    client_ip: str | None = None,
) -> dict[str, Any]:
    """
    Xử lý tạo yêu cầu tư vấn công khai từ form website (SCRUM-125 - Activity A2/A4).
    - Không yêu cầu đăng nhập.
    - Validate nghiêm ngặt full_name, phone, email, message, interested_program_id.
    - Chặn các trường lạ và trường can thiệp hệ thống.
    - Chuẩn hóa khoảng trắng, line endings, chữ thường cho email.
    - Chống spam / rate limit theo Phone, Email, IP (cooldown 60s).
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

    now = datetime.now(timezone.utc)

    # 7. Kiểm tra chống spam / rate limit (SCRUM-125)
    _check_consultation_rate_limit(
        phone=phone,
        email=email,
        client_ip=client_ip,
        now=now,
    )

    # 8. Khởi tạo thực thể Lead an toàn
    new_lead = Lead(
        id=str(uuid.uuid4()),
        full_name=full_name,
        phone=phone,
        email=email,
        interested_program_id=interested_program_id,
        message=message,
        source=LEAD_SOURCE_PUBLIC_FORM,
        status=LEAD_STATUS_NEW,
        created_at=now,
        updated_at=now,
    )

    created_lead = lead_repository.insert_lead(new_lead)

    # 9. Ghi nhận thời điểm gửi thành công vào bộ nhớ rate limit
    norm_phone = _normalize_phone_key(phone)
    _consultation_rate_limits[f"phone:{norm_phone}"] = now
    if email:
        _consultation_rate_limits[f"email:{email.strip().lower()}"] = now
    if client_ip:
        _consultation_rate_limits[f"ip:{client_ip.strip()}"] = now

    _prune_stale_rate_limits(now)

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


def _parse_iso_date(
    raw_val: Any, param_name: str, end_of_day: bool = False
) -> datetime | None:
    """Chuyển đổi chuỗi ngày ISO thành đối tượng datetime UTC có kiểm tra an toàn."""
    if raw_val is None:
        return None
    if not isinstance(raw_val, str) or not raw_val.strip():
        return None

    cleaned = raw_val.strip()
    try:
        if len(cleaned) == 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
            d = datetime.strptime(cleaned, "%Y-%m-%d")
            if end_of_day:
                d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
            return d.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        raise LeadValidationError(
            "INVALID_PARAMS",
            f"Định dạng ngày '{param_name}' không hợp lệ. Vui lòng sử dụng định dạng ISO (YYYY-MM-DD hoặc ISO-8601).",
        )


def get_leads_service(
    page_raw: Any = 1,
    page_size_raw: Any = 20,
    search: str | None = None,
    status: str | None = None,
    interested_program_id: str | None = None,
    assigned_to_user_id: str | None = None,
    source: str | None = None,
    date_from_raw: str | None = None,
    date_to_raw: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "DESC",
) -> dict[str, Any]:
    """
    Lấy danh sách Lead cho người dùng nội bộ có thẩm quyền (SCRUM-126/127/128).
    - Hỗ trợ phân trang: page >= 1, page_size từ 1 đến 100.
    - Tìm kiếm: search theo họ tên, điện thoại, email.
    - Bộ lọc: status, interested_program_id, assigned_to_user_id, source, date_from, date_to.
    - Sắp xếp: sort_by whitelist, sort_order ASC/DESC.
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

    # Validate search length
    clean_search: str | None = None
    if search is not None:
        if not isinstance(search, str):
            raise LeadValidationError("INVALID_PARAMS", "Từ khóa tìm kiếm phải là chuỗi ký tự.")
        clean_search = search.strip()
        if len(clean_search) > 100:
            raise LeadValidationError("INVALID_PARAMS", "Từ khóa tìm kiếm không được vượt quá 100 ký tự.")

    # Validate status filter
    clean_status: str | None = None
    if status is not None:
        if not isinstance(status, str):
            raise LeadValidationError("INVALID_PARAMS", "Trạng thái lọc phải là chuỗi ký tự.")
        clean_status = status.strip().lower()
        from app.models.lead import VALID_LEAD_STATUSES

        if clean_status and clean_status not in VALID_LEAD_STATUSES:
            raise LeadValidationError(
                "INVALID_PARAMS",
                f"Trạng thái '{clean_status}' không hợp lệ. Các trạng thái hợp lệ: {', '.join(sorted(VALID_LEAD_STATUSES))}.",
            )

    # Validate interested_program_id UUID
    clean_program_id: str | None = None
    if interested_program_id is not None:
        if not isinstance(interested_program_id, str):
            raise LeadValidationError("INVALID_PARAMS", "Mã chương trình đào tạo phải là chuỗi UUID.")
        clean_program_id = interested_program_id.strip()
        if clean_program_id and not is_valid_uuid(clean_program_id):
            raise LeadValidationError("INVALID_PARAMS", "Mã chương trình quan tâm không hợp lệ (phải là UUID).")

    # Validate assigned_to_user_id UUID or 'unassigned'
    clean_assignee_id: str | None = None
    if assigned_to_user_id is not None:
        if not isinstance(assigned_to_user_id, str):
            raise LeadValidationError("INVALID_PARAMS", "Mã người phụ trách phải là chuỗi ký tự.")
        clean_assignee_id = assigned_to_user_id.strip()
        if clean_assignee_id and clean_assignee_id.lower() != "unassigned":
            if not is_valid_uuid(clean_assignee_id):
                raise LeadValidationError("INVALID_PARAMS", "Mã người phụ trách không hợp lệ (phải là UUID).")

    # Validate source
    clean_source: str | None = None
    if source is not None:
        if not isinstance(source, str):
            raise LeadValidationError("INVALID_PARAMS", "Nguồn tiếp nhận phải là chuỗi ký tự.")
        clean_source = source.strip()

    # Validate date range
    date_from = _parse_iso_date(date_from_raw, "date_from", end_of_day=False)
    date_to = _parse_iso_date(date_to_raw, "date_to", end_of_day=True)

    if date_from and date_to and date_from > date_to:
        raise LeadValidationError(
            "INVALID_PARAMS",
            "Ngày bắt đầu 'date_from' không được lớn hơn ngày kết thúc 'date_to'.",
        )

    # Validate sort_by
    clean_sort_by = (sort_by or "created_at").strip().lower()
    if clean_sort_by not in lead_repository.SAFE_LEAD_SORT_COLUMNS:
        raise LeadValidationError(
            "INVALID_PARAMS",
            f"Trường sắp xếp '{clean_sort_by}' không hợp lệ. Các trường hợp lệ: {', '.join(sorted(lead_repository.SAFE_LEAD_SORT_COLUMNS.keys()))}.",
        )

    # Validate sort_order
    clean_sort_order = (sort_order or "DESC").strip().upper()
    if clean_sort_order not in {"ASC", "DESC"}:
        raise LeadValidationError(
            "INVALID_PARAMS",
            "Thứ tự sắp xếp 'sort_order' chỉ chấp nhận 'ASC' hoặc 'DESC'.",
        )

    leads, total = lead_repository.list_leads(
        page=page,
        page_size=page_size,
        search=clean_search,
        status=clean_status,
        interested_program_id=clean_program_id,
        assigned_to_user_id=clean_assignee_id,
        source=clean_source,
        date_from=date_from,
        date_to=date_to,
        sort_by=clean_sort_by,
        sort_order=clean_sort_order,
    )
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


def assign_lead_service(lead_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """
    Phân công hoặc gỡ phân công Lead (SCRUM-127 - Activity A2/A3).
    - Kiểm tra ID Lead hợp lệ và Lead tồn tại trong cơ sở dữ liệu.
    - Chấp nhận:
        {"user_id": "<uuid>"} -> phân công nhân sự
        {"user_id": null}     -> gỡ phân công
    - Nếu payload là None (khi gọi từ DELETE endpoint) -> coi như gỡ phân công.
    - Kiểm tra user_id hợp lệ: phải tồn tại, đang hoạt động (active), và có vai trò phù hợp (admin, trainer).
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    existing_lead = lead_repository.get_lead_by_id(lead_id)
    if not existing_lead:
        raise LeadNotFoundError()

    target_user_id: str | None = None

    if payload is not None:
        if not isinstance(payload, dict):
            raise LeadValidationError("INVALID_JSON", "Dữ liệu yêu cầu phải là đối tượng JSON.")

        disallowed_fields = set(payload.keys()) - {"user_id"}
        if disallowed_fields:
            raise LeadValidationError(
                "INVALID_PARAMS",
                f"Không được phép truyền các trường ngoài 'user_id': {', '.join(sorted(disallowed_fields))}.",
            )

        raw_user_id = payload.get("user_id")
        if raw_user_id is not None:
            if not isinstance(raw_user_id, str):
                raise LeadValidationError("INVALID_PARAMS", "Mã người dùng không hợp lệ.")
            target_user_id = raw_user_id.strip()
            if not is_valid_uuid(target_user_id):
                raise LeadValidationError("INVALID_PARAMS", "Mã người dùng không hợp lệ.")

            user = user_repository.get_user_by_id(target_user_id)
            if not user:
                raise LeadServiceError("USER_NOT_FOUND", "Người dùng được phân công không tồn tại.", status_code=404)

            if user.status != "active":
                raise LeadValidationError("INACTIVE_USER", "Người dùng không còn hoạt động, không thể nhận phân công.")

            if user.role not in {"admin", "trainer"}:
                raise LeadValidationError("INVALID_ASSIGNEE", "Chỉ có thể phân công cho Quản trị viên hoặc Giảng viên.")

    now = datetime.now(timezone.utc)
    updated = lead_repository.assign_lead(
        lead_id=lead_id,
        assigned_to_user_id=target_user_id,
        assigned_at=now if target_user_id else None,
        updated_at=now,
    )
    if not updated:
        raise LeadNotFoundError()

    msg = "Phân công Lead thành công." if target_user_id else "Gỡ phân công Lead thành công."
    return {
        "status": "success",
        "message": msg,
        "data": updated.to_dict(),
    }


def get_assignable_users_service() -> list[dict[str, Any]]:
    """
    Lấy danh sách người dùng có thể nhận phân công Lead (SCRUM-127 - Activity A4).
    Đảm bảo 100% users trả về có UUID hợp lệ để phân công không bị lỗi INVALID_PARAMS.
    """
    users = lead_repository.get_assignable_lead_users()
    return [u for u in users if is_valid_uuid(str(u.get("id", "")))]



