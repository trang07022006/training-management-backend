import re
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash

from app.models.user import User
from app.repositories import user_repository
from app.services.session_service import create_stored_login_session


MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
LOCKOUT_DURATION = timedelta(minutes=LOCKOUT_DURATION_MINUTES)
INVALID_CREDENTIALS_MESSAGE = "Email hoặc mật khẩu không đúng"
ACCOUNT_LOCKED_MESSAGE = "Tài khoản tạm thời bị khóa 15 phút do nhập sai mật khẩu quá 5 lần. Vui lòng thử lại sau."
PUBLIC_FORGOT_PASSWORD_MESSAGE = (
    "Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi tới email của bạn."
)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")


class AuthValidationError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        locked_until: datetime | None = None,
    ):
        self.code = code
        self.locked_until = locked_until
        if message is None and code == "INVALID_CREDENTIALS":
            message = INVALID_CREDENTIALS_MESSAGE
        elif message is None and code == "ACCOUNT_LOCKED":
            message = ACCOUNT_LOCKED_MESSAGE
        self.message = message
        super().__init__(message or code)


def verify_password(stored_password_hash: str, plain_password: str) -> bool:
    """Xác thực mật khẩu với hash đã lưu bằng werkzeug.security (không so sánh plaintext)."""
    if not isinstance(stored_password_hash, str) or not stored_password_hash:
        return False

    if not isinstance(plain_password, str) or not plain_password:
        return False

    try:
        return check_password_hash(stored_password_hash, plain_password)
    except Exception:
        return False


def validate_credentials(
    email: str,
    password: str,
    current_time: datetime | None = None,
) -> User:
    """
    Kiểm tra thông tin đăng nhập (email và mật khẩu) và xử lý khóa tạm thời.

    - Kiểm tra email và password hợp lệ (không rỗng).
    - Tìm kiếm người dùng theo email.
    - Kiểm tra tài khoản có đang bị khóa (locked_until > now): nếu có thì từ chối.
    - Nếu khóa đã hết hạn (locked_until <= now): cho phép đăng nhập lại, reset bộ đếm tạm thời.
    - So khớp mật khẩu:
      + Mật khẩu đúng: reset số lần sai (failed_login_attempts=0, locked_until=None).
        Kiểm tra tài khoản active.
      + Mật khẩu sai:
        * Lần 1-4: tăng bộ đếm, ném INVALID_CREDENTIALS.
        * Lần 5: tăng bộ đếm, khóa tạm 15 phút, ném ACCOUNT_LOCKED.
    """
    if not isinstance(email, str) or not email.strip():
        raise AuthValidationError("EMAIL_REQUIRED")

    if not isinstance(password, str) or not password:
        raise AuthValidationError("PASSWORD_REQUIRED")

    now = current_time or datetime.now(timezone.utc)

    user = user_repository.get_user_by_email(email.strip())
    if user is None:
        raise AuthValidationError("INVALID_CREDENTIALS", INVALID_CREDENTIALS_MESSAGE)

    # 1. Kiểm tra tài khoản có đang trong thời gian bị khóa tạm thời hay không
    if user.is_locked(current_time=now):
        raise AuthValidationError(
            code="ACCOUNT_LOCKED",
            message=ACCOUNT_LOCKED_MESSAGE,
            locked_until=user.locked_until,
        )

    # 2. Kiểm tra nếu thời gian khóa đã hết hạn, bắt đầu chu kỳ đếm mới
    has_expired_lockout = user.locked_until is not None and not user.is_locked(current_time=now)
    current_failed_attempts = 0 if has_expired_lockout else (user.failed_login_attempts or 0)

    # 3. Kiểm tra mật khẩu
    if not verify_password(user.password_hash, password):
        new_failed_attempts = current_failed_attempts + 1

        if new_failed_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            # Sai lần 5: khóa tạm 15 phút
            locked_until = now + LOCKOUT_DURATION
            user.failed_login_attempts = new_failed_attempts
            user.locked_until = locked_until
            user_repository.update_user_lockout(
                user_id=user.id,
                failed_login_attempts=new_failed_attempts,
                locked_until=locked_until,
            )
            raise AuthValidationError(
                code="ACCOUNT_LOCKED",
                message=ACCOUNT_LOCKED_MESSAGE,
                locked_until=locked_until,
            )
        else:
            # Sai lần 1–4: tăng bộ đếm
            user.failed_login_attempts = new_failed_attempts
            user.locked_until = None
            user_repository.update_user_lockout(
                user_id=user.id,
                failed_login_attempts=new_failed_attempts,
                locked_until=None,
            )
            raise AuthValidationError(
                code="INVALID_CREDENTIALS",
                message=INVALID_CREDENTIALS_MESSAGE,
            )

    # 4. Đăng nhập thành công: reset số lần sai
    if user.failed_login_attempts > 0 or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        user_repository.reset_user_lockout(user_id=user.id)

    # 5. Kiểm tra trạng thái tài khoản
    if user.status != "active":
        raise AuthValidationError("ACCOUNT_DISABLED")

    return user


def authenticate_and_login(
    email: str,
    password: str,
    current_time: datetime | None = None,
):
    """
    Xác thực thông tin đăng nhập và tạo phiên làm việc mới kèm JWT tokens.
    Tái sử dụng create_stored_login_session từ session_service.
    """
    user = validate_credentials(email=email, password=password, current_time=current_time)
    session, tokens = create_stored_login_session(user_id=str(user.id))
    return user, session, tokens


def process_forgot_password_request(email: str) -> dict:
    """
    Xử lý yêu cầu đặt lại mật khẩu (SCRUM-45).
    - Validate & normalize email.
    - Kiểm tra user theo email trong MySQL database.
    - Không tiết lộ email có tồn tại hay không (anti-enumeration).
    - Email tồn tại và không tồn tại đều trả về cùng một thông báo công khai.
    - Không dùng mock database khi MySQL lỗi.
    """
    if not isinstance(email, str) or not email.strip():
        raise AuthValidationError("EMAIL_REQUIRED", "Email là bắt buộc")

    normalized_email = email.strip().lower()

    if not EMAIL_REGEX.match(normalized_email):
        raise AuthValidationError("INVALID_EMAIL", "Định dạng email không hợp lệ")

    # Kiểm tra người dùng theo email trong MySQL database (không fallback mock)
    user = user_repository.get_user_by_email(normalized_email)

    # Chưa triển khai đầy đủ token 30 phút của SCRUM-46
    # Chưa làm single-use token SCRUM-47
    # Chưa gửi SMTP thật SCRUM-48
    if user is not None:
        pass

    return {
        "message": PUBLIC_FORGOT_PASSWORD_MESSAGE,
    }



