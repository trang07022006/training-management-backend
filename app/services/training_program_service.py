import math
import uuid
from datetime import datetime, timezone
from typing import Any
from mysql.connector.errors import IntegrityError

from app.models.training_program import (
    PROGRAM_STATUS_DRAFT,
    VALID_PROGRAM_STATUSES,
    TrainingProgram,
)
from app.repositories import training_program_repository


def is_valid_uuid(val: str) -> bool:
    """Kiểm tra chuỗi có đúng định dạng UUID hay không."""
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        parsed = uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError, AttributeError):
        return False


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


class DuplicateProgramCodeError(TrainingProgramServiceError):
    """Ngoại lệ khi mã chương trình đào tạo bị trùng lặp (409)."""

    def __init__(self, message: str = "Mã chương trình đào tạo đã tồn tại trong hệ thống."):
        super().__init__(code="DUPLICATE_CODE", message=message, status_code=409)


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
        raise TrainingProgramValidationError(
            "Số trang (page) phải là số nguyên dương lớn hơn hoặc bằng 1.",
            code="INVALID_PARAMS",
        )

    # 2. Validate page_size
    try:
        page_size = int(page_size_raw)
        if page_size < 1 or page_size > 100:
            raise ValueError()
    except (ValueError, TypeError):
        raise TrainingProgramValidationError(
            "Kích thước trang (page_size) phải là số nguyên từ 1 đến 100.",
            code="INVALID_PARAMS",
        )

    # 3. Validate status
    cleaned_status = None
    if status is not None and str(status).strip():
        cleaned_status = str(status).strip().lower()
        if cleaned_status not in VALID_PROGRAM_STATUSES:
            allowed = ", ".join(sorted(VALID_PROGRAM_STATUSES))
            raise TrainingProgramValidationError(
                f"Trạng thái chương trình không hợp lệ: '{cleaned_status}'. Cho phép: {allowed}.",
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
    - Validate định danh program_id đúng chuẩn UUID (36 ký tự).
    - Nếu sai định dạng -> HTTP 400 (INVALID_PARAMS).
    - Nếu UUID hợp lệ nhưng không tìm thấy -> HTTP 404 (PROGRAM_NOT_FOUND).
    """
    if not isinstance(program_id, str) or not program_id.strip():
        raise TrainingProgramValidationError(
            "Mã định danh chương trình đào tạo không hợp lệ.",
            code="INVALID_PARAMS",
        )

    cleaned_id = program_id.strip()

    if not is_valid_uuid(cleaned_id):
        raise TrainingProgramValidationError(
            "Mã định danh chương trình đào tạo không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    program = training_program_repository.get_training_program_by_id(cleaned_id)
    if program is None:
        raise TrainingProgramNotFoundError("Không tìm thấy chương trình đào tạo.")

    return program.to_dict()


def validate_program_code(raw_code: Any) -> str:
    """Kiểm tra và chuẩn hóa mã chương trình (code)."""
    if raw_code is None or not isinstance(raw_code, str):
        raise TrainingProgramValidationError(
            "Mã chương trình (code) là bắt buộc.",
            code="CODE_REQUIRED",
        )
    cleaned = raw_code.strip()
    if not cleaned:
        raise TrainingProgramValidationError(
            "Mã chương trình không được để trống.",
            code="CODE_REQUIRED",
        )
    if len(cleaned) > 50:
        raise TrainingProgramValidationError(
            "Mã chương trình không được vượt quá 50 ký tự.",
            code="CODE_TOO_LONG",
        )
    return cleaned


def validate_program_name(raw_name: Any) -> str:
    """Kiểm tra và chuẩn hóa tên chương trình (name)."""
    if raw_name is None or not isinstance(raw_name, str):
        raise TrainingProgramValidationError(
            "Tên chương trình (name) là bắt buộc.",
            code="NAME_REQUIRED",
        )
    cleaned = raw_name.strip()
    if not cleaned:
        raise TrainingProgramValidationError(
            "Tên chương trình không được để trống.",
            code="NAME_REQUIRED",
        )
    if len(cleaned) > 255:
        raise TrainingProgramValidationError(
            "Tên chương trình không được vượt quá 255 ký tự.",
            code="NAME_TOO_LONG",
        )
    return cleaned


def validate_program_description(raw_desc: Any) -> str | None:
    """Kiểm tra và chuẩn hóa mô tả chương trình (description)."""
    if raw_desc is None:
        return None
    if not isinstance(raw_desc, str):
        raise TrainingProgramValidationError(
            "Mô tả chương trình phải là chuỗi ký tự.",
            code="INVALID_PARAMS",
        )
    cleaned = raw_desc.strip()
    return cleaned if cleaned else None


def validate_program_duration(raw_duration: Any) -> int | None:
    """Kiểm tra và chuẩn hóa thời lượng học kỳ (duration_semesters)."""
    if raw_duration is None:
        return None
    if isinstance(raw_duration, bool) or not isinstance(raw_duration, int):
        raise TrainingProgramValidationError(
            "Thời lượng học kỳ (duration_semesters) phải là số nguyên dương.",
            code="INVALID_PARAMS",
        )
    if raw_duration <= 0 or raw_duration > 65535:
        raise TrainingProgramValidationError(
            "Thời lượng học kỳ (duration_semesters) phải là số nguyên dương từ 1 đến 65535.",
            code="INVALID_PARAMS",
        )
    return raw_duration


def validate_program_status(raw_status: Any, default: str = PROGRAM_STATUS_DRAFT) -> str:
    """Kiểm tra và chuẩn hóa trạng thái chương trình (status)."""
    if raw_status is None:
        return default
    if isinstance(raw_status, bool) or not isinstance(raw_status, str):
        raise TrainingProgramValidationError(
            "Trạng thái chương trình không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned = raw_status.strip().lower()
    if not cleaned:
        return default
    if cleaned not in VALID_PROGRAM_STATUSES:
        allowed = ", ".join(sorted(VALID_PROGRAM_STATUSES))
        raise TrainingProgramValidationError(
            f"Trạng thái không hợp lệ: '{cleaned}'. Cho phép: {allowed}.",
            code="INVALID_PARAMS",
        )
    return cleaned


def validate_patch_status(raw_status: Any) -> str:
    """Kiểm tra trạng thái chương trình khi PATCH (bắt buộc phải là giá trị hợp lệ, không cho phép null/rỗng)."""
    if raw_status is None or isinstance(raw_status, bool) or not isinstance(raw_status, str):
        raise TrainingProgramValidationError(
            "Trạng thái chương trình không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned = raw_status.strip().lower()
    if not cleaned or cleaned not in VALID_PROGRAM_STATUSES:
        allowed = ", ".join(sorted(VALID_PROGRAM_STATUSES))
        raise TrainingProgramValidationError(
            f"Trạng thái không hợp lệ: '{cleaned}'. Cho phép: {allowed}.",
            code="INVALID_PARAMS",
        )
    return cleaned


def create_training_program_service(data: dict) -> dict:
    """
    Nghiệp vụ tạo mới một chương trình đào tạo (SCRUM-122 - Activity A3).
    Quy tắc nghiệp vụ & validation:
    1. data phải là dict hợp lệ.
    2. code: Bắt buộc, không rỗng, tối đa 50 ký tự, không trùng trong database.
    3. name: Bắt buộc, không rỗng, tối đa 255 ký tự.
    4. description: Tùy chọn, chuỗi ký tự hoặc None.
    5. duration_semesters: Tùy chọn, số nguyên dương (1-65535) hoặc None.
    6. status: Tùy chọn, mặc định 'draft', nhận: draft, active, archived.
    7. id, created_at, updated_at: Backend tự sinh và quản lý bằng UUID v4 & UTC.
    """
    if not isinstance(data, dict):
        raise TrainingProgramValidationError(
            "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
            code="INVALID_JSON",
        )

    cleaned_code = validate_program_code(data.get("code"))
    cleaned_name = validate_program_name(data.get("name"))
    cleaned_desc = validate_program_description(data.get("description"))
    cleaned_duration = validate_program_duration(data.get("duration_semesters"))
    cleaned_status = validate_program_status(data.get("status"), default=PROGRAM_STATUS_DRAFT)

    # Kiểm tra trùng mã code ở tầng service
    if training_program_repository.exists_by_code(cleaned_code):
        raise DuplicateProgramCodeError()

    # Khởi tạo đối tượng với UUID v4 và UTC timestamp do backend sinh
    program_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    program = TrainingProgram(
        id=program_id,
        code=cleaned_code,
        name=cleaned_name,
        description=cleaned_desc,
        duration_semesters=cleaned_duration,
        status=cleaned_status,
        created_at=now,
        updated_at=now,
    )

    # Lưu vào database và bắt lỗi IntegrityError phòng ngừa race condition
    try:
        created_program = training_program_repository.insert_training_program(program)
    except IntegrityError as err:
        err_msg = str(err).lower()
        if getattr(err, "errno", None) == 1062 or "duplicate" in err_msg or "code" in err_msg or "unique" in err_msg:
            raise DuplicateProgramCodeError()
        raise
    except Exception as err:
        err_msg = str(err).lower()
        if "duplicate" in err_msg or "1062" in err_msg or "unique" in err_msg:
            raise DuplicateProgramCodeError()
        raise

    return created_program.to_dict()


def update_training_program_service(program_id: str, data: dict) -> dict:
    """
    Nghiệp vụ cập nhật toàn bộ thông tin một chương trình đào tạo (SCRUM-122 - Activity A4 - PUT).
    - Validate program_id (định dạng UUID, tồn tại trong database).
    - Validate data (phải là dict).
    - code và name bắt buộc.
    - description, duration_semesters, status xử lý theo quy tắc chuẩn:
      nếu không gửi -> description=None, duration_semesters=None, status='draft'.
    - Không cho phép cập nhật id hoặc created_at.
    - Cập nhật updated_at theo UTC.
    - Kiểm tra mã code trùng lặp (ngoại trừ chính chương trình này).
    """
    if not isinstance(program_id, str) or not program_id.strip():
        raise TrainingProgramValidationError(
            "Mã định danh chương trình đào tạo không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned_id = program_id.strip()
    if not is_valid_uuid(cleaned_id):
        raise TrainingProgramValidationError(
            "Mã định danh chương trình đào tạo không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(data, dict):
        raise TrainingProgramValidationError(
            "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
            code="INVALID_JSON",
        )

    existing = training_program_repository.get_training_program_by_id(cleaned_id)
    if existing is None:
        raise TrainingProgramNotFoundError("Không tìm thấy chương trình đào tạo.")

    cleaned_code = validate_program_code(data.get("code"))
    cleaned_name = validate_program_name(data.get("name"))
    cleaned_desc = validate_program_description(data.get("description"))
    cleaned_duration = validate_program_duration(data.get("duration_semesters"))
    cleaned_status = validate_program_status(data.get("status"), default=PROGRAM_STATUS_DRAFT)

    if cleaned_code != existing.code:
        if training_program_repository.exists_by_code(cleaned_code, exclude_id=cleaned_id):
            raise DuplicateProgramCodeError()

    now = datetime.now(timezone.utc)
    program_to_update = TrainingProgram(
        id=cleaned_id,
        code=cleaned_code,
        name=cleaned_name,
        description=cleaned_desc,
        duration_semesters=cleaned_duration,
        status=cleaned_status,
        created_at=existing.created_at,
        updated_at=now,
    )

    try:
        updated = training_program_repository.update_training_program(program_to_update)
    except IntegrityError as err:
        err_msg = str(err).lower()
        if getattr(err, "errno", None) == 1062 or "duplicate" in err_msg or "code" in err_msg or "unique" in err_msg:
            raise DuplicateProgramCodeError()
        raise
    except Exception as err:
        err_msg = str(err).lower()
        if "duplicate" in err_msg or "1062" in err_msg or "unique" in err_msg:
            raise DuplicateProgramCodeError()
        raise

    return updated.to_dict()


def patch_training_program_service(program_id: str, data: dict) -> dict:
    """
    Nghiệp vụ cập nhật từng phần thông tin một chương trình đào tạo (SCRUM-122 - Activity A4 - PATCH).
    - Validate program_id (định dạng UUID, tồn tại trong database).
    - Validate data (phải là dict, không được rỗng).
    - Chỉ cập nhật các trường được gửi:
      code, name, description, duration_semesters, status.
    - Các trường không gửi được giữ nguyên tuyệt đối.
    - Bỏ qua id, created_at, updated_at do client truyền.
    - Cập nhật updated_at theo UTC.
    - Kiểm tra mã code trùng lặp (ngoại trừ chính chương trình này).
    """
    if not isinstance(program_id, str) or not program_id.strip():
        raise TrainingProgramValidationError(
            "Mã định danh chương trình đào tạo không hợp lệ.",
            code="INVALID_PARAMS",
        )
    cleaned_id = program_id.strip()
    if not is_valid_uuid(cleaned_id):
        raise TrainingProgramValidationError(
            "Mã định danh chương trình đào tạo không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(data, dict):
        raise TrainingProgramValidationError(
            "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
            code="INVALID_JSON",
        )

    if not data:
        raise TrainingProgramValidationError(
            "Dữ liệu yêu cầu không được để trống.",
            code="INVALID_PARAMS",
        )

    existing = training_program_repository.get_training_program_by_id(cleaned_id)
    if existing is None:
        raise TrainingProgramNotFoundError("Không tìm thấy chương trình đào tạo.")

    fields_to_update: dict[str, Any] = {}

    if "code" in data:
        cleaned_code = validate_program_code(data["code"])
        if cleaned_code != existing.code:
            if training_program_repository.exists_by_code(cleaned_code, exclude_id=cleaned_id):
                raise DuplicateProgramCodeError()
        fields_to_update["code"] = cleaned_code

    if "name" in data:
        fields_to_update["name"] = validate_program_name(data["name"])

    if "description" in data:
        fields_to_update["description"] = validate_program_description(data["description"])

    if "duration_semesters" in data:
        fields_to_update["duration_semesters"] = validate_program_duration(data["duration_semesters"])

    if "status" in data:
        fields_to_update["status"] = validate_patch_status(data["status"])

    if not fields_to_update:
        raise TrainingProgramValidationError(
            "Không có trường dữ liệu nào hợp lệ để cập nhật.",
            code="INVALID_PARAMS",
        )

    try:
        updated = training_program_repository.update_training_program_fields(cleaned_id, fields_to_update)
    except IntegrityError as err:
        err_msg = str(err).lower()
        if getattr(err, "errno", None) == 1062 or "duplicate" in err_msg or "code" in err_msg or "unique" in err_msg:
            raise DuplicateProgramCodeError()
        raise
    except Exception as err:
        err_msg = str(err).lower()
        if "duplicate" in err_msg or "1062" in err_msg or "unique" in err_msg:
            raise DuplicateProgramCodeError()
        raise

    if updated is None:
        raise TrainingProgramNotFoundError("Không tìm thấy chương trình đào tạo.")

    return updated.to_dict()

