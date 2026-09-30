from werkzeug.security import check_password_hash

from app.repositories import user_repository


class ChangePasswordError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def verify_current_password(stored_password_hash: str, plain_password: str) -> bool:
    """Xác thực mật khẩu hiện tại bằng werkzeug check_password_hash (không dùng plaintext comparison)."""
    if not isinstance(stored_password_hash, str) or not stored_password_hash:
        return False
    if not isinstance(plain_password, str) or not plain_password:
        return False
    return check_password_hash(stored_password_hash, plain_password)


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    current_session_id: str | None = None,
) -> dict:
    """
    Xử lý đổi mật khẩu:
    - Kiểm tra dữ liệu đầu vào
    - Lấy user từ database theo user_id (từ JWT/session)
    - Xác thực mật khẩu hiện tại
    """
    if not isinstance(current_password, str) or not current_password:
        raise ChangePasswordError("CURRENT_PASSWORD_REQUIRED", "Mật khẩu hiện tại là bắt buộc")

    if not isinstance(new_password, str) or not new_password:
        raise ChangePasswordError("NEW_PASSWORD_REQUIRED", "Mật khẩu mới là bắt buộc")

    user = user_repository.get_user_by_id(user_id)
    if user is None:
        raise ChangePasswordError("USER_NOT_FOUND", "Không tìm thấy thông tin tài khoản người dùng")

    if not verify_current_password(user.password_hash, current_password):
        raise ChangePasswordError(
            "INCORRECT_CURRENT_PASSWORD",
            "Mật khẩu hiện tại không chính xác",
        )

    return {
        "message": "Xác thực mật khẩu hiện tại thành công",
    }
