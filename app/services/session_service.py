import secrets
from datetime import datetime, timezone
from dataclasses import replace
from app.repositories import session_repository
from flask import current_app
from flask_jwt_extended import decode_token

from app.models.login_session import LoginSession
from app.services.token_service import create_login_tokens


class SessionValidationError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def create_login_session(user_id: str):
    """Chỉ gọi sau khi phần login đã xác minh tài khoản và mật khẩu."""

    session_id = secrets.token_hex(16)
    created_at = datetime.now(timezone.utc)

    tokens = create_login_tokens(user_id, session_id)
    refresh_payload = decode_token(tokens["refresh_token"])

    absolute_expires_at = datetime.fromtimestamp(
        refresh_payload["exp"],
        tz=timezone.utc,
    )

    idle_timeout = current_app.config["SESSION_IDLE_TIMEOUT"]

    idle_expires_at = min(
        created_at + idle_timeout,
        absolute_expires_at,
    )

    session = LoginSession(
        session_id=session_id,
        user_id=user_id,
        refresh_jti=refresh_payload["jti"],
        created_at=created_at,
        last_activity_at=created_at,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )

    return session, tokens
def renew_login_session(
    session: LoginSession,
    now: datetime | None = None,
) -> LoginSession:
    current_time = now if now is not None else datetime.now(timezone.utc)

    # Phiên hết hạn hoặc bị thu hồi không được gia hạn.
    validate_login_session(session, now=current_time)

    idle_timeout = current_app.config["SESSION_IDLE_TIMEOUT"]

    new_idle_expires_at = min(
        current_time + idle_timeout,
        session.absolute_expires_at,
    )

    return replace(
        session,
        last_activity_at=current_time,
        idle_expires_at=new_idle_expires_at,
    )


def validate_login_session(
    session: LoginSession,
    now: datetime | None = None,
):
    current_time = now if now is not None else datetime.now(timezone.utc)

    if session.revoked_at is not None:
        raise SessionValidationError("SESSION_REVOKED")

    if current_time >= session.absolute_expires_at:
        raise SessionValidationError("SESSION_EXPIRED")

    if current_time >= session.idle_expires_at:
        raise SessionValidationError("SESSION_EXPIRED")
        
def _get_valid_stored_session(
    session_id: str,
    user_id: str,
    refresh_jti: str,
    now: datetime,
) -> LoginSession:
    session = session_repository.get_session_by_id(session_id)

    if session is None or session.user_id != user_id:
        raise SessionValidationError("SESSION_INVALID")

    if session.refresh_jti != refresh_jti:
        raise SessionValidationError("REFRESH_TOKEN_INVALID")

    validate_login_session(session, now=now)

    return session


def renew_stored_session(
    session_id: str,
    user_id: str,
    refresh_jti: str,
    now: datetime | None = None,
) -> LoginSession:
    """Các thông tin định danh phải lấy từ refresh JWT đã được xác minh."""

    current_time = now if now is not None else datetime.now(timezone.utc)

    original_session = _get_valid_stored_session(
        session_id,
        user_id,
        refresh_jti,
        current_time,
    )

    renewed_session = renew_login_session(
        original_session,
        now=current_time,
    )

    updated = session_repository.update_session_activity(
        original_session,
        renewed_session,
    )

    if not updated:
        # Đọc lại để biết phiên vừa bị thu hồi/hết hạn hay chỉ bị cập nhật.
        _get_valid_stored_session(
            session_id,
            user_id,
            refresh_jti,
            current_time,
        )

        raise SessionValidationError("SESSION_UPDATE_CONFLICT")

    return renewed_session