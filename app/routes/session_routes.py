from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from mysql.connector import Error as MySQLError

from app.services.session_service import (
    SessionValidationError,
    renew_stored_session,
)


session_bp = Blueprint(
    "session",
    __name__,
    url_prefix="/api/auth",
)


@session_bp.post("/refresh")
@jwt_required(refresh=True, locations=["headers"])
def refresh_session():
    # Chỉ đọc thông tin từ JWT đã được xác minh.
    claims = get_jwt()
    user_id = get_jwt_identity()
    session_id = claims.get("sid")
    refresh_jti = claims.get("jti")

    identifiers = (user_id, session_id, refresh_jti)

    if any(
        not isinstance(value, str) or not value.strip()
        for value in identifiers
    ):
        return jsonify({"code": "REFRESH_TOKEN_INVALID"}), 401

    try:
        session = renew_stored_session(
            session_id=session_id,
            user_id=user_id,
            refresh_jti=refresh_jti,
        )
    except SessionValidationError as error:
        status = (
            409
            if error.code == "SESSION_UPDATE_CONFLICT"
            else 401
        )
        return jsonify({"code": error.code}), status
    except MySQLError:
        return jsonify({"code": "SESSION_STORAGE_UNAVAILABLE"}), 503

    # Tính lại thời gian sau khi thao tác với database.
    now = datetime.now(timezone.utc)

    access_deadline = min(
        now + current_app.config["JWT_ACCESS_TOKEN_EXPIRES"],
        session.idle_expires_at,
        session.absolute_expires_at,
    )

    # JWT lưu thời điểm hết hạn bằng số giây Unix.
    expires_at = int(access_deadline.timestamp())

    if expires_at <= int(now.timestamp()):
        return jsonify({"code": "SESSION_EXPIRED"}), 401

    access_token = create_access_token(
        identity=user_id,
        additional_claims={
            "sid": session.session_id,
            "exp": expires_at,
        },
    )

    response = jsonify({
        "access_token": access_token,
        "token_type": "Bearer",
        "access_expires_at": expires_at,
        "idle_expires_at": session.idle_expires_at.isoformat(),
        "absolute_expires_at": session.absolute_expires_at.isoformat(),
    })
    response.headers["Cache-Control"] = "no-store"

    return response, 200