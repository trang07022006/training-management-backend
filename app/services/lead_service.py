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
    LEAD_SOURCE_DIRECT,
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    VALID_LEAD_SOURCES,
    Lead,
)
from app.repositories import (
    lead_repository,
    training_program_repository,
    user_repository,
    user_role_repository,
)


def is_user_consultant(user_id: str) -> bool:
    """
    Kiểm tra người dùng có vai trò Tư vấn tuyển sinh ('consultant') hợp lệ (SCRUM-127).
    Chỉ chấp nhận user đang active và có vai trò consultant.
    Từ chối nếu user có các vai trò khác: trainer, trainee, admin, training_manager.
    """
    if not is_valid_uuid(user_id):
        return False
    user = user_repository.get_user_by_id(user_id)
    if not user or user.status != "active":
        return False

    roles = set(user_role_repository.get_role_codes_by_user_id(user_id))
    if not roles and user.role:
        roles = {user.role}

    disallowed_roles = {"trainer", "trainee", "admin", "training_manager"}
    if roles.intersection(disallowed_roles):
        return False

    return "consultant" in roles



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


try:
    from zoneinfo import ZoneInfo
    VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    VIETNAM_TZ = timezone(timedelta(hours=7))


def _parse_iso_date(
    raw_val: Any, param_name: str, end_of_day: bool = False
) -> datetime | None:
    """
    Chuyển đổi chuỗi ngày ISO thành đối tượng datetime UTC chuẩn theo múi giờ Việt Nam (Asia/Ho_Chi_Minh).
    - Chuỗi ngày YYYY-MM-DD được hiểu là ngày lịch theo múi giờ Việt Nam (Asia/Ho_Chi_Minh):
      + date_from (start of day): 00:00:00.000000 GMT+7 -> chuyển sang UTC.
      + date_to (end of day): 23:59:59.999999 GMT+7 -> chuyển sang UTC.
    - Chuỗi ISO-8601:
      + Nếu không có múi giờ: mặc định hiểu theo Asia/Ho_Chi_Minh rồi chuyển sang UTC.
      + Nếu đã có múi giờ: chuyển sang UTC.
    """
    if raw_val is None:
        return None
    if not isinstance(raw_val, str) or not raw_val.strip():
        return None

    cleaned = raw_val.strip()
    try:
        if len(cleaned) == 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
            d = datetime.strptime(cleaned, "%Y-%m-%d")
            if end_of_day:
                d = d.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=VIETNAM_TZ)
            else:
                d = d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=VIETNAM_TZ)
            return d.astimezone(timezone.utc)
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VIETNAM_TZ)
        return dt.astimezone(timezone.utc)
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
    actor_id: str | None = None,
) -> dict[str, Any]:
    """
    Lấy danh sách Lead cho người dùng nội bộ có thẩm quyền (SCRUM-126/127/128).
    - Hỗ trợ phân trang: page >= 1, page_size từ 1 đến 100.
    - Tìm kiếm: search theo họ tên, điện thoại, email.
    - Bộ lọc: status, interested_program_id, assigned_to_user_id, source, date_from, date_to.
    - Sắp xếp: sort_by whitelist, sort_order ASC/DESC.
    - Phân quyền dữ liệu (SCRUM-127): Tư vấn viên chỉ thấy Lead được giao cho mình.
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

    # Phân quyền dữ liệu tại Backend (SCRUM-127 - Activity A11):
    # Role Tư vấn tuyển sinh chỉ nhìn thấy Lead được giao cho mình (assignee_id = current_user.id).
    # Quản lý đào tạo (training_manager) và Quản trị viên (admin) xem toàn bộ Lead.
    if actor_id:
        actor_roles = set(user_role_repository.get_role_codes_by_user_id(actor_id))
        actor_user = user_repository.get_user_by_id(actor_id)
        if actor_user and actor_user.role:
            actor_roles.add(actor_user.role)

        is_privileged = bool(actor_roles.intersection({"admin", "training_manager"}))
        is_consultant = "consultant" in actor_roles

        if is_consultant and not is_privileged:
            clean_assignee_id = actor_id

    # Validate source
    clean_source: str | None = None
    if source is not None:
        if not isinstance(source, str):
            raise LeadValidationError("INVALID_PARAMS", "Nguồn tiếp nhận phải là chuỗi ký tự.")
        clean_source = source.strip()
        if clean_source and clean_source not in VALID_LEAD_SOURCES:
            raise LeadValidationError(
                "INVALID_PARAMS",
                f"Nguồn tiếp nhận '{clean_source}' không hợp lệ. Các nguồn hợp lệ: {', '.join(sorted(VALID_LEAD_SOURCES))}.",
            )
        if not clean_source:
            clean_source = None

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


def get_lead_by_id_service(lead_id: str, actor_id: str | None = None) -> dict[str, Any]:
    """
    Lấy chi tiết một Lead theo ID (SCRUM-126/SCRUM-127).
    - Kiểm tra định dạng UUID 36 ký tự.
    - Ném LeadNotFoundError (404) nếu không tìm thấy.
    - Phân quyền: Tư vấn tuyển sinh chỉ xem Lead được phân công cho mình.
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    lead = lead_repository.get_lead_by_id(lead_id)
    if not lead:
        raise LeadNotFoundError()

    if actor_id:
        actor_roles = set(user_role_repository.get_role_codes_by_user_id(actor_id))
        actor_user = user_repository.get_user_by_id(actor_id)
        if actor_user and actor_user.role:
            actor_roles.add(actor_user.role)

        is_privileged = bool(actor_roles.intersection({"admin", "training_manager"}))
        is_consultant = "consultant" in actor_roles

        if is_consultant and not is_privileged:
            if lead.assigned_to_user_id != actor_id:
                raise LeadServiceError(
                    "FORBIDDEN",
                    "Bạn không có quyền truy cập thông tin Lead này.",
                    status_code=403,
                )

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


def assign_lead_service(
    lead_id: str,
    payload: dict[str, Any] | None,
    performed_by_user_id: str | None = None,
) -> dict[str, Any]:
    """
    Phân công hoặc gỡ phân công Lead (SCRUM-127 - Activity A2/A3).
    - Kiểm tra ID Lead hợp lệ và Lead tồn tại trong cơ sở dữ liệu.
    - Chấp nhận:
        {"user_id": "<uuid>"} -> phân công nhân sự
        {"user_id": null}     -> gỡ phân công
    - Nếu payload là None (khi gọi từ DELETE endpoint) -> coi như gỡ phân công.
    - Validate vai trò: CHỈ chấp nhận user đang active có vai trò Tư vấn tuyển sinh ('consultant').
    - Từ chối trainer, trainee, admin, user, training_manager với thông báo:
      "Chỉ có thể phân công Lead cho nhân viên Tư vấn tuyển sinh."
    - Ghi nhận lịch sử chuyển giao mỗi khi người phụ trách thay đổi.
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    existing_lead = lead_repository.get_lead_by_id(lead_id)
    if not existing_lead:
        raise LeadNotFoundError()

    target_user_id: str | None = None
    target_user = None

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

            target_user = user_repository.get_user_by_id(target_user_id)
            if not target_user:
                raise LeadServiceError("USER_NOT_FOUND", "Người dùng được phân công không tồn tại.", status_code=404)

            if target_user.status != "active":
                raise LeadValidationError("INACTIVE_USER", "Người dùng không còn hoạt động, không thể nhận phân công.")

            if not is_user_consultant(target_user_id):
                raise LeadValidationError(
                    "INVALID_ASSIGNEE",
                    "Chỉ có thể phân công Lead cho nhân viên Tư vấn tuyển sinh.",
                )

    old_assignee_id = existing_lead.assigned_to_user_id
    now = datetime.now(timezone.utc)
    updated = lead_repository.assign_lead(
        lead_id=lead_id,
        assigned_to_user_id=target_user_id,
        assigned_at=now if target_user_id else None,
        updated_at=now,
    )
    if not updated:
        raise LeadNotFoundError()

    # Ghi nhận lịch sử chuyển giao nếu assignee thay đổi (bao gồm A -> B, None -> A, và A -> None)
    if old_assignee_id != target_user_id:
        lead_repository.create_lead_assignment_history(
            lead_id=lead_id,
            old_assigned_to_user_id=old_assignee_id,
            new_assigned_to_user_id=target_user_id,
            performed_by_user_id=performed_by_user_id,
            created_at=now,
        )

    assignee_name = target_user.name if target_user else (updated.assigned_to_name or "")
    msg = f"Đã phân công Lead cho {assignee_name}." if target_user_id else "Gỡ phân công Lead thành công."
    return {
        "status": "success",
        "message": msg,
        "data": updated.to_dict(),
    }


def bulk_assign_leads_service(
    payload: dict[str, Any],
    performed_by_user_id: str | None = None,
) -> dict[str, Any]:
    """
    Phân công hoặc gỡ phân công đồng loạt nhiều Lead (SCRUM-127 - Activity A10).
    Body: {"lead_ids": ["uuid-1", "uuid-2"], "user_id": "<uuid>" hoặc null}
    """
    if not isinstance(payload, dict):
        raise LeadValidationError("INVALID_JSON", "Dữ liệu yêu cầu phải là đối tượng JSON.")

    lead_ids_raw = payload.get("lead_ids")
    if not isinstance(lead_ids_raw, list) or len(lead_ids_raw) == 0:
        raise LeadValidationError("INVALID_PARAMS", "Danh sách 'lead_ids' phải là mảng không rỗng.")

    if len(lead_ids_raw) > 100:
        raise LeadValidationError("INVALID_PARAMS", "Không thể phân công quá 100 Lead mỗi lần.")

    lead_ids: list[str] = []
    for lid in lead_ids_raw:
        if not isinstance(lid, str) or not is_valid_uuid(lid.strip()):
            raise LeadValidationError("INVALID_PARAMS", f"Mã Lead '{lid}' không đúng định dạng UUID.")
        lead_ids.append(lid.strip())

    target_user_id: str | None = None
    target_user = None

    raw_user_id = payload.get("user_id")
    if raw_user_id is not None:
        if not isinstance(raw_user_id, str):
            raise LeadValidationError("INVALID_PARAMS", "Mã người dùng không hợp lệ.")
        clean_user_id = raw_user_id.strip()
        if not is_valid_uuid(clean_user_id):
            raise LeadValidationError("INVALID_PARAMS", "Mã người dùng không hợp lệ.")
        target_user_id = clean_user_id

        target_user = user_repository.get_user_by_id(target_user_id)
        if not target_user:
            raise LeadServiceError("USER_NOT_FOUND", "Người dùng được phân công không tồn tại.", status_code=404)

        if target_user.status != "active":
            raise LeadValidationError("INACTIVE_USER", "Người dùng không còn hoạt động, không thể nhận phân công.")

        if not is_user_consultant(target_user_id):
            raise LeadValidationError(
                "INVALID_ASSIGNEE",
                "Chỉ có thể phân công Lead cho nhân viên Tư vấn tuyển sinh.",
            )

    now = datetime.now(timezone.utc)
    updated_count = 0

    for lid in lead_ids:
        existing = lead_repository.get_lead_by_id(lid)
        if not existing:
            continue

        if existing.assigned_to_user_id != target_user_id:
            lead_repository.assign_lead(
                lead_id=lid,
                assigned_to_user_id=target_user_id,
                assigned_at=now if target_user_id else None,
                updated_at=now,
            )
            lead_repository.create_lead_assignment_history(
                lead_id=lid,
                old_assigned_to_user_id=existing.assigned_to_user_id,
                new_assigned_to_user_id=target_user_id,
                performed_by_user_id=performed_by_user_id,
                created_at=now,
            )
            updated_count += 1

    assignee_name = target_user.name if target_user else "tư vấn viên"
    msg = (
        f"Đã phân công {updated_count} Lead cho {assignee_name}."
        if target_user_id
        else f"Đã gỡ phân công {updated_count} Lead."
    )
    return {
        "status": "success",
        "message": msg,
        "data": {
            "updated_count": updated_count,
            "target_user_id": target_user_id,
        },
    }


def get_lead_assignment_history_service(
    lead_id: str,
    actor_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Lấy danh sách lịch sử phân công của một Lead (SCRUM-127 - Activity A8).
    Sắp xếp mới nhất ở trên.
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    lead = lead_repository.get_lead_by_id(lead_id)
    if not lead:
        raise LeadNotFoundError()

    if actor_id:
        actor_roles = set(user_role_repository.get_role_codes_by_user_id(actor_id))
        actor_user = user_repository.get_user_by_id(actor_id)
        if actor_user and actor_user.role:
            actor_roles.add(actor_user.role)

        is_privileged = bool(actor_roles.intersection({"admin", "training_manager"}))
        is_consultant = "consultant" in actor_roles

        if is_consultant and not is_privileged:
            if lead.assigned_to_user_id != actor_id:
                raise LeadServiceError(
                    "FORBIDDEN",
                    "Bạn không có quyền truy cập lịch sử của Lead này.",
                    status_code=403,
                )

    records = lead_repository.get_lead_assignment_history(lead_id)
    return [
        {
            "id": r["id"],
            "lead_id": r["lead_id"],
            "old_assigned_to_user_id": r["old_assigned_to_user_id"],
            "new_assigned_to_user_id": r["new_assigned_to_user_id"],
            "performed_by_user_id": r["performed_by_user_id"],
            "old_assigned_to_name": r["old_assigned_to_name"],
            "new_assigned_to_name": r["new_assigned_to_name"],
            "performed_by_name": r["performed_by_name"],
            "created_at": r["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if r.get("created_at") else None,
        }
        for r in records
    ]



def get_assignable_users_service() -> list[dict[str, Any]]:
    """
    Lấy danh sách người dùng có thể nhận phân công Lead (SCRUM-127 - Activity A4).
    Đảm bảo 100% users trả về có UUID hợp lệ để phân công không bị lỗi INVALID_PARAMS.
    """
    users = lead_repository.get_assignable_lead_users()
    return [u for u in users if is_valid_uuid(str(u.get("id", "")))]


def check_lead_phone_service(
    phone: str | None,
    exclude_lead_id: str | None = None,
) -> dict[str, Any]:
    """
    Kiểm tra số điện thoại có trùng với lead đã có hay không (SCRUM-126).
    """
    if not phone or not isinstance(phone, str) or len(phone.strip()) < 3:
        return {"exists": False, "lead": None}

    clean_phone = phone.strip()
    clean_exclude = exclude_lead_id.strip() if exclude_lead_id else None

    existing = lead_repository.get_lead_by_phone(clean_phone, exclude_lead_id=clean_exclude)
    if existing:
        return {
            "exists": True,
            "lead": {
                "id": existing.id,
                "full_name": existing.full_name,
                "phone": existing.phone,
            },
        }
    return {"exists": False, "lead": None}


ALLOWED_MANUAL_LEAD_FIELDS = {
    "full_name",
    "phone",
    "email",
    "source",
    "interested_program_id",
    "message",
}


def _validate_manual_lead_payload(payload: dict[str, Any]) -> tuple[str, str, str | None, str, str | None, str | None]:
    """Hàm chuẩn hóa và kiểm tra dữ liệu đầu vào cho tạo/sửa Lead thủ công (SCRUM-126)."""
    if not isinstance(payload, dict):
        raise LeadValidationError("INVALID_JSON", "Dữ liệu yêu cầu phải là đối tượng JSON.")

    unexpected = set(payload.keys()) - ALLOWED_MANUAL_LEAD_FIELDS
    if unexpected:
        raise LeadValidationError(
            "INVALID_PARAMS",
            f"Không được phép truyền các trường không hợp lệ: {', '.join(sorted(unexpected))}.",
        )

    # 1. Họ và tên * (bắt buộc)
    raw_name = payload.get("full_name")
    if raw_name is None:
        raise LeadValidationError("NAME_REQUIRED", "Vui lòng nhập họ và tên.")
    if not isinstance(raw_name, str):
        raise LeadValidationError("INVALID_PARAMS", "Họ và tên phải là chuỗi văn bản.")
    full_name = raw_name.strip()
    if not full_name:
        raise LeadValidationError("NAME_REQUIRED", "Vui lòng nhập họ và tên.")
    if len(full_name) > 255:
        raise LeadValidationError("INVALID_PARAMS", "Họ và tên không được vượt quá 255 ký tự.")

    # 2. Số điện thoại * (bắt buộc)
    raw_phone = payload.get("phone")
    if raw_phone is None:
        raise LeadValidationError("PHONE_REQUIRED", "Vui lòng nhập số điện thoại.")
    if not isinstance(raw_phone, str):
        raise LeadValidationError("INVALID_PARAMS", "Số điện thoại phải là chuỗi văn bản.")
    phone = raw_phone.strip()
    if not phone:
        raise LeadValidationError("PHONE_REQUIRED", "Vui lòng nhập số điện thoại.")
    if len(phone) > 30 or not PHONE_CHARS_REGEX.match(phone):
        raise LeadValidationError("INVALID_PARAMS", "Số điện thoại không đúng định dạng hợp lệ.")

    # 3. Email (không bắt buộc, nếu nhập phải đúng format)
    raw_email = payload.get("email")
    email: str | None = None
    if raw_email is not None and not (isinstance(raw_email, str) and not raw_email.strip()):
        if not isinstance(raw_email, str):
            raise LeadValidationError("INVALID_PARAMS", "Email phải là chuỗi văn bản.")
        email_cand = raw_email.strip().lower()
        if not EMAIL_REGEX.match(email_cand) or len(email_cand) > 255:
            raise LeadValidationError("INVALID_EMAIL", "Email không đúng định dạng hợp lệ.")
        email = email_cand

    # 4. Nguồn (mặc định 'direct' cho tạo thủ công)
    raw_source = payload.get("source")
    source = LEAD_SOURCE_DIRECT
    if raw_source is not None and not (isinstance(raw_source, str) and not raw_source.strip()):
        if not isinstance(raw_source, str):
            raise LeadValidationError("INVALID_PARAMS", "Nguồn tiếp nhận phải là chuỗi văn bản.")
        clean_source = raw_source.strip().lower()
        if clean_source not in VALID_LEAD_SOURCES:
            raise LeadValidationError(
                "INVALID_SOURCE",
                f"Nguồn '{clean_source}' không hợp lệ. Các nguồn hợp lệ: {', '.join(sorted(VALID_LEAD_SOURCES))}.",
            )
        source = clean_source

    # 5. Chương trình quan tâm (không bắt buộc, phải là UUID hợp lệ và tồn tại)
    raw_program_id = payload.get("interested_program_id")
    interested_program_id: str | None = None
    if raw_program_id is not None and not (isinstance(raw_program_id, str) and not raw_program_id.strip()):
        if not isinstance(raw_program_id, str):
            raise LeadValidationError("INVALID_PARAMS", "Mã chương trình quan tâm phải là chuỗi UUID.")
        clean_prog = raw_program_id.strip()
        if not is_valid_uuid(clean_prog):
            raise LeadValidationError("INVALID_PARAMS", "Mã chương trình quan tâm không hợp lệ.")
        prog = training_program_repository.get_training_program_by_id(clean_prog)
        if not prog:
            raise LeadProgramNotFoundError()
        interested_program_id = clean_prog

    # 6. Ghi chú nội dung (message)
    raw_msg = payload.get("message")
    message: str | None = None
    if raw_msg is not None and not (isinstance(raw_msg, str) and not raw_msg.strip()):
        if not isinstance(raw_msg, str):
            raise LeadValidationError("INVALID_PARAMS", "Nội dung ghi chú phải là chuỗi văn bản.")
        clean_msg = raw_msg.strip()
        if len(clean_msg) > 5000:
            raise LeadValidationError("INVALID_PARAMS", "Nội dung ghi chú không được vượt quá 5000 ký tự.")
        message = clean_msg

    return full_name, phone, email, source, interested_program_id, message


def create_manual_lead_service(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Tạo khách hàng tiềm năng thủ công bởi cán bộ tuyển sinh (SCRUM-126).
    """
    full_name, phone, email, source, interested_program_id, message = _validate_manual_lead_payload(payload)

    # Cảnh báo số điện thoại trùng
    existing_phone_lead = lead_repository.get_lead_by_phone(phone)
    duplicate_info = None
    if existing_phone_lead:
        duplicate_info = {
            "id": existing_phone_lead.id,
            "full_name": existing_phone_lead.full_name,
            "phone": existing_phone_lead.phone,
        }

    now = datetime.now(timezone.utc)
    new_lead = Lead(
        id=str(uuid.uuid4()),
        full_name=full_name,
        phone=phone,
        email=email,
        interested_program_id=interested_program_id,
        message=message,
        source=source,
        status=LEAD_STATUS_NEW,
        created_at=now,
        updated_at=now,
    )

    created_lead = lead_repository.insert_lead(new_lead)

    return {
        "status": "success",
        "message": "Tạo khách hàng tiềm năng thành công.",
        "data": created_lead.to_dict(),
        "duplicate_warning": bool(existing_phone_lead),
        "existing_lead": duplicate_info,
    }


def update_lead_info_service(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Cập nhật thông tin chi tiết một Lead (SCRUM-126 - Tạo và sửa Lead).
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    existing_lead = lead_repository.get_lead_by_id(lead_id)
    if not existing_lead:
        raise LeadNotFoundError()

    full_name, phone, email, source, interested_program_id, message = _validate_manual_lead_payload(payload)

    # Cảnh báo số điện thoại trùng (ngoại trừ lead hiện tại)
    existing_phone_lead = lead_repository.get_lead_by_phone(phone, exclude_lead_id=lead_id)
    duplicate_info = None
    if existing_phone_lead:
        duplicate_info = {
            "id": existing_phone_lead.id,
            "full_name": existing_phone_lead.full_name,
            "phone": existing_phone_lead.phone,
        }

    now = datetime.now(timezone.utc)
    updated = lead_repository.update_lead_info(
        lead_id=lead_id,
        full_name=full_name,
        phone=phone,
        email=email,
        source=source,
        interested_program_id=interested_program_id,
        message=message,
        updated_at=now,
    )
    if not updated:
        raise LeadNotFoundError()

    return {
        "status": "success",
        "message": "Cập nhật khách hàng tiềm năng thành công.",
        "data": updated.to_dict(),
        "duplicate_warning": bool(existing_phone_lead),
        "existing_lead": duplicate_info,
    }


def delete_lead_service(lead_id: str) -> dict[str, Any]:
    """
    Xóa một Lead theo ID (SCRUM-126).
    - Kiểm tra ID hợp lệ (UUID).
    - Ném LeadNotFoundError (404) nếu không tìm thấy.
    - Thực hiện xóa và trả về kết quả thành công.
    """
    if not is_valid_uuid(lead_id):
        raise LeadValidationError("INVALID_PARAMS", "Mã Lead không hợp lệ.")

    existing = lead_repository.get_lead_by_id(lead_id)
    if not existing:
        raise LeadNotFoundError("Không tìm thấy thông tin Lead để xóa.")

    success = lead_repository.delete_lead(lead_id)
    if not success:
        raise LeadServiceError("DELETE_FAILED", "Không thể xóa khách hàng tiềm năng.", 500)

    return {
        "status": "success",
        "message": "Xóa khách hàng tiềm năng thành công.",
        "data": {"id": lead_id},
    }




