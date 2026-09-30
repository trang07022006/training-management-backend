"""
Dịch vụ quản trị người dùng (User Management Service - SCRUM-84, SCRUM-85, SCRUM-86, SCRUM-87).
Bao gồm:
- Tạo người dùng mới với băm mật khẩu an toàn và kiểm tra email duy nhất
- Kiểm tra chính sách mật khẩu, định dạng email, số điện thoại
- Cập nhật thông tin người dùng an toàn (không mass-assignment, không lộ hash)
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from mysql.connector.errors import IntegrityError
from werkzeug.security import generate_password_hash

from app.models.user import User
from app.repositories import role_repository, user_repository, user_role_repository

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")
PHONE_REGEX = re.compile(r"^\+?[0-9]{9,15}$")
VALID_ROLES = {"admin", "trainer", "trainee", "user"}
VALID_STATUSES = {"active", "inactive", "locked"}


class UserValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class DuplicateEmailError(Exception):
    def __init__(self, message: str = "Email này đã được sử dụng trong hệ thống."):
        self.code = "DUPLICATE_EMAIL"
        self.message = message
        super().__init__(message)


class UserNotFoundError(Exception):
    def __init__(self, message: str = "Không tìm thấy người dùng."):
        self.code = "USER_NOT_FOUND"
        self.message = message
        super().__init__(message)


def normalize_email(email: str | None) -> str:
    """Chuẩn hóa email: loại bỏ khoảng trắng và chuyển chữ thường."""
    if not email or not isinstance(email, str):
        return ""
    return email.strip().lower()


def validate_email_format(email: str) -> str:
    """Kiểm tra và trả về email đã chuẩn hóa nếu hợp lệ."""
    norm = normalize_email(email)
    if not norm:
        raise UserValidationError("EMAIL_REQUIRED", "Email là bắt buộc.")
    if len(norm) > 255 or not EMAIL_REGEX.match(norm):
        raise UserValidationError("INVALID_EMAIL", "Email không đúng định dạng.")
    return norm


def validate_password_policy(password: str) -> None:
    """
    Kiểm tra chính sách mật khẩu ban đầu:
    - Tối thiểu 8 ký tự
    - Có ít nhất 1 chữ cái
    - Có ít nhất 1 chữ số
    """
    if not isinstance(password, str) or not password:
        raise UserValidationError("PASSWORD_REQUIRED", "Mật khẩu là bắt buộc.")
    if len(password) < 8:
        raise UserValidationError("PASSWORD_TOO_SHORT", "Mật khẩu phải có tối thiểu 8 ký tự.")
    if not re.search(r"[a-zA-Z]", password) or not re.search(r"[0-9]", password):
        raise UserValidationError("PASSWORD_INVALID", "Mật khẩu phải bao gồm cả chữ cái và chữ số.")


def validate_phone_number(phone: str | None) -> str | None:
    """Kiểm tra số điện thoại (nếu có cung cấp)."""
    if phone is None or phone == "":
        return None
    cleaned = str(phone).strip()
    if not cleaned:
        return None
    if not PHONE_REGEX.match(cleaned):
        raise UserValidationError("INVALID_PHONE", "Số điện thoại không hợp lệ (cần 9-15 chữ số).")
    return cleaned


def create_user_service(
    email: str,
    password: str,
    name: str | None = None,
    phone: str | None = None,
    role: str = "user",
    status: str = "active",
) -> User:
    """
    Tạo người dùng mới:
    1. Validate required fields & format
    2. Check duplicate email (case-insensitive)
    3. Hash password bằng werkzeug generate_password_hash
    4. Ghi DB với parameterized query
    5. Gán initial role nếu có trong roles table
    """
    normalized_email = validate_email_format(email)
    validate_password_policy(password)

    cleaned_name = name.strip() if isinstance(name, str) and name.strip() else None
    if not cleaned_name:
        raise UserValidationError("NAME_REQUIRED", "Họ và tên là bắt buộc.")

    cleaned_phone = validate_phone_number(phone)

    selected_role = (role or "user").strip().lower()
    if selected_role not in VALID_ROLES:
        raise UserValidationError("INVALID_ROLE", f"Vai trò không hợp lệ: {selected_role}.")

    selected_status = (status or "active").strip().lower()
    if selected_status not in VALID_STATUSES:
        raise UserValidationError("INVALID_STATUS", f"Trạng thái không hợp lệ: {selected_status}.")

    # Check duplicate email
    existing = user_repository.get_user_by_email(normalized_email)
    if existing is not None:
        raise DuplicateEmailError()

    password_hash = generate_password_hash(password)
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    user = User(
        id=user_id,
        email=normalized_email,
        password_hash=password_hash,
        name=cleaned_name,
        phone=cleaned_phone,
        role=selected_role,
        status=selected_status,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )

    try:
        created_user = user_repository.create_user(user)
    except IntegrityError as e:
        # MySQL errno 1062 = Duplicate entry
        if getattr(e, "errno", None) == 1062 or "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise DuplicateEmailError()
        raise

    # Assign initial role mapping in user_roles table if role exists
    try:
        role_obj = role_repository.get_role_by_code(selected_role)
        if role_obj:
            user_role_repository.assign_role_to_user(user_id, role_obj.id)
    except Exception as e:
        logger.warning(f"Could not assign initial role {selected_role} to user {user_id}: {e}")

    return created_user
