from datetime import datetime, timezone
from flask import Blueprint, current_app, g, jsonify
from app.utils.session_auth import session_required
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from mysql.connector import Error as MySQLError

from app.services.session_service import (
    SessionValidationError,
    logout_stored_session,
    renew_stored_session,
)
from app.repositories import user_repository, user_role_repository
from app.services import authorization_service


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

@session_bp.post("/logout")
@jwt_required(locations=["headers"])
def logout_session():
    session_id = get_jwt().get("sid")
    user_id = get_jwt_identity()

    try:
        logout_stored_session(
            session_id=session_id,
            user_id=user_id,
        )
    except SessionValidationError as error:
        return jsonify({"code": error.code}), 401
    except MySQLError:
        return jsonify({"code": "SESSION_STORAGE_UNAVAILABLE"}), 503

    return "", 204

@session_bp.get("/session")
@session_required
def current_session():
    session = g.login_session
    user_id = session.user_id

    try:
        user = user_repository.get_user_by_id(user_id)
    except Exception:
        user = None

    try:
        user_roles = user_role_repository.get_role_codes_by_user_id(user_id)
    except Exception:
        user_roles = []

    if not user_roles and user and user.role:
        user_roles = [user.role]

    try:
        effective_permissions = authorization_service.get_user_permissions(user_id)
    except Exception:
        effective_permissions = []

    if user and user.role and user.role in user_roles:
        display_role = user.role
    else:
        try:
            display_role = user_role_repository.get_primary_role_code_by_user_id(user_id) or (user.role if user else "user")
        except Exception:
            display_role = user.role if user else "user"

    response = jsonify({
        "user_id": session.user_id,
        "idle_expires_at": session.idle_expires_at.isoformat(),
        "absolute_expires_at": session.absolute_expires_at.isoformat(),
        "role": display_role,
        "roles": user_roles,
        "permissions": effective_permissions,
    })
    response.headers["Cache-Control"] = "no-store"

    return response, 200