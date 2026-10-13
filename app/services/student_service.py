"""
Tầng nghiệp vụ Quản lý Học viên và Chuyển đổi Lead (Student Service) - SCRUM-215.
"""

import os
from datetime import datetime, timezone
import logging
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


class StudentInitialPasswordNotConfiguredError(StudentServiceError):
    def __init__(
        self,
        message: str = "Chưa cấu hình mật khẩu ban đầu cho học viên trong hệ thống (STUDENT_INITIAL_PASSWORD).",
    ):
        super().__init__("CONFIGURATION_ERROR", message, status_code=500)


def get_student_initial_password() -> str:
    """
    Đọc mật khẩu ban đầu cố định cho học viên từ biến môi trường STUDENT_INITIAL_PASSWORD.
    Nếu biến môi trường không tồn tại hoặc rỗng: không tự dùng fallback yếu mà ném lỗi rõ ràng.
    """
    pwd = os.getenv("STUDENT_INITIAL_PASSWORD")
    if not pwd or not pwd.strip():
        raise StudentInitialPasswordNotConfiguredError()
    return pwd.strip()


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

    # Kiểm tra Lead phải ở trạng thái Chốt (won) và chưa Đã nhập học (converted)
    if lead.status in ("converted", "enrolled"):
        raise LeadAlreadyConvertedError("Khách hàng đã nhập học / đã được chuyển thành hồ sơ học viên trước đó.")
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
            raw_password = get_student_initial_password()
            password_hash = generate_password_hash(raw_password)
            user_id = str(uuid.uuid4())
            new_user = User(
                id=user_id,
                email=norm_email,
                password_hash=password_hash,
                name=lead.full_name,
                phone=lead.phone,
                role="trainee",
                status="active",
                failed_login_attempts=0,
                must_change_password=True,
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

    # 4. Chuyển trạng thái Lead sang Đã nhập học (SCRUM-215 - Sub-task 215-04)
    updated_lead = lead_repository.update_lead_status(lead.id, "converted", updated_at=now)
    if updated_lead:
        lead = updated_lead
    else:
        lead.status = "converted"

    # Lấy thông tin đầy đủ sau khi tạo (kèm tên chương trình đào tạo)
    full_student = student_repository.get_student_by_id(created_student.id) or created_student

    logger.info(
        "Chuyển đổi Lead %s thành Student %s (Code: %s, User: %s, EmailSent: %s, LeadStatus: %s) bởi actor %s",
        lead_id,
        student_id,
        student_code,
        user_id,
        email_sent,
        lead.status,
        actor_user_id,
    )

    return {
        "student": full_student.to_dict(),
        "lead": lead.to_dict(),
        "user_id": user_id,
        "account_created": account_created,
        "email_sent": email_sent,
    }


class StudentNotFoundError(StudentServiceError):
    def __init__(self, message: str = "Không tìm thấy hồ sơ học viên."):
        super().__init__("STUDENT_NOT_FOUND", message, status_code=404)


class StudentValidationError(StudentServiceError):
    def __init__(self, code: str = "VALIDATION_ERROR", message: str = "Dữ liệu không hợp lệ."):
        super().__init__(code, message, status_code=400)


import re
from app.database.connection import get_db_connection
from app.models.student import format_datetime_utc_iso

PHONE_CHARS_REGEX = re.compile(r"^\+?[0-9\s\-\.\(\)]{6,30}$")
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _get_student_classes(student_id: str) -> tuple[dict | None, list[dict]]:
    """
    Truy vấn lớp đang học và lịch sử các lớp đã học của học viên (SCRUM-216 - Sub-task 216-02).
    Nếu bảng class_enrollments/classes chưa tồn tại hoặc chưa có dữ liệu, trả về (None, []).
    """
    connection = get_db_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM information_schema.tables 
                WHERE table_schema = DATABASE() AND table_name = 'class_enrollments';
            """)
            if cursor.fetchone()["cnt"] == 0:
                return None, []

            cursor.execute("""
                SELECT 
                    ce.id AS enrollment_id,
                    ce.class_id,
                    ce.status AS enrollment_status,
                    ce.enrolled_at,
                    c.class_code AS class_code,
                    c.class_code AS class_name,
                    c.status AS class_status,
                    c.expected_start_date,
                    tp.code AS program_code,
                    tp.name AS program_name
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                LEFT JOIN training_programs tp ON c.program_id = tp.id
                WHERE ce.student_id = %s
                ORDER BY ce.enrolled_at DESC
            """, (student_id,))
            rows = cursor.fetchall()
            if not rows:
                return None, []

            current = None
            history = []
            for r in rows:
                cls_info = {
                    "enrollment_id": r["enrollment_id"],
                    "class_id": r["class_id"],
                    "class_code": r["class_code"],
                    "class_name": r["class_name"] or r["class_code"],
                    "class_status": r["class_status"],
                    "enrollment_status": r["enrollment_status"],
                    "expected_start_date": format_datetime_utc_iso(r["expected_start_date"]) if r.get("expected_start_date") else None,
                    "enrolled_at": format_datetime_utc_iso(r["enrolled_at"]) if r.get("enrolled_at") else None,
                    "program_code": r.get("program_code"),
                    "program_name": r.get("program_name"),
                }
                if r["class_status"] in ("in_progress", "ongoing", "studying") and not current:
                    current = cls_info
                else:
                    history.append(cls_info)

            if not current and rows:
                first = rows[0]
                if first["class_status"] in ("preparing", "in_progress", "ongoing"):
                    current = {
                        "enrollment_id": first["enrollment_id"],
                        "class_id": first["class_id"],
                        "class_code": first["class_code"],
                        "class_name": first["class_name"] or first["class_code"],
                        "class_status": first["class_status"],
                        "enrollment_status": first["enrollment_status"],
                        "expected_start_date": format_datetime_utc_iso(first["expected_start_date"]) if first.get("expected_start_date") else None,
                        "enrolled_at": format_datetime_utc_iso(first["enrolled_at"]) if first.get("enrolled_at") else None,
                        "program_code": first.get("program_code"),
                        "program_name": first.get("program_name"),
                    }
                    history = [h for h in history if h["enrollment_id"] != first["enrollment_id"]]

            return current, history
    except Exception as e:
        logger.warning("Không thể đọc danh sách lớp học của học viên %s: %s", student_id, e)
        return None, []
    finally:
        connection.close()


def get_student_detail_service(student_id: str) -> dict:
    """
    Lấy chi tiết hồ sơ học viên kèm lớp đang học và lịch sử lớp (SCRUM-216 - Sub-task 216-01 & 216-02).
    """
    student = student_repository.get_student_by_id(student_id)
    if not student:
        raise StudentNotFoundError()

    data = student.to_dict()
    current_class, class_history = _get_student_classes(student.id)
    data["current_class"] = current_class
    data["class_history"] = class_history
    return data


def update_student_profile_service(student_id: str, payload: dict) -> dict:
    """
    Cập nhật thông tin hồ sơ học viên (SCRUM-216 - Sub-task 216-01).
    - Cập nhật thông tin cá nhân: full_name, phone, email.
    - Cập nhật trình độ đầu vào: entry_level.
    - Cập nhật ghi chú: notes.
    """
    student = student_repository.get_student_by_id(student_id)
    if not student:
        raise StudentNotFoundError()

    full_name = payload.get("full_name")
    if full_name is not None:
        if not isinstance(full_name, str) or not full_name.strip():
            raise StudentValidationError("INVALID_NAME", "Họ và tên không được để trống.")
        full_name = full_name.strip()
        if len(full_name) > 255:
            raise StudentValidationError("NAME_TOO_LONG", "Họ và tên không được vượt quá 255 ký tự.")
    else:
        full_name = student.full_name

    phone = payload.get("phone")
    if phone is not None:
        if not isinstance(phone, str) or not phone.strip():
            raise StudentValidationError("INVALID_PHONE", "Số điện thoại không được để trống.")
        phone = phone.strip()
        if not PHONE_CHARS_REGEX.match(phone):
            raise StudentValidationError("INVALID_PHONE", "Số điện thoại không đúng định dạng.")
    else:
        phone = student.phone

    email = payload.get("email")
    if email is not None:
        if isinstance(email, str) and email.strip():
            email = email.strip()
            if not EMAIL_REGEX.match(email):
                raise StudentValidationError("INVALID_EMAIL", "Email không đúng định dạng.")
        else:
            email = None
    else:
        email = student.email

    entry_level = payload.get("entry_level")
    if entry_level is not None:
        if isinstance(entry_level, str) and entry_level.strip():
            entry_level = entry_level.strip()
            if len(entry_level) > 255:
                raise StudentValidationError("ENTRY_LEVEL_TOO_LONG", "Trình độ đầu vào không được vượt quá 255 ký tự.")
        else:
            entry_level = None
    else:
        entry_level = student.entry_level

    notes = payload.get("notes")
    if notes is not None:
        if isinstance(notes, str) and notes.strip():
            notes = notes.strip()
        else:
            notes = None
    else:
        notes = student.notes

    updated = student_repository.update_student_profile(
        student_id=student.id,
        full_name=full_name,
        phone=phone,
        email=email,
        entry_level=entry_level,
        notes=notes,
    )
    if not updated:
        raise StudentNotFoundError()

    data = updated.to_dict()
    current_class, class_history = _get_student_classes(updated.id)
    data["current_class"] = current_class
    data["class_history"] = class_history
    return data


def list_students_service(
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Lấy danh sách học viên có phân trang và tìm kiếm (SCRUM-216 - Sub-task 216-01 & 216-03).
    """
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    students, total = student_repository.list_students(search=search, page=page, page_size=page_size)
    return {
        "items": [s.to_dict() for s in students],
        "total": total,
        "page": page,
        "page_size": page_size,
    }



