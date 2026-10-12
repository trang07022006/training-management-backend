"""
Tầng nghiệp vụ Quản lý Học viên và Chuyển đổi Lead (Student Service) - SCRUM-215.
"""

from datetime import datetime, timezone
import logging
import secrets
import uuid
from werkzeug.security import generate_password_hash
from app.models.student import Student
from app.models.user import User
from app.repositories import (
    lead_repository,
    role_repository,
    student_repository,
    user_repository,
    user_role_repository,
)
from app.services import email_service

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
    Chuyển đổi dữ liệu Lead đã chốt sang Hồ sơ học viên (SCRUM-215).
    - Tái sử dụng toàn bộ thông tin Lead (full_name, phone, email, interested_program_id).
    - Tự động sinh mã học viên chuẩn hệ thống (215-02).
    - Tạo tài khoản người dùng đăng nhập cho học viên và gửi email (215-03).
    - Chống thao tác lặp (Idempotent guard).
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

    now = datetime.now(timezone.utc)

    # 1. Tạo hoặc liên kết tài khoản đăng nhập cho học viên (Sub-task 215-03)
    user_id = None
    account_created = False
    email_sent = False
    raw_password = None

    if lead.email and lead.email.strip():
        norm_email = lead.email.strip().lower()
        existing_user = user_repository.get_user_by_email(norm_email)
        if existing_user:
            user_id = existing_user.id
            account_created = False
            # Đảm bảo gán vai trò học viên (trainee) nếu chưa có
            role_obj = role_repository.get_role_by_code("trainee")
            if role_obj:
                existing_roles = user_role_repository.get_roles_by_user_id(user_id)
                if not any(r.id == role_obj.id for r in existing_roles):
                    user_role_repository.assign_role_to_user(user_id, role_obj.id)
        else:
            user_id = str(uuid.uuid4())
            raw_password = f"Hv@{secrets.token_hex(4)}"
            password_hash = generate_password_hash(raw_password)
            new_user = User(
                id=user_id,
                email=norm_email,
                password_hash=password_hash,
                name=lead.full_name,
                phone=lead.phone,
                role="trainee",
                status="active",
                failed_login_attempts=0,
                created_at=now,
                updated_at=now,
            )
            try:
                user_repository.create_user(new_user)
                account_created = True
                role_obj = role_repository.get_role_by_code("trainee")
                if role_obj:
                    user_role_repository.assign_role_to_user(user_id, role_obj.id)
            except Exception as e:
                err_msg = str(e).lower()
                if "duplicate" in err_msg or "1062" in err_msg:
                    fallback_user = user_repository.get_user_by_email(norm_email)
                    if fallback_user:
                        user_id = fallback_user.id
                        account_created = False
                else:
                    raise

    # 2. Sinh mã học viên tự động và tạo Student (có cơ chế retry nếu gặp xung đột mã)
    student_id = str(uuid.uuid4())
    max_retries = 3
    created_student = None
    student_code = ""

    for attempt in range(max_retries):
        student_code = student_repository.generate_next_student_code()
        student = Student(
            id=student_id,
            student_code=student_code,
            user_id=user_id,
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

    # 3. Gửi email thông báo tài khoản cho học viên (Sub-task 215-03)
    if lead.email and lead.email.strip() and account_created:
        try:
            email_service.send_account_creation_email(
                to_email=lead.email.strip().lower(),
                name=lead.full_name,
                raw_password=raw_password,
            )
            email_sent = True
            logger.info("Đã gửi email thông báo tài khoản cho học viên %s", lead.email)
        except Exception as email_err:
            email_sent = False
            logger.warning(
                "Không thể gửi email thông báo tài khoản tới %s: %s",
                lead.email,
                type(email_err).__name__,
            )

    # Lấy thông tin đầy đủ sau khi tạo (kèm tên chương trình đào tạo)
    full_student = student_repository.get_student_by_id(created_student.id) or created_student

    logger.info(
        "Chuyển đổi Lead %s thành Student %s (Code: %s, User: %s, EmailSent: %s) bởi actor %s",
        lead_id,
        student_id,
        student_code,
        user_id,
        email_sent,
        actor_user_id,
    )

    return {
        "student": full_student.to_dict(),
        "lead": lead.to_dict(),
        "user_id": user_id,
        "account_created": account_created,
        "email_sent": email_sent,
    }

