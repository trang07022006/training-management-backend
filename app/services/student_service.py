"""
Tầng nghiệp vụ Quản lý Học viên và Chuyển đổi Lead (Student Service) - SCRUM-215.
"""

from datetime import datetime, timezone
import logging
import uuid
from app.models.student import Student
from app.repositories import lead_repository, student_repository

logger = logging.getLogger(__name__)


class StudentServiceError(Exception):
    """Lớp ngoại lệ cơ sở cho nghiệp vụ Student."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LeadNotFoundError(StudentServiceError):
    def __init__(self, message: str = "Không tìm thấy khách hàng tiềm năng."):
        super().__init__("LEAD_NOT_FOUND", message, status_code=404)


class LeadNotWonError(StudentServiceError):
    def __init__(self, message: str = "Chỉ có thể chuyển đổi Lead có trạng thái Chốt sang hồ sơ học viên."):
        super().__init__("LEAD_NOT_WON", message, status_code=400)


class LeadAlreadyConvertedError(StudentServiceError):
    def __init__(self, message: str = "Lead này đã được chuyển thành hồ sơ học viên trước đó."):
        super().__init__("LEAD_ALREADY_CONVERTED", message, status_code=400)


def convert_lead_to_student_service(lead_id: str, actor_user_id: str | None = None) -> dict:
    """
    Chuyển đổi dữ liệu Lead đã chốt sang Hồ sơ học viên (SCRUM-215 - Sub-task 215-01).
    - Tái sử dụng toàn bộ thông tin Lead (full_name, phone, email, interested_program_id).
    - Không bắt nhập lại dữ liệu.
    - Chống thao tác lặp (Idempotent guard).
    - Tạo bản ghi Student thật trong database.
    """
    lead = lead_repository.get_lead_by_id(lead_id)
    if not lead:
        raise LeadNotFoundError()

    # Kiểm tra Lead phải ở trạng thái Chốt (won)
    if lead.status != "won":
        raise LeadNotWonError()

    # Kiểm tra trùng lặp
    existing_student = student_repository.get_student_by_lead_id(lead_id)
    if existing_student:
        raise LeadAlreadyConvertedError()

    # Sinh mã học viên tự động và tạo Student (có cơ chế retry nếu gặp xung đột mã)
    student_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    max_retries = 3
    created_student = None
    student_code = ""

    for attempt in range(max_retries):
        student_code = student_repository.generate_next_student_code()
        student = Student(
            id=student_id,
            student_code=student_code,
            full_name=lead.full_name,
            phone=lead.phone,
            email=lead.email,
            program_id=lead.interested_program_id,
            lead_id=lead.id,
            status="enrolled",
            created_at=now,
            updated_at=now,
        )
        try:
            created_student = student_repository.create_student(student)
            break
        except Exception as e:
            if "uq_students_student_code" in str(e) and attempt < max_retries - 1:
                logger.warning("Collision on student_code %s, retrying with next code...", student_code)
                continue
            raise

    # Lấy thông tin đầy đủ sau khi tạo (kèm tên chương trình đào tạo)
    full_student = student_repository.get_student_by_id(created_student.id) or created_student

    logger.info(
        "Chuyển đổi Lead %s thành Student %s (Code: %s) thành công bởi actor %s",
        lead_id,
        student_id,
        student_code,
        actor_user_id,
    )

    return {
        "student": full_student.to_dict(),
        "lead": lead.to_dict(),
    }
