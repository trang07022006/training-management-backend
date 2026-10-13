"""
Tầng nghiệp vụ Quản lý Lớp học (Class Service) - SCRUM-217.
- Khai báo và mở lớp từ chương trình đào tạo (217-01).
- Đảm bảo mã lớp duy nhất (217-02).
- Vòng đời trạng thái: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ (217-03).
- Tự động sao chép danh sách môn học từ chương trình sang lớp (217-04).
"""

from datetime import datetime, timezone
import logging
import uuid
from app.models.class_entity import (
    CLASS_STATUS_CANCELLED,
    CLASS_STATUS_COMPLETED,
    CLASS_STATUS_IN_PROGRESS,
    CLASS_STATUS_PREPARING,
    CLASS_STATUS_LABELS,
    CLASS_STATUSES,
    VIETNAMESE_TO_STATUS,
    ClassEntity,
)
from app.repositories import class_repository, training_program_repository

logger = logging.getLogger(__name__)


class ClassServiceError(Exception):
    """Lớp ngoại lệ cơ sở cho nghiệp vụ Class."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ClassValidationError(ClassServiceError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, status_code=400)


class ClassCodeAlreadyExistsError(ClassServiceError):
    def __init__(self, message: str = "Mã lớp đã tồn tại. Vui lòng chọn mã lớp khác."):
        super().__init__("CLASS_CODE_ALREADY_EXISTS", message, status_code=409)


class ClassNotFoundError(ClassServiceError):
    def __init__(self, message: str = "Không tìm thấy lớp học."):
        super().__init__("CLASS_NOT_FOUND", message, status_code=404)


class ProgramNotFoundError(ClassServiceError):
    def __init__(self, message: str = "Chương trình đào tạo không tồn tại trong hệ thống."):
        super().__init__("PROGRAM_NOT_FOUND", message, status_code=404)


class InvalidLifecycleStatusError(ClassServiceError):
    def __init__(self, message: str = "Trạng thái lớp không hợp lệ. Chỉ chấp nhận 4 trạng thái: Chuẩn bị, Đang học, Kết thúc, Huỷ."):
        super().__init__("INVALID_CLASS_STATUS", message, status_code=400)


def create_class_service(payload: dict) -> dict:
    """
    Khai báo và mở lớp mới từ chương trình đào tạo (SCRUM-217 - 217-01 -> 217-04).
    Yêu cầu:
    1. Mã lớp là bắt buộc và DUY NHẤT trong hệ thống (217-02).
    2. Chương trình đào tạo là bắt buộc và phải tồn tại.
    3. Ngày khai giảng dự kiến, sĩ số tối đa (> 0), hình thức học.
    4. Trạng thái khởi tạo: Chuẩn bị (preparing) (217-03).
    5. Danh sách môn học được tự động sao chép từ chương trình khi mở lớp (217-04).
    """
    # 1. Mã lớp
    class_code = payload.get("class_code")
    if not isinstance(class_code, str) or not class_code.strip():
        raise ClassValidationError("CLASS_CODE_REQUIRED", "Mã lớp học là bắt buộc.")
    class_code = class_code.strip().upper()

    # Kiểm tra mã lớp duy nhất (217-02)
    existing = class_repository.get_class_by_code(class_code)
    if existing:
        raise ClassCodeAlreadyExistsError("Mã lớp đã tồn tại. Vui lòng chọn mã lớp khác.")

    # 2. Chương trình đào tạo
    program_id = payload.get("program_id")
    if not isinstance(program_id, str) or not program_id.strip():
        raise ClassValidationError("PROGRAM_REQUIRED", "Chương trình đào tạo là bắt buộc.")
    program_id = program_id.strip()

    # Kiểm tra chương trình có tồn tại
    program = training_program_repository.get_training_program_by_id(program_id)
    if not program:
        raise ProgramNotFoundError("Chương trình đào tạo được chọn không tồn tại.")

    # 3. Ngày khai giảng dự kiến
    expected_start_date = payload.get("expected_start_date")
    if expected_start_date:
        if isinstance(expected_start_date, str):
            expected_start_date = expected_start_date.strip()
            if not expected_start_date:
                expected_start_date = None
            else:
                try:
                    # Kiểm tra format YYYY-MM-DD
                    datetime.strptime(expected_start_date, "%Y-%m-%d")
                except ValueError:
                    raise ClassValidationError("INVALID_DATE", "Ngày khai giảng dự kiến không đúng định dạng YYYY-MM-DD.")
    else:
        expected_start_date = None

    # 4. Sĩ số tối đa
    max_capacity_raw = payload.get("max_capacity", 30)
    try:
        max_capacity = int(max_capacity_raw)
        if max_capacity <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise ClassValidationError("INVALID_CAPACITY", "Sĩ số tối đa phải là số nguyên dương lớn hơn 0.")

    # 5. Hình thức học
    learning_mode = payload.get("learning_mode", "offline")
    if isinstance(learning_mode, str) and learning_mode.strip():
        learning_mode = learning_mode.strip()
    else:
        learning_mode = "offline"

    # 6. Trạng thái khởi tạo: Chuẩn bị
    status = payload.get("status")
    if status:
        normalized_status = normalize_status(status)
        if not normalized_status:
            raise InvalidLifecycleStatusError()
        status = normalized_status
    else:
        status = CLASS_STATUS_PREPARING

    # 7. Lưu lớp học
    class_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    entity = ClassEntity(
        id=class_id,
        class_code=class_code,
        program_id=program_id,
        expected_start_date=expected_start_date,
        max_capacity=max_capacity,
        learning_mode=learning_mode,
        status=status,
        created_at=now,
        updated_at=now,
    )
    created = class_repository.create_class(entity)

    # 8. Sao chép danh sách môn học từ chương trình sang lớp (217-04)
    copied_count = class_repository.copy_program_subjects_to_class(class_id, program_id)
    logger.info("Created class %s and copied %d subjects from program %s", class_code, copied_count, program_id)

    # 9. Đọc danh sách môn học đã sao chép để trả về
    subjects = class_repository.get_class_subjects(class_id)
    result = created.to_dict()
    result["subjects"] = [s.to_dict() for s in subjects]
    result["copied_subjects_count"] = copied_count
    return result


def normalize_status(status_input: str) -> str | None:
    """Chuẩn hóa trạng thái vòng đời từ mã hoặc nhãn tiếng Việt."""
    if not isinstance(status_input, str):
        return None
    val = status_input.strip().lower()
    if val in CLASS_STATUSES:
        return val
    if val in VIETNAMESE_TO_STATUS:
        return VIETNAMESE_TO_STATUS[val]
    return None


def update_class_lifecycle_status_service(class_id: str, new_status: str) -> dict:
    """
    Cập nhật trạng thái vòng đời của lớp học (SCRUM-217 - 217-03).
    Chỉ chấp nhận 4 trạng thái: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ.
    """
    cls = class_repository.get_class_by_id(class_id)
    if not cls:
        raise ClassNotFoundError()

    normalized = normalize_status(new_status)
    if not normalized:
        raise InvalidLifecycleStatusError()

    updated = class_repository.update_class_status(class_id, normalized)
    if not updated:
        raise ClassNotFoundError()

    subjects = class_repository.get_class_subjects(class_id)
    res = updated.to_dict()
    res["subjects"] = [s.to_dict() for s in subjects]
    return res


def get_class_detail_service(class_id: str) -> dict:
    """Lấy thông tin chi tiết lớp học kèm danh sách môn học đã sao chép (217-01 & 217-04)."""
    cls = class_repository.get_class_by_id(class_id)
    if not cls:
        raise ClassNotFoundError()

    subjects = class_repository.get_class_subjects(class_id)
    res = cls.to_dict()
    res["subjects"] = [s.to_dict() for s in subjects]
    return res


def get_class_subjects_service(class_id: str) -> list[dict]:
    """Lấy riêng danh sách môn học của lớp học (217-04)."""
    cls = class_repository.get_class_by_id(class_id)
    if not cls:
        raise ClassNotFoundError()

    subjects = class_repository.get_class_subjects(class_id)
    return [s.to_dict() for s in subjects]


def list_classes_service(
    program_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Danh sách các lớp học có phân trang và tìm kiếm."""
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    if status:
        status = normalize_status(status) or status

    classes, total = class_repository.list_classes(
        program_id=program_id,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [c.to_dict() for c in classes],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }
