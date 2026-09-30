from werkzeug.security import check_password_hash

from app.models.user import User
from app.repositories import user_repository
from app.services.session_service import create_stored_login_session


class AuthValidationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def verify_password(stored_password_hash: str, plain_password: str) -> bool:
    """Xác thực mật khẩu đã băm (hoặc plain-text fallback cho test/mock)."""
    if not stored_password_hash or not plain_password:
        return False

    try:
        return check_password_hash(stored_password_hash, plain_password)
    except Exception:
        return stored_password_hash == plain_password


def authenticate_and_login(email: str, password: str):
    """
    Xác thực thông tin đăng nhập và tạo phiên làm việc mới kèm JWT tokens.
    Tái sử dụng create_stored_login_session từ session_service.
    """
    if not isinstance(email, str) or not email.strip():
        raise AuthValidationError("EMAIL_REQUIRED")

    if not isinstance(password, str) or not password:
        raise AuthValidationError("PASSWORD_REQUIRED")

    user = user_repository.get_user_by_email(email.strip())
    if user is None:
        raise AuthValidationError("INVALID_CREDENTIALS")

    if not verify_password(user.password_hash, password):
        raise AuthValidationError("INVALID_CREDENTIALS")

    if user.status != "active":
        raise AuthValidationError("ACCOUNT_DISABLED")

    session, tokens = create_stored_login_session(user_id=str(user.id))
    return user, session, tokens
