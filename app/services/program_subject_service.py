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


class ProgramSubjectInUseError(ProgramSubjectServiceError):
    """Ngoại lệ khi môn học đang là điều kiện tiên quyết cho môn khác trong chương trình (409)."""

    def __init__(self, message: str = "Không thể gỡ môn học đang là điều kiện tiên quyết của môn khác trong chương trình"):
        super().__init__("PROGRAM_SUBJECT_IN_USE", message, status_code=409)


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


def add_subject_to_program_service(
    program_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Nghiệp vụ thêm môn học vào chương trình đào tạo (SCRUM-124 - Activity A3).
    - Kiểm tra tính hợp lệ UUID, sự tồn tại của program và subject
    - Kiểm tra trạng thái program và subject (chống thêm vào program archived, chống thêm subject archived, chống thêm subject draft vào program active)
    - Kiểm tra chống trùng lặp môn trong cùng một chương trình
    - Kiểm tra học kỳ (semester <= duration_semesters nếu có)
    - Kiểm tra tính bắt buộc (is_mandatory phải là boolean)
    - Tự động chuẩn hóa order_index và lưu dữ liệu an toàn trong transaction
    """
    if not is_valid_uuid(program_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã chương trình đào tạo không hợp lệ", status_code=400)

    program = training_program_repository.get_training_program_by_id(program_id.strip())
    if not program:
        raise ProgramNotFoundError()

    # Chính sách trạng thái chương trình đào tạo
    if program.status == "archived":
        raise ProgramSubjectServiceError(
            "ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED",
            "Không thể thêm môn học vào chương trình đào tạo đã lưu trữ",
            status_code=400,
        )

    if not isinstance(data, dict):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Dữ liệu yêu cầu không hợp lệ", status_code=400)

    subject_id = data.get("subject_id")
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã môn học không hợp lệ", status_code=400)

    subject = subject_repository.get_subject_by_id(subject_id.strip())
    if not subject:
        raise SubjectNotFoundError()

    # Chính sách trạng thái môn học
    if subject.status == "archived":
        raise ProgramSubjectServiceError(
            "ARCHIVED_SUBJECT_CANNOT_BE_ADDED",
            "Không thể thêm môn học đã lưu trữ vào chương trình đào tạo",
            status_code=400,
        )

    if program.status == "active" and subject.status == "draft":
        raise ProgramSubjectServiceError(
            "DRAFT_SUBJECT_NOT_ALLOWED_IN_ACTIVE_PROGRAM",
            "Chương trình đang áp dụng (active) chỉ được phép thêm môn học đã kích hoạt (active)",
            status_code=400,
        )

    # Chống trùng lặp môn trong chương trình
    if program_subject_repository.exists_program_subject(program.id, subject.id):
        raise ProgramSubjectServiceError(
            "SUBJECT_ALREADY_IN_PROGRAM",
            "Môn học đã tồn tại trong chương trình đào tạo",
            status_code=409,
        )

    # Validate semester
    semester = None
    if "semester" in data and data["semester"] is not None:
        sem_raw = data["semester"]
        try:
            semester = int(sem_raw)
            if semester < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Học kỳ phải là số nguyên dương lớn hơn hoặc bằng 1", status_code=400)

        if program.duration_semesters is not None and semester > program.duration_semesters:
            raise ProgramSubjectServiceError(
                "SEMESTER_EXCEEDS_PROGRAM_DURATION",
                f"Học kỳ ({semester}) không được vượt quá thời lượng chương trình ({program.duration_semesters} học kỳ)",
                status_code=400,
            )

    # Validate is_mandatory (bắt buộc phải là kiểu boolean thực sự, không nhận string "true")
    is_mandatory = True
    if "is_mandatory" in data and data["is_mandatory"] is not None:
        mand_val = data["is_mandatory"]
        if not isinstance(mand_val, bool):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Giá trị tính bắt buộc (is_mandatory) phải là kiểu boolean", status_code=400)
        is_mandatory = mand_val

    # Validate order_index
    order_index = None
    if "order_index" in data and data["order_index"] is not None:
        order_raw = data["order_index"]
        try:
            order_index = int(order_raw)
            if order_index < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Thứ tự học (order_index) phải là số nguyên dương lớn hơn hoặc bằng 1", status_code=400)

    new_ps = ProgramSubject(
        id=str(uuid.uuid4()),
        program_id=program.id,
        subject_id=subject.id,
        semester=semester,
        is_mandatory=is_mandatory,
        order_index=order_index or 1,
    )
    saved = program_subject_repository.insert_program_subject_ordered(new_ps, requested_order=order_index)

    return {
        "program_subject_id": saved.id,
        "program_id": saved.program_id,
        "subject_id": saved.subject_id,
        "subject_code": saved.subject_code,
        "subject_name": saved.subject_name,
        "credits": saved.subject_credits,
        "total_sessions": saved.subject_total_sessions,
        "subject_status": saved.subject_status,
        "semester": saved.semester,
        "is_mandatory": saved.is_mandatory,
        "order_index": saved.order_index,
        "created_at": saved.created_at.isoformat() if saved.created_at else None,
        "updated_at": saved.updated_at.isoformat() if saved.updated_at else None,
    }


def update_program_subject_service(
    program_id: str,
    program_subject_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Nghiệp vụ cập nhật metadata của một môn trong chương trình đào tạo (SCRUM-124 - Activity A3 - PATCH).
    - Cho phép cập nhật: semester, is_mandatory, order_index
    - Bỏ qua các trường hệ thống: id, program_id, subject_id, created_at
    - Kiểm tra trạng thái chương trình đào tạo (chống sửa program archived)
    - Tự động chuẩn hóa thứ tự học trong cả học kỳ cũ và mới
    """
    if not is_valid_uuid(program_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã chương trình đào tạo không hợp lệ", status_code=400)
    if not is_valid_uuid(program_subject_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã liên kết môn học không hợp lệ", status_code=400)

    program = training_program_repository.get_training_program_by_id(program_id.strip())
    if not program:
        raise ProgramNotFoundError()

    if program.status == "archived":
        raise ProgramSubjectServiceError(
            "ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED",
            "Không thể chỉnh sửa cấu trúc của chương trình đào tạo đã lưu trữ",
            status_code=400,
        )

    existing = program_subject_repository.get_program_subject_by_id(program_subject_id.strip())
    if not existing or existing.program_id != program.id:
        raise ProgramSubjectNotFoundError()

    if not isinstance(data, dict):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Dữ liệu yêu cầu không hợp lệ", status_code=400)

    fields_to_update: dict[str, Any] = {}

    if "semester" in data:
        sem_val = data["semester"]
        if sem_val is not None:
            try:
                sem_int = int(sem_val)
                if sem_int < 1:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ProgramSubjectServiceError("INVALID_PARAMS", "Học kỳ phải là số nguyên dương lớn hơn hoặc bằng 1", status_code=400)
            if program.duration_semesters is not None and sem_int > program.duration_semesters:
                raise ProgramSubjectServiceError(
                    "SEMESTER_EXCEEDS_PROGRAM_DURATION",
                    f"Học kỳ ({sem_int}) không được vượt quá thời lượng chương trình ({program.duration_semesters} học kỳ)",
                    status_code=400,
                )
            fields_to_update["semester"] = sem_int
        else:
            fields_to_update["semester"] = None

    if "is_mandatory" in data:
        mand_val = data["is_mandatory"]
        if not isinstance(mand_val, bool):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Giá trị tính bắt buộc (is_mandatory) phải là kiểu boolean", status_code=400)
        fields_to_update["is_mandatory"] = mand_val

    if "order_index" in data:
        order_val = data["order_index"]
        try:
            order_int = int(order_val)
            if order_int < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Thứ tự học (order_index) phải là số nguyên dương lớn hơn hoặc bằng 1", status_code=400)
        fields_to_update["order_index"] = order_int

    updated = program_subject_repository.update_program_subject_fields(existing.id, fields_to_update)
    if not updated:
        raise ProgramSubjectNotFoundError()

    return {
        "program_subject_id": updated.id,
        "program_id": updated.program_id,
        "subject_id": updated.subject_id,
        "subject_code": updated.subject_code,
        "subject_name": updated.subject_name,
        "credits": updated.subject_credits,
        "total_sessions": updated.subject_total_sessions,
        "subject_status": updated.subject_status,
        "semester": updated.semester,
        "is_mandatory": updated.is_mandatory,
        "order_index": updated.order_index,
        "created_at": updated.created_at.isoformat() if updated.created_at else None,
        "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
    }


def reorder_program_subjects_service(
    program_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Nghiệp vụ sắp xếp lại thứ tự học các môn trong chương trình đào tạo (SCRUM-124 - Activity A4 - PATCH reorder).
    - Hỗ trợ cả 2 format: `ordered_ids: [...]` hoặc `items: [{program_subject_id: ..., order_index: ...}, ...]`
    - Kiểm tra tính hợp lệ UUID, chống trùng lặp ID
    - Kiểm tra tất cả các môn phải thuộc cùng chương trình (và cùng học kỳ nếu có chỉ định)
    - Thực thi trong transaction nguyên tử (atomic), rollback toàn bộ nếu có lỗi
    - Chuẩn hóa dãy thứ tự 1..N
    """
    if not is_valid_uuid(program_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã chương trình đào tạo không hợp lệ", status_code=400)

    program = training_program_repository.get_training_program_by_id(program_id.strip())
    if not program:
        raise ProgramNotFoundError()

    if program.status == "archived":
        raise ProgramSubjectServiceError(
            "ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED",
            "Không thể sắp xếp lại môn học của chương trình đào tạo đã lưu trữ",
            status_code=400,
        )

    if not isinstance(data, dict):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Dữ liệu yêu cầu không hợp lệ", status_code=400)

    semester = None
    if "semester" in data and data["semester"] is not None:
        try:
            semester = int(data["semester"])
            if semester < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProgramSubjectServiceError("INVALID_PARAMS", "Học kỳ không hợp lệ", status_code=400)

    # Trích xuất danh sách ID
    if "ordered_ids" in data and isinstance(data["ordered_ids"], list):
        id_list = data["ordered_ids"]
    elif "items" in data and isinstance(data["items"], list):
        sorted_items = sorted(data["items"], key=lambda x: int(x.get("order_index", 0)) if isinstance(x, dict) else 0)
        id_list = [it.get("program_subject_id") for it in sorted_items if isinstance(it, dict)]
    else:
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Dữ liệu danh sách sắp xếp không hợp lệ", status_code=400)

    if not id_list or not isinstance(id_list, list):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Danh sách môn học sắp xếp không được để trống", status_code=400)

    # Chống trùng lặp ID
    if len(id_list) != len(set(id_list)):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Danh sách ID môn học bị trùng lặp", status_code=400)

    # Kiểm tra từng phần tử
    for ps_id in id_list:
        if not isinstance(ps_id, str) or not is_valid_uuid(ps_id):
            raise ProgramSubjectServiceError("INVALID_PARAMS", f"ID môn học không hợp lệ: {ps_id}", status_code=400)
        ps_obj = program_subject_repository.get_program_subject_by_id(ps_id.strip())
        if not ps_obj or ps_obj.program_id != program.id:
            raise ProgramSubjectServiceError("INVALID_PARAMS", f"Môn học {ps_id} không thuộc chương trình đào tạo", status_code=400)
        if semester is not None and ps_obj.semester != semester:
            raise ProgramSubjectServiceError(
                "INVALID_PARAMS",
                f"Môn học {ps_id} thuộc học kỳ {ps_obj.semester}, không khớp với học kỳ yêu cầu {semester}",
                status_code=400,
            )

    program_subject_repository.reorder_program_subjects(program.id, semester, id_list)
    return get_program_structure_service(program.id, semester_raw=semester)


def remove_program_subject_service(
    program_id: str,
    program_subject_id: str,
) -> dict[str, Any]:
    """
    Nghiệp vụ gỡ môn học khỏi chương trình đào tạo an toàn (SCRUM-124 - Activity A4 - DELETE).
    - Chỉ xóa dòng liên kết program_subjects, giữ nguyên môn học và chương trình đào tạo master
    - Nếu môn học đang làm prerequisite target của môn khác trong chương trình -> chặn (409 PROGRAM_SUBJECT_IN_USE)
    - Tự động chuẩn hóa lại thứ tự (order_index) trong học kỳ liên quan sau khi gỡ
    """
    if not is_valid_uuid(program_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã chương trình đào tạo không hợp lệ", status_code=400)
    if not is_valid_uuid(program_subject_id):
        raise ProgramSubjectServiceError("INVALID_PARAMS", "Mã liên kết môn học không hợp lệ", status_code=400)

    program = training_program_repository.get_training_program_by_id(program_id.strip())
    if not program:
        raise ProgramNotFoundError()

    if program.status == "archived":
        raise ProgramSubjectServiceError(
            "ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED",
            "Không thể gỡ môn học khỏi chương trình đào tạo đã lưu trữ",
            status_code=400,
        )

    ps_obj = program_subject_repository.get_program_subject_by_id(program_subject_id.strip())
    if not ps_obj or ps_obj.program_id != program.id:
        raise ProgramSubjectNotFoundError()

    # Kiểm tra xem môn này có đang là môn tiên quyết cho môn khác hay không
    if program_subject_repository.is_prerequisite_target(ps_obj.id):
        raise ProgramSubjectInUseError(
            "Môn học đang là điều kiện tiên quyết của môn khác trong chương trình. Hãy gỡ ràng buộc tiên quyết trước."
        )

    old_semester = ps_obj.semester
    removed = program_subject_repository.remove_program_subject(ps_obj.id)
    if not removed:
        raise ProgramSubjectNotFoundError()

    # Chuẩn hóa lại thứ tự trong học kỳ
    program_subject_repository.normalize_order_indices(program.id, old_semester)

    return {
        "message": "Đã gỡ môn học khỏi chương trình đào tạo thành công",
        "removed_program_subject_id": ps_obj.id,
    }


