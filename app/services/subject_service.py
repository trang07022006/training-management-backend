import math
import uuid
from typing import Any

from app.models.subject import (
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
