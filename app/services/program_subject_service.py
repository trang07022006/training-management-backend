from datetime import datetime, timezone
from typing import Any
import uuid

from app.models.program_subject import ProgramSubject
from app.models.program_subject_prerequisite import ProgramSubjectPrerequisite
from app.repositories import (
    program_subject_repository,
    subject_repository,
    training_program_repository,
)


def is_valid_uuid(val: str) -> bool:
    """Kiểm tra chuỗi có đúng định dạng UUID hay không."""
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        parsed = uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError, AttributeError):
        return False


class ProgramSubjectServiceError(Exception):
    """Lớp ngoại lệ cơ sở cho nghiệp vụ cấu trúc chương trình đào tạo."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProgramNotFoundError(ProgramSubjectServiceError):
    """Ngoại lệ khi không tìm thấy chương trình đào tạo (404)."""

    def __init__(self, message: str = "Chương trình đào tạo không tồn tại"):
        super().__init__("PROGRAM_NOT_FOUND", message, status_code=404)


class SubjectNotFoundError(ProgramSubjectServiceError):
    """Ngoại lệ khi không tìm thấy môn học (404)."""

    def __init__(self, message: str = "Môn học không tồn tại"):
        super().__init__("SUBJECT_NOT_FOUND", message, status_code=404)


class ProgramSubjectNotFoundError(ProgramSubjectServiceError):
    """Ngoại lệ khi không tìm thấy môn học trong chương trình đào tạo (404)."""

    def __init__(self, message: str = "Môn học không tồn tại trong chương trình đào tạo"):
        super().__init__("PROGRAM_SUBJECT_NOT_FOUND", message, status_code=404)


def get_program_structure_service(
    program_id: str,
    semester_raw: Any = None,
    is_mandatory_raw: Any = None,
) -> dict[str, Any]:
    """
    Nghiệp vụ lấy danh sách và cấu trúc môn học của một chương trình đào tạo (SCRUM-124 - Activity A2).
    - Kiểm tra tính hợp lệ của program_id UUID
    - Kiểm tra chương trình đào tạo có tồn tại hay không
    - Hỗ trợ lọc theo semester và is_mandatory nếu có
    - Trả về thông tin tóm tắt chương trình, tổng số môn, tổng tín chỉ và danh sách môn chi tiết kèm prerequisites
    """
    if not is_valid_uuid(program_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã chương trình đào tạo không hợp lệ", status_code=400)

    program = training_program_repository.get_training_program_by_id(program_id.strip())
    if not program:
        raise ProgramNotFoundError()

    # Xử lý bộ lọc semester nếu có
    target_semester = None
    if semester_raw is not None and str(semester_raw).strip() != "":
        try:
            target_semester = int(semester_raw)
            if target_semester < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Tham số học kỳ không hợp lệ", status_code=400)

    # Xử lý bộ lọc is_mandatory nếu có
    target_mandatory = None
    if is_mandatory_raw is not None and str(is_mandatory_raw).strip() != "":
        val_str = str(is_mandatory_raw).strip().lower()
        if val_str in ("true", "1"):
            target_mandatory = True
        elif val_str in ("false", "0"):
            target_mandatory = False
        else:
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Tham số tính bắt buộc không hợp lệ", status_code=400)

    items = program_subject_repository.get_program_structure(program.id)

    # Lọc kết quả nếu có điều kiện query
    if target_semester is not None:
        items = [it for it in items if it.semester == target_semester]
    if target_mandatory is not None:
        items = [it for it in items if it.is_mandatory is target_mandatory]

    total_subjects = len(items)
    total_credits = sum(it.subject_credits or 0 for it in items)

    formatted_items = [
        {
            "program_subject_id": it.id,
            "subject_id": it.subject_id,
            "subject_code": it.subject_code,
            "subject_name": it.subject_name,
            "credits": it.subject_credits,
            "total_sessions": it.subject_total_sessions,
            "subject_status": it.subject_status,
            "semester": it.semester,
            "is_mandatory": it.is_mandatory,
            "order_index": it.order_index,
            "prerequisites": it.prerequisites,
        }
        for it in items
    ]

    return {
        "program": {
            "id": program.id,
            "code": program.code,
            "name": program.name,
            "status": program.status,
            "duration_semesters": program.duration_semesters,
        },
        "total_subjects": total_subjects,
        "total_credits": total_credits,
        "items": formatted_items,
    }
