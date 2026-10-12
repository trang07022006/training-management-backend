"""
Service xử lý nghiệp vụ Ghi danh học viên vào lớp (Enrollment Service) - SCRUM-218.
- Ghi danh đơn lẻ và hàng loạt (218-01)
- Chặn lớp đầy và học viên đã có trong lớp (218-02)
- Ghi nhận ngày ghi danh và người thực hiện từ token (218-03)
"""

from datetime import datetime, timezone
import logging
import uuid

from app.models.enrollment import Enrollment
from app.repositories import class_repository, enrollment_repository, student_repository

logger = logging.getLogger(__name__)


class EnrollmentServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ClassNotFoundError(EnrollmentServiceError):
    def __init__(self, message: str = "Không tìm thấy thông tin lớp học."):
        super().__init__("CLASS_NOT_FOUND", message, status_code=404)


class StudentNotFoundError(EnrollmentServiceError):
    def __init__(self, message: str = "Không tìm thấy học viên tương ứng."):
        super().__init__("STUDENT_NOT_FOUND", message, status_code=404)


class ClassCapacityFullError(EnrollmentServiceError):
    def __init__(self, message: str = "Lớp học đã đạt sĩ số tối đa."):
        super().__init__("CLASS_CAPACITY_FULL", message, status_code=400)


class StudentAlreadyEnrolledError(EnrollmentServiceError):
    def __init__(self, message: str = "Học viên đã được ghi danh vào lớp học này."):
        super().__init__("STUDENT_ALREADY_ENROLLED", message, status_code=400)


class EnrollmentValidationError(EnrollmentServiceError):
    def __init__(self, message: str = "Dữ liệu ghi danh không hợp lệ."):
        super().__init__("VALIDATION_ERROR", message, status_code=400)


def enroll_students_service(class_id: str, payload: dict, actor_user_id: str) -> dict:
    """
    Ghi danh học viên vào lớp học (đơn lẻ hoặc hàng loạt).
    - class_id: ID lớp học
    - payload: {"student_id": "..."} hoặc {"student_ids": ["...", "..."]}
    - actor_user_id: ID người thực hiện lấy từ token JWT
    """
    # 1. Kiểm tra lớp học có tồn tại
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ClassNotFoundError()

    # 2. Thu thập danh sách student_id
    raw_student_ids = []
    if "student_ids" in payload:
        ids_input = payload.get("student_ids")
        if not isinstance(ids_input, list):
            raise EnrollmentValidationError("Danh sách student_ids phải là một mảng.")
        raw_student_ids = ids_input
    elif "student_id" in payload:
        single_id = payload.get("student_id")
        if not isinstance(single_id, str) or not single_id.strip():
            raise EnrollmentValidationError("student_id không được để trống.")
        raw_student_ids = [single_id.strip()]
    else:
        raise EnrollmentValidationError("Yêu cầu cung cấp student_id hoặc student_ids.")

    # Lọc bỏ trùng lặp trong chính payload và làm sạch dữ liệu
    student_ids: list[str] = []
    for sid in raw_student_ids:
        if isinstance(sid, str) and sid.strip():
            clean_id = sid.strip()
            if clean_id not in student_ids:
                student_ids.append(clean_id)

    if not student_ids:
        raise EnrollmentValidationError("Vui lòng chọn ít nhất một học viên để ghi danh.")

    # 3. Kiểm tra các học viên có tồn tại trong hệ thống
    for sid in student_ids:
        student = student_repository.get_student_by_id(sid)
        if not student:
            raise StudentNotFoundError(f"Không tìm thấy học viên với ID '{sid}'.")

    # 4. Kiểm tra học viên đã được ghi danh vào lớp chưa (RULE 2: Duplicate Guard)
    already_enrolled = enrollment_repository.get_already_enrolled_student_ids(class_id, student_ids)
    if already_enrolled:
        # Lấy thông tin học viên đầu tiên bị trùng để hiển thị thông báo chi tiết
        dup_student = student_repository.get_student_by_id(already_enrolled[0])
        student_desc = f"'{dup_student.full_name}' ({dup_student.student_code})" if dup_student else already_enrolled[0]
        raise StudentAlreadyEnrolledError(
            f"Học viên {student_desc} đã được ghi danh vào lớp học này."
        )

    # 5. Kiểm tra sĩ số lớp học (RULE 1: Capacity Guard)
    current_enrolled = enrollment_repository.count_enrollments_by_class_id(class_id)
    requested_count = len(student_ids)
    if current_enrolled + requested_count > class_obj.max_capacity:
        raise ClassCapacityFullError(
            f"Số lượng học viên ghi danh ({requested_count}) vượt quá sĩ số còn lại của lớp. "
            f"Hiện tại lớp đã có {current_enrolled}/{class_obj.max_capacity} học viên."
        )

    # 6. Tạo danh sách Enrollment objects và ghi nhận audit
    now = datetime.now(timezone.utc)
    enrollments_to_create = [
        Enrollment(
            id=str(uuid.uuid4()),
            class_id=class_id,
            student_id=sid,
            status="enrolled",
            enrolled_at=now,
            enrolled_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        for sid in student_ids
    ]

    # 7. Lưu vào database với transaction all-or-nothing
    created = enrollment_repository.create_enrollments(enrollments_to_create)

    logger.info(
        "Ghi danh thành công %d học viên vào lớp %s (%s) bởi actor %s",
        len(created),
        class_obj.class_code,
        class_id,
        actor_user_id,
    )

    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "enrolled_count": len(created),
        "total_enrolled": current_enrolled + len(created),
        "max_capacity": class_obj.max_capacity,
        "items": [c.to_dict() for c in created],
    }


def get_class_roster_service(class_id: str) -> dict:
    """Lấy danh sách học viên trong lớp (Class Roster) kèm thông tin chi tiết."""
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ClassNotFoundError()

    enrollments = enrollment_repository.get_enrollments_by_class_id(class_id)
    return {
        "class": class_obj.to_dict(),
        "items": [e.to_dict() for e in enrollments],
        "total": len(enrollments),
    }
