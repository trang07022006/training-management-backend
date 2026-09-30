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
from app.repositories import role_repository, session_repository, user_repository, user_role_repository

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
    if user_repository.check_email_exists(normalized_email):
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
    except Exception as e:
        err_msg = str(e).lower()
        err_no = getattr(e, "errno", None)
        if err_no == 1062 or "duplicate" in err_msg or "unique" in err_msg:
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


def update_user_service(user_id: str, updates: dict) -> User:
    """
    Cập nhật thông tin người dùng (SCRUM-86):
    - Không cho mass-assignment
    - Chỉ cho phép cập nhật: name, phone, email, status
    - Ngăn chặn chỉnh sửa password, role, id, permissions
    - Kiểm tra email duy nhất nếu thay đổi
    """
    if not isinstance(updates, dict):
        raise UserValidationError("INVALID_DATA", "Dữ liệu cập nhật không hợp lệ.")

    # Check for forbidden sensitive fields
    for forbidden in ["password", "password_hash", "role", "permissions", "id", "failed_login_attempts", "locked_until"]:
        if forbidden in updates and updates[forbidden] is not None:
            raise UserValidationError("FORBIDDEN_FIELD", f"Không được phép chỉnh sửa trường nhạy cảm: {forbidden}.")

    user = user_repository.get_user_by_id(user_id)
    if user is None:
        raise UserNotFoundError()

    # Update name
    if "name" in updates:
        name_val = updates["name"]
        if not isinstance(name_val, str) or not name_val.strip():
            raise UserValidationError("NAME_REQUIRED", "Họ và tên không được để trống.")
        user.name = name_val.strip()

    # Update phone
    if "phone" in updates:
        user.phone = validate_phone_number(updates["phone"])

    # Update status
    if "status" in updates:
        st_val = updates["status"]
        if not isinstance(st_val, str) or st_val.strip().lower() not in VALID_STATUSES:
            raise UserValidationError("INVALID_STATUS", f"Trạng thái không hợp lệ: {st_val}.")
        user.status = st_val.strip().lower()

    # Update email
    if "email" in updates:
        new_email = validate_email_format(updates["email"])
        if new_email != user.email:
            if user_repository.check_email_exists(new_email, exclude_user_id=user.id):
                raise DuplicateEmailError()
            user.email = new_email

    user.updated_at = datetime.now(timezone.utc)

    try:
        user_repository.update_user(user)
    except Exception as e:
        err_msg = str(e).lower()
        err_no = getattr(e, "errno", None)
        if err_no == 1062 or "duplicate" in err_msg or "unique" in err_msg:
            raise DuplicateEmailError()
        raise

    return user


ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_LOCKED = "locked"
ACCOUNT_STATUS_INACTIVE = "inactive"


def get_user_account_status(user_id: str) -> dict:
    """
    Chuẩn hóa việc đọc trạng thái tài khoản từ database (SCRUM-104).
    Xác định rõ ràng: ACTIVE, LOCKED hoặc trạng thái hợp lệ trong hệ thống.
    Tuyệt đối không expose mật khẩu, token hay DB internals.
    """
    user = user_repository.get_user_by_id(user_id)
    if user is None:
        raise UserNotFoundError()

    normalized_status = user.status if user.status in VALID_STATUSES else "unknown"
    is_locked = (normalized_status == ACCOUNT_STATUS_LOCKED) or user.is_locked()

    return {
        "user_id": str(user.id),
        "status": normalized_status,
        "is_locked": is_locked,
        "is_active": normalized_status == ACCOUNT_STATUS_ACTIVE and not is_locked,
    }


class AccountAlreadyLockedError(Exception):
    def __init__(self, message: str = "Tài khoản này đã bị khóa từ trước."):
        self.code = "ALREADY_LOCKED"
        self.message = message
        self.status_code = 409
        super().__init__(message)


def lock_user_account(user_id: str) -> dict:
    """
    Khóa tài khoản người dùng (SCRUM-106).
    - Kiểm tra user tồn tại (404 USER_NOT_FOUND nếu không tìm thấy).
    - Kiểm tra nếu account đã ở trạng thái locked (409 ALREADY_LOCKED nếu đã khóa).
    - Cập nhật status='locked' trong database.
    - Thu hồi toàn bộ phiên hoạt động của người dùng (SCRUM-109).
    - Trả về thông tin an toàn: user_id, status.
    """
    user = user_repository.get_user_by_id(user_id)
    if user is None:
        raise UserNotFoundError()

    if user.status == ACCOUNT_STATUS_LOCKED:
        raise AccountAlreadyLockedError()

    user_repository.update_user_status(user_id=str(user.id), status=ACCOUNT_STATUS_LOCKED)

    # Thu hồi toàn bộ phiên làm việc của tài khoản này
    try:
        session_repository.revoke_other_user_sessions(user_id=str(user.id), current_session_id=None)
    except Exception as e:
        logger.warning(f"Could not revoke sessions for locked user {user_id}: {e}")

    return {
        "user_id": str(user.id),
        "status": ACCOUNT_STATUS_LOCKED,
    }

