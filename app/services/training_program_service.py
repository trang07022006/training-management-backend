import math
from typing import Any

from app.models.training_program import VALID_PROGRAM_STATUSES
from app.repositories import training_program_repository


class TrainingProgramServiceError(Exception):
    """Lớp ngoại lệ cơ sở cho nghiệp vụ chương trình đào tạo."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class TrainingProgramNotFoundError(TrainingProgramServiceError):
    """Ngoại lệ khi không tìm thấy chương trình đào tạo (404)."""

    def __init__(self, message: str = "Không tìm thấy chương trình đào tạo."):
        super().__init__(code="PROGRAM_NOT_FOUND", message=message, status_code=404)


class TrainingProgramValidationError(TrainingProgramServiceError):
    """Ngoại lệ khi tham số yêu cầu không hợp lệ (400)."""

    def __init__(self, message: str, code: str = "INVALID_PARAMS"):
        super().__init__(code=code, message=message, status_code=400)


def get_training_programs_service(
    page_raw: Any = 1,
    page_size_raw: Any = 20,
    status: str | None = None,
    search: str | None = None,
) -> dict:
    """
    Nghiệp vụ lấy danh sách chương trình đào tạo có phân trang, lọc và tìm kiếm (SCRUM-122 - Activity A2).
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
        raise TrainingProgramValidationError("Số trang (page) phải là số nguyên dương lớn hơn hoặc bằng 1.")

    # 2. Validate page_size
    try:
        page_size = int(page_size_raw)
        if page_size < 1 or page_size > 100:
            raise ValueError()
    except (ValueError, TypeError):
        raise TrainingProgramValidationError("Kích thước trang (page_size) phải là số nguyên từ 1 đến 100.")

    # 3. Validate status
    cleaned_status = None
    if status is not None and str(status).strip():
        cleaned_status = str(status).strip()
        if cleaned_status not in VALID_PROGRAM_STATUSES:
            allowed = ", ".join(sorted(VALID_PROGRAM_STATUSES))
            raise TrainingProgramValidationError(
                f"Trạng thái chương trình không hợp lệ: '{cleaned_status}'. Cho phép: {allowed}."
            )

    # 4. Clean search
    cleaned_search = None
    if search is not None and str(search).strip():
        cleaned_search = str(search).strip()
        if len(cleaned_search) > 255:
            cleaned_search = cleaned_search[:255]

    # 5. Truy vấn repository
    offset = (page - 1) * page_size
    programs = training_program_repository.get_all_training_programs(
        status=cleaned_status,
        search=cleaned_search,
        limit=page_size,
        offset=offset,
    )
    total = training_program_repository.count_training_programs(
        status=cleaned_status,
        search=cleaned_search,
    )

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return {
        "items": [program.to_dict() for program in programs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_training_program_detail_service(program_id: str) -> dict:
    """
    Nghiệp vụ lấy chi tiết một chương trình đào tạo theo ID (SCRUM-122 - Activity A2).
    - Validate định danh program_id
    - Trả về 404 nếu không tìm thấy
    """
    if not isinstance(program_id, str) or not program_id.strip():
        raise TrainingProgramValidationError("Mã định danh chương trình đào tạo không hợp lệ.")

    cleaned_id = program_id.strip()

    program = training_program_repository.get_training_program_by_id(cleaned_id)
    if program is None:
        raise TrainingProgramNotFoundError("Không tìm thấy chương trình đào tạo.")

    return program.to_dict()
