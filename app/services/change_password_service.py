class ChangePasswordError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    current_session_id: str | None = None,
) -> dict:
    """
    Xử lý đổi mật khẩu (SCRUM-53 boundary).
    Identity được lấy an toàn từ JWT/session, không nhận từ client.
    """
    if not isinstance(current_password, str) or not current_password:
        raise ChangePasswordError("CURRENT_PASSWORD_REQUIRED", "Mật khẩu hiện tại là bắt buộc")

    if not isinstance(new_password, str) or not new_password:
        raise ChangePasswordError("NEW_PASSWORD_REQUIRED", "Mật khẩu mới là bắt buộc")

    return {
        "message": "Yêu cầu đổi mật khẩu hợp lệ",
    }
