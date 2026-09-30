import re
from werkzeug.security import check_password_hash, generate_password_hash

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


def validate_new_password_policy(new_password: str, current_password: str | None = None) -> None:
    """
    Kiểm tra điều kiện mật khẩu mới (SCRUM-55):
    - Không rỗng
    - Tối thiểu 8 ký tự
    - Phải có ít nhất 1 chữ cái
    - Phải có ít nhất 1 chữ số
    - Không được trùng với mật khẩu hiện tại
    """
    if not isinstance(new_password, str) or not new_password:
        raise ChangePasswordError("NEW_PASSWORD_REQUIRED", "Mật khẩu mới là bắt buộc")

    if len(new_password) < 8:
        raise ChangePasswordError("PASSWORD_TOO_SHORT", "Mật khẩu mới phải có tối thiểu 8 ký tự")

    has_letter = bool(re.search(r"[a-zA-Z]", new_password))
    has_digit = bool(re.search(r"[0-9]", new_password))

    if not has_letter or not has_digit:
        raise ChangePasswordError("PASSWORD_INVALID", "Mật khẩu mới phải bao gồm cả chữ cái và chữ số")

    if current_password is not None and new_password == current_password:
        raise ChangePasswordError("PASSWORD_SAME_AS_CURRENT", "Mật khẩu mới không được trùng với mật khẩu hiện tại")


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    current_session_id: str | None = None,
) -> dict:
    """
    Xử lý đổi mật khẩu (SCRUM-56):
    1. Validate dữ liệu đầu vào & chính sách mật khẩu mới
    2. Lấy user từ MySQL
    3. Xác thực mật khẩu hiện tại bằng check_password_hash
    4. Băm mật khẩu mới bằng generate_password_hash
    5. Cập nhật password_hash vào MySQL
    """
    if not isinstance(current_password, str) or not current_password:
        raise ChangePasswordError("CURRENT_PASSWORD_REQUIRED", "Mật khẩu hiện tại là bắt buộc")

    # Kiểm tra điều kiện mật khẩu mới theo chính sách SCRUM-55
    validate_new_password_policy(new_password, current_password)

    user = user_repository.get_user_by_id(user_id)
    if user is None:
        raise ChangePasswordError("USER_NOT_FOUND", "Không tìm thấy thông tin tài khoản người dùng")

    if not verify_current_password(user.password_hash, current_password):
        raise ChangePasswordError(
            "INCORRECT_CURRENT_PASSWORD",
            "Mật khẩu hiện tại không chính xác",
        )

    # SCRUM-56: Băm mật khẩu mới và lưu vào cơ sở dữ liệu
    new_password_hash = generate_password_hash(new_password)
    user_repository.update_user_password(
        user_id=user.id,
        new_password_hash=new_password_hash,
    )

    return {
        "message": "Đổi mật khẩu thành công.",
    }
