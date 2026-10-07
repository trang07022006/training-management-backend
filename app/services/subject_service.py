from datetime import datetime, timezone
import math
from typing import Any
import uuid

from mysql.connector import IntegrityError

from app.models.subject import (
    MAX_SUBJECT_CREDITS,
    MIN_SUBJECT_CREDITS,
    SUBJECT_STATUS_DRAFT,
    Subject,
    VALID_SUBJECT_STATUSES,
)
from app.repositories import subject_repository


def is_valid_uuid(val: str) -> bool:
    """Kiểm tra chuỗi có đúng định dạng UUID hay không."""
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        parsed = uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError, AttributeError):
        return False


class SubjectServiceError(Exception):
    """Lớp ngoại lệ cơ sở cho nghiệp vụ môn học/học phần."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class SubjectNotFoundError(SubjectServiceError):
    """Ngoại lệ khi không tìm thấy môn học (404)."""

    def __init__(self, message: str = "Không tìm thấy môn học."):
        super().__init__(code="SUBJECT_NOT_FOUND", message=message, status_code=404)


class SubjectValidationError(SubjectServiceError):
    """Ngoại lệ khi tham số yêu cầu không hợp lệ (400)."""

    def __init__(self, message: str, code: str = "INVALID_PARAMS"):
        super().__init__(code=code, message=message, status_code=400)


class DuplicateSubjectCodeError(SubjectServiceError):
    """Ngoại lệ khi mã môn học bị trùng lặp (409)."""

    def __init__(self, message: str = "Mã môn học đã tồn tại trong hệ thống."):
        super().__init__(code="DUPLICATE_CODE", message=message, status_code=409)


class SubjectInUseError(SubjectServiceError):
    """Ngoại lệ khi môn học đang có dữ liệu liên kết hoặc phụ thuộc (409)."""

    def __init__(
        self,
        message: str = "Không thể xóa môn học vì đang có dữ liệu liên kết trong hệ thống.",
    ):
        super().__init__(code="SUBJECT_IN_USE", message=message, status_code=409)


def get_subjects_service(
    page_raw: Any = 1,
    page_size_raw: Any = 20,
    status: str | None = None,
    search: str | None = None,
) -> dict:
    """
    Nghiệp vụ lấy danh sách môn học có phân trang, lọc và tìm kiếm (SCRUM-123 - Activity A2).
    - Validate page >= 1
    - Validate 1 <= page_size <= 100
    - Validate status trong danh sách cho phép (draft, active, archived)
    - Trả về cấu trúc phân trang chuẩn
    """
    # 1. Validate page
    try:
        page = int(page_raw)
        if page < 1:
            raise ValueError()
    except (ValueError, TypeError):
        raise SubjectValidationError(
            "Số trang (page) phải là số nguyên dương lớn hơn hoặc bằng 1.",
            code="INVALID_PARAMS",
        )

    # 2. Validate page_size
    try:
        page_size = int(page_size_raw)
        if page_size < 1 or page_size > 100:
            raise ValueError()
    except (ValueError, TypeError):
        raise SubjectValidationError(
            "Kích thước trang (page_size) phải là số nguyên từ 1 đến 100.",
            code="INVALID_PARAMS",
        )

    # 3. Validate status
    cleaned_status = None
    if status is not None and str(status).strip():
        cleaned_status = str(status).strip().lower()
        if cleaned_status not in VALID_SUBJECT_STATUSES:
            allowed = ", ".join(sorted(VALID_SUBJECT_STATUSES))
            raise SubjectValidationError(
                f"Trạng thái môn học không hợp lệ: '{cleaned_status}'. Cho phép: {allowed}.",
                code="INVALID_PARAMS",
            )

    # 4. Clean search
    cleaned_search = None
    if search is not None and str(search).strip():
        cleaned_search = str(search).strip()
        if len(cleaned_search) > 255:
            cleaned_search = cleaned_search[:255]

    # 5. Truy vấn repository
    offset = (page - 1) * page_size
    subjects = subject_repository.get_all_subjects(
        status=cleaned_status,
        search=cleaned_search,
        limit=page_size,
        offset=offset,
    )
    total = subject_repository.count_subjects(
        status=cleaned_status,
        search=cleaned_search,
    )

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return {
        "items": [subject.to_dict() for subject in subjects],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_subject_detail_service(subject_id: str) -> dict:
    """
    Nghiệp vụ lấy chi tiết một môn học theo ID (SCRUM-123 - Activity A2).
    - Validate định danh subject_id đúng chuẩn UUID (36 ký tự).
    - Nếu sai định dạng -> HTTP 400 (INVALID_PARAMS).
    - Nếu UUID hợp lệ nhưng không tìm thấy -> HTTP 404 (SUBJECT_NOT_FOUND).
    """
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise SubjectValidationError(
            "Mã định danh môn học không hợp lệ.",
            code="INVALID_PARAMS",
        )

    cleaned_id = subject_id.strip()

    if not is_valid_uuid(cleaned_id):
        raise SubjectValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    subject = subject_repository.get_subject_by_id(cleaned_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    return subject.to_dict()


def validate_subject_code(raw_code: Any) -> str:
    """Kiểm tra và chuẩn hóa mã môn học (code)."""
    if raw_code is None or not isinstance(raw_code, str):
        raise SubjectValidationError(
            "Mã môn học (code) là bắt buộc.",
            code="CODE_REQUIRED",
        )
    cleaned = raw_code.strip()
    if not cleaned:
        raise SubjectValidationError(
            "Mã môn học không được để trống.",
            code="CODE_REQUIRED",
        )
    if len(cleaned) > 50:
        raise SubjectValidationError(
            "Mã môn học không được vượt quá 50 ký tự.",
            code="CODE_TOO_LONG",
        )
    return cleaned.upper()


def validate_subject_name(raw_name: Any) -> str:
    """Kiểm tra và chuẩn hóa tên môn học (name)."""
    if raw_name is None or not isinstance(raw_name, str):
        raise SubjectValidationError(
            "Tên môn học (name) là bắt buộc.",
            code="NAME_REQUIRED",
        )
    cleaned = raw_name.strip()
    if not cleaned:
        raise SubjectValidationError(
            "Tên môn học không được để trống.",
            code="NAME_REQUIRED",
        )
    if len(cleaned) > 255:
        raise SubjectValidationError(
            "Tên môn học không được vượt quá 255 ký tự.",
            code="NAME_TOO_LONG",
        )
    return cleaned


def validate_subject_description(raw_desc: Any) -> str | None:
    """Kiểm tra và chuẩn hóa mô tả môn học (description)."""
    if raw_desc is None:
        return None
    if isinstance(raw_desc, bool) or not isinstance(raw_desc, str):
        raise SubjectValidationError(
            "Mô tả môn học phải là chuỗi ký tự.",
            code="INVALID_PARAMS",
        )
    cleaned = raw_desc.strip()
    return cleaned if cleaned else None


def validate_subject_credits(raw_credits: Any) -> int:
    """Kiểm tra và chuẩn hóa số tín chỉ (credits)."""
    if raw_credits is None:
        raise SubjectValidationError(
            "Số tín chỉ (credits) là bắt buộc.",
            code="INVALID_PARAMS",
        )
    if isinstance(raw_credits, bool) or not isinstance(raw_credits, int):
        raise SubjectValidationError(
            "Số tín chỉ (credits) phải là số nguyên từ 1 đến 30.",
            code="INVALID_PARAMS",
        )
    if raw_credits < MIN_SUBJECT_CREDITS or raw_credits > MAX_SUBJECT_CREDITS:
        raise SubjectValidationError(
            f"Số tín chỉ (credits) phải nằm trong khoảng từ {MIN_SUBJECT_CREDITS} đến {MAX_SUBJECT_CREDITS}.",
            code="INVALID_PARAMS",
        )
    return raw_credits


def validate_subject_total_sessions(raw_sessions: Any) -> int | None:
    """Kiểm tra và chuẩn hóa tổng số tiết/buổi học (total_sessions)."""
    if raw_sessions is None:
        return None
    if isinstance(raw_sessions, bool) or not isinstance(raw_sessions, int):
        raise SubjectValidationError(
            "Tổng số tiết/buổi học (total_sessions) phải là số nguyên không âm.",
            code="INVALID_PARAMS",
        )
    if raw_sessions < 0 or raw_sessions > 65535:
        raise SubjectValidationError(
            "Tổng số tiết/buổi học (total_sessions) phải nằm trong khoảng từ 0 đến 65535.",
            code="INVALID_PARAMS",
        )
    return raw_sessions


def validate_subject_status(raw_status: Any, default: str = SUBJECT_STATUS_DRAFT) -> str:
    """Kiểm tra và chuẩn hóa trạng thái môn học (status)."""
    if raw_status is None:
        return default
    if isinstance(raw_status, bool) or not isinstance(raw_status, str):
        raise SubjectValidationError(
            "Trạng thái môn học không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned = raw_status.strip().lower()
    if not cleaned:
        return default
    if cleaned not in VALID_SUBJECT_STATUSES:
        allowed = ", ".join(sorted(VALID_SUBJECT_STATUSES))
        raise SubjectValidationError(
            f"Trạng thái không hợp lệ: '{cleaned}'. Cho phép: {allowed}.",
            code="INVALID_PARAMS",
        )
    return cleaned


def create_subject_service(data: dict) -> dict:
    """
    Nghiệp vụ tạo mới một môn học/học phần (SCRUM-123 - Activity A3).
    Quy tắc nghiệp vụ & validation:
    1. data phải là dict hợp lệ.
    2. code: Bắt buộc, không rỗng, tối đa 50 ký tự, chuẩn hóa uppercase, không trùng trong database.
    3. name: Bắt buộc, không rỗng, tối đa 255 ký tự.
    4. description: Tùy chọn, chuỗi ký tự hoặc None.
    5. credits: Bắt buộc, số nguyên từ 1 đến 30.
    6. total_sessions: Tùy chọn, số nguyên không âm (0-65535) hoặc None.
    7. status: Tùy chọn, mặc định 'draft', nhận: draft, active, archived.
    8. id, created_at, updated_at: Backend tự sinh UUID v4 & UTC timestamp, bỏ qua dữ liệu client truyền.
    """
    if not isinstance(data, dict):
        raise SubjectValidationError(
            "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
            code="INVALID_JSON",
        )

    cleaned_code = validate_subject_code(data.get("code"))
    cleaned_name = validate_subject_name(data.get("name"))
    cleaned_desc = validate_subject_description(data.get("description"))
    cleaned_credits = validate_subject_credits(data.get("credits"))
    cleaned_sessions = validate_subject_total_sessions(data.get("total_sessions"))
    cleaned_status = validate_subject_status(data.get("status"), default=SUBJECT_STATUS_DRAFT)

    # 1. Kiểm tra trùng mã môn học ở tầng service
    if subject_repository.exists_by_code(cleaned_code):
        raise DuplicateSubjectCodeError()

    # 2. Khởi tạo đối tượng với UUID v4 và UTC timestamp do server tự sinh
    subject_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    subject = Subject(
        id=subject_id,
        code=cleaned_code,
        name=cleaned_name,
        credits=cleaned_credits,
        description=cleaned_desc,
        total_sessions=cleaned_sessions,
        status=cleaned_status,
        created_at=now,
        updated_at=now,
    )

    # 3. Lưu vào database và bắt IntegrityError để chống race condition
    try:
        created_subject = subject_repository.insert_subject(subject)
    except IntegrityError as err:
        err_msg = str(err).lower()
        if getattr(err, "errno", None) == 1062 or "duplicate" in err_msg or "code" in err_msg or "unique" in err_msg:
            raise DuplicateSubjectCodeError()
        raise
    except Exception as err:
        err_msg = str(err).lower()
        if "duplicate" in err_msg or "1062" in err_msg or "unique" in err_msg:
            raise DuplicateSubjectCodeError()
        raise

    return created_subject.to_dict()


def validate_patch_status(raw_status: Any) -> str:
    """Kiểm tra trạng thái môn học khi PATCH (bắt buộc phải là giá trị hợp lệ, không cho phép null/rỗng)."""
    if raw_status is None or isinstance(raw_status, bool) or not isinstance(raw_status, str):
        raise SubjectValidationError(
            "Trạng thái môn học không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned = raw_status.strip().lower()
    if not cleaned or cleaned not in VALID_SUBJECT_STATUSES:
        allowed = ", ".join(sorted(VALID_SUBJECT_STATUSES))
        raise SubjectValidationError(
            f"Trạng thái không hợp lệ: '{cleaned}'. Cho phép: {allowed}.",
            code="INVALID_PARAMS",
        )
    return cleaned


def update_subject_service(subject_id: str, data: dict) -> dict:
    """
    Nghiệp vụ cập nhật toàn bộ thông tin một môn học (SCRUM-123 - Activity A4 - PUT).
    - Validate subject_id (định dạng UUID, tồn tại trong database).
    - Validate data (phải là dict).
    - code, name, credits bắt buộc.
    - description, total_sessions, status xử lý theo quy tắc chuẩn:
      nếu không gửi -> description=None, total_sessions=None, status='draft'.
    - Không cho phép cập nhật id hoặc created_at.
    - Cập nhật updated_at theo UTC.
    - Kiểm tra mã code trùng lặp (ngoại trừ chính môn học này).
    """
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise SubjectValidationError(
            "Mã định danh môn học không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned_id = subject_id.strip()
    if not is_valid_uuid(cleaned_id):
        raise SubjectValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(data, dict):
        raise SubjectValidationError(
            "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
            code="INVALID_JSON",
        )

    existing = subject_repository.get_subject_by_id(cleaned_id)
    if existing is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    cleaned_code = validate_subject_code(data.get("code"))
    cleaned_name = validate_subject_name(data.get("name"))
    cleaned_credits = validate_subject_credits(data.get("credits"))
    cleaned_desc = validate_subject_description(data.get("description"))
    cleaned_sessions = validate_subject_total_sessions(data.get("total_sessions"))
    cleaned_status = validate_subject_status(data.get("status"), default=SUBJECT_STATUS_DRAFT)

    if cleaned_code != existing.code:
        if subject_repository.exists_by_code(cleaned_code, exclude_id=cleaned_id):
            raise DuplicateSubjectCodeError()

    now = datetime.now(timezone.utc)
    subject_to_update = Subject(
        id=cleaned_id,
        code=cleaned_code,
        name=cleaned_name,
        credits=cleaned_credits,
        description=cleaned_desc,
        total_sessions=cleaned_sessions,
        status=cleaned_status,
        created_at=existing.created_at,
        updated_at=now,
    )

    try:
        subject_repository.update_subject(subject_to_update)
    except IntegrityError as err:
        err_msg = str(err).lower()
        if getattr(err, "errno", None) == 1062 or "duplicate" in err_msg or "code" in err_msg or "unique" in err_msg:
            raise DuplicateSubjectCodeError()
        raise
    except Exception as err:
        err_msg = str(err).lower()
        if "duplicate" in err_msg or "1062" in err_msg or "unique" in err_msg:
            raise DuplicateSubjectCodeError()
        raise

    return subject_to_update.to_dict()


def patch_subject_service(subject_id: str, data: dict) -> dict:
    """
    Nghiệp vụ cập nhật từng phần thông tin một môn học (SCRUM-123 - Activity A4 - PATCH).
    - Validate subject_id (định dạng UUID, tồn tại trong database).
    - Validate data (phải là dict, không được rỗng).
    - Chỉ cập nhật các trường được gửi:
      code, name, description, credits, total_sessions, status.
    - Các trường không gửi được giữ nguyên tuyệt đối.
    - Bỏ qua id, created_at, updated_at do client truyền.
    - Cập nhật updated_at theo UTC.
    - Kiểm tra mã code trùng lặp (ngoại trừ chính môn học này).
    """
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise SubjectValidationError(
            "Mã định danh môn học không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned_id = subject_id.strip()
    if not is_valid_uuid(cleaned_id):
        raise SubjectValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(data, dict):
        raise SubjectValidationError(
            "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
            code="INVALID_JSON",
        )

    if not data:
        raise SubjectValidationError(
            "Dữ liệu yêu cầu không được để trống.",
            code="INVALID_PARAMS",
        )

    existing = subject_repository.get_subject_by_id(cleaned_id)
    if existing is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    fields_to_update: dict[str, Any] = {}

    if "code" in data:
        cleaned_code = validate_subject_code(data["code"])
        if cleaned_code != existing.code:
            if subject_repository.exists_by_code(cleaned_code, exclude_id=cleaned_id):
                raise DuplicateSubjectCodeError()
        fields_to_update["code"] = cleaned_code

    if "name" in data:
        fields_to_update["name"] = validate_subject_name(data["name"])

    if "description" in data:
        fields_to_update["description"] = validate_subject_description(data["description"])

    if "credits" in data:
        fields_to_update["credits"] = validate_subject_credits(data["credits"])

    if "total_sessions" in data:
        fields_to_update["total_sessions"] = validate_subject_total_sessions(data["total_sessions"])

    if "status" in data:
        fields_to_update["status"] = validate_patch_status(data["status"])

    if not fields_to_update:
        raise SubjectValidationError(
            "Không có trường dữ liệu nào hợp lệ để cập nhật.",
            code="INVALID_PARAMS",
        )

    try:
        updated = subject_repository.update_subject_fields(cleaned_id, fields_to_update)
    except IntegrityError as err:
        err_msg = str(err).lower()
        if getattr(err, "errno", None) == 1062 or "duplicate" in err_msg or "code" in err_msg or "unique" in err_msg:
            raise DuplicateSubjectCodeError()
        raise
    except Exception as err:
        err_msg = str(err).lower()
        if "duplicate" in err_msg or "1062" in err_msg or "unique" in err_msg:
            raise DuplicateSubjectCodeError()
        raise

    if updated is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    return updated.to_dict()


