from flask_jwt_extended import create_access_token, create_refresh_token


def create_login_tokens(user_id: str, session_id: str):
    """Chỉ gọi sau khi phần login đã xác minh tài khoản và mật khẩu."""

    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id phải là chuỗi không rỗng.")

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id phải là chuỗi không rỗng.")

    claims = {"sid": session_id}

    access_token = create_access_token(
        identity=user_id,
        additional_claims=claims,
    )

    refresh_token = create_refresh_token(
        identity=user_id,
        additional_claims=claims,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }