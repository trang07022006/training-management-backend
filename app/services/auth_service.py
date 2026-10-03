import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.repositories import password_reset_repository, user_repository
from app.services import email_service
from app.services.session_service import create_stored_login_session

logger = logging.getLogger(__name__)


MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
LOCKOUT_DURATION = timedelta(minutes=LOCKOUT_DURATION_MINUTES)
INVALID_CREDENTIALS_MESSAGE = "Email hoặc mật khẩu không đúng"
ACCOUNT_LOCKED_MESSAGE = "Tài khoản tạm thời bị khóa 15 phút do nhập sai mật khẩu quá 5 lần. Vui lòng thử lại sau."
ACCOUNT_INACTIVE_MESSAGE = "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên."
PUBLIC_FORGOT_PASSWORD_MESSAGE = (
    "Nếu email tồn tại trong hệ thống, hướng dẫn đặt lại mật khẩu sẽ được gửi tới email của bạn."
)

RESET_TOKEN_EXPIRES_MINUTES = 30
RESET_TOKEN_DURATION = timedelta(minutes=RESET_TOKEN_EXPIRES_MINUTES)

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
        elif message is None and code in ("ACCOUNT_INACTIVE", "ACCOUNT_DISABLED"):
            message = ACCOUNT_INACTIVE_MESSAGE
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

    # 5. Kiểm tra trạng thái tài khoản (phân biệt rõ active, inactive, locked)
    if user.status == "locked":
        raise AuthValidationError(
            code="ACCOUNT_LOCKED",
            message="Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên để được hỗ trợ.",
        )
    elif user.status == "inactive":
        raise AuthValidationError(
            code="ACCOUNT_INACTIVE",
            message=ACCOUNT_INACTIVE_MESSAGE,
        )
    elif user.status != "active":
        raise AuthValidationError(
            code="ACCOUNT_INACTIVE",
            message=ACCOUNT_INACTIVE_MESSAGE,
        )

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


def generate_reset_token() -> str:
    """Sinh token ngẫu nhiên bảo mật cao (cryptographically secure random)."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """Băm SHA-256 token trước khi lưu vào cơ sở dữ liệu để bảo mật."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset_token(
    user_id: str,
    current_time: datetime | None = None,
) -> tuple[str, PasswordResetToken]:
    """
    Sinh token ngẫu nhiên bảo mật, tính thời hạn chính xác 30 phút,
    và lưu persistence vào MySQL dưới dạng SHA-256 hash.
    Trả về tuple (raw_token, reset_token_record).
    """
    now = current_time or datetime.now(timezone.utc)
    expires_at = now + RESET_TOKEN_DURATION
    raw_token = generate_reset_token()
    token_hash = hash_reset_token(raw_token)

    token_record = PasswordResetToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
    )

    password_reset_repository.insert_reset_token(token_record)
    return raw_token, token_record


def process_forgot_password_request(
    email: str,
    current_time: datetime | None = None,
) -> dict:
    """
    Xử lý yêu cầu đặt lại mật khẩu (SCRUM-45 & SCRUM-46).
    - Validate & normalize email.
    - Kiểm tra user theo email trong MySQL database.
    - Khi email tồn tại: sinh reset token cryptographic random, thời hạn 30 phút,
      và lưu persistence vào MySQL (dưới dạng hash SHA-256).
    - Khi email không tồn tại: không tạo token.
    - Không tiết lộ email có tồn tại hay không (anti-enumeration).
    - Không trả token ra public API.
    - Không fallback mock khi MySQL lỗi.
    """
    if not isinstance(email, str) or not email.strip():
        raise AuthValidationError("EMAIL_REQUIRED", "Email là bắt buộc")

    normalized_email = email.strip().lower()

    if not EMAIL_REGEX.match(normalized_email):
        raise AuthValidationError("INVALID_EMAIL", "Định dạng email không hợp lệ")

    # Kiểm tra người dùng theo email trong MySQL database (không fallback mock)
    user = user_repository.get_user_by_email(normalized_email)

    # SCRUM-46 & SCRUM-48: Nếu user tồn tại, tạo token 30 phút và gửi email
    if user is not None:
        raw_token, token_record = create_password_reset_token(
            user_id=user.id,
            current_time=current_time,
        )
        try:
            email_service.send_password_reset_email(
                to_email=user.email,
                raw_token=raw_token,
            )
        except Exception as error:
            # Ghi log an toàn phía server (không log token raw, không log password)
            logger.error(
                "Lỗi khi gửi email đặt lại mật khẩu tới %s: %s",
                user.email,
                type(error).__name__,
            )
            # Không throw lỗi ra ngoài để bảo vệ nguyên tắc anti-enumeration

    return {
        "message": PUBLIC_FORGOT_PASSWORD_MESSAGE,
    }


def validate_reset_token(
    raw_token: str,
    current_time: datetime | None = None,
) -> PasswordResetToken:
    """
    Kiểm tra token đặt lại mật khẩu (SCRUM-47):
    - Token không được rỗng.
    - Hash token theo SHA-256.
    - Tìm token trong database.
    - Kiểm tra:
      + Tồn tại (nếu không -> INVALID_TOKEN)
      + Chưa bị sử dụng (nếu đã dùng -> TOKEN_ALREADY_USED)
      + Chưa hết hạn 30 phút (nếu hết hạn -> TOKEN_EXPIRED)
    - Không làm rò rỉ dữ liệu nhạy cảm.
    """
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise AuthValidationError("TOKEN_REQUIRED", "Token là bắt buộc")

    clean_token = raw_token.strip()
    token_hash = hash_reset_token(clean_token)
    token_record = password_reset_repository.get_reset_token_by_hash(token_hash)

    if token_record is None:
        raise AuthValidationError("INVALID_TOKEN", "Token đặt lại mật khẩu không hợp lệ")

    now = current_time or datetime.now(timezone.utc)

    if token_record.is_used:
        raise AuthValidationError("TOKEN_ALREADY_USED", "Token đặt lại mật khẩu đã được sử dụng")

    if token_record.is_expired(current_time=now):
        raise AuthValidationError("TOKEN_EXPIRED", "Token đặt lại mật khẩu đã hết hạn")

    return token_record


def reset_password_with_token(
    raw_token: str,
    new_password: str,
    current_time: datetime | None = None,
) -> dict:
    """
    Đặt lại mật khẩu với token một lần duy nhất (SCRUM-47):
    - Nhận raw reset token & new_password.
    - Validate format token & password.
    - Hash token theo SHA-256 (SCRUM-46).
    - Tạo hash mật khẩu mới an toàn bằng generate_password_hash.
    - Thực thi transaction:
        validate token -> update password -> mark token used -> commit.
    - Nếu có lỗi -> rollback, token chưa bị consume.
    - Không lưu plaintext token vào database.
    - Không làm lộ token hoặc thông tin nhạy cảm trong response.
    """
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise AuthValidationError("TOKEN_REQUIRED", "Token là bắt buộc")

    if not isinstance(new_password, str) or not new_password:
        raise AuthValidationError("PASSWORD_REQUIRED", "Mật khẩu mới là bắt buộc")

    if len(new_password) < 8:
        raise AuthValidationError("PASSWORD_TOO_SHORT", "Mật khẩu phải có tối thiểu 8 ký tự")

    has_letter = bool(re.search(r"[a-zA-Z]", new_password))
    has_digit = bool(re.search(r"[0-9]", new_password))
    if not has_letter or not has_digit:
        raise AuthValidationError("PASSWORD_INVALID", "Mật khẩu phải bao gồm cả chữ cái và chữ số")

    clean_token = raw_token.strip()
    now = current_time or datetime.now(timezone.utc)
    token_hash = hash_reset_token(clean_token)
    new_password_hash = generate_password_hash(new_password)

    try:
        password_reset_repository.execute_reset_password_transaction(
            token_hash=token_hash,
            new_password_hash=new_password_hash,
            current_time=now,
        )
    except password_reset_repository.ResetTokenNotFoundError:
        raise AuthValidationError("INVALID_TOKEN", "Token đặt lại mật khẩu không hợp lệ")
    except password_reset_repository.ResetTokenAlreadyUsedError:
        raise AuthValidationError("TOKEN_ALREADY_USED", "Token đặt lại mật khẩu đã được sử dụng")
    except password_reset_repository.ResetTokenExpiredError:
        raise AuthValidationError("TOKEN_EXPIRED", "Token đặt lại mật khẩu đã hết hạn")

    return {
        "message": "Mật khẩu đã được đặt lại thành công",
    }



