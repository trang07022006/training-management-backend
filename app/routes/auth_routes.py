from flask import Blueprint, jsonify, request
from flask_jwt_extended import decode_token
from mysql.connector import Error as MySQLError

from app.services.auth_service import AuthValidationError, authenticate_and_login

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/api/auth",
)


@auth_bp.post("/login")
def login():
    if not request.is_json:
        return jsonify({"code": "INVALID_REQUEST"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"code": "INVALID_REQUEST"}), 400

    email = data.get("email")
    password = data.get("password")

    if not isinstance(email, str) or not email.strip():
        return jsonify({"code": "EMAIL_REQUIRED"}), 400

    if not isinstance(password, str) or not password:
        return jsonify({"code": "PASSWORD_REQUIRED"}), 400

    try:
        user, session, tokens = authenticate_and_login(
            email=email.strip(),
            password=password,
        )
    except AuthValidationError as error:
        status = 403 if error.code == "ACCOUNT_DISABLED" else 401
        payload = {"code": error.code}
        if error.message:
            payload["message"] = error.message
        elif error.code == "INVALID_CREDENTIALS":
            payload["message"] = "Email hoặc mật khẩu không đúng"
        return jsonify(payload), status
    except MySQLError:
        return jsonify({"code": "SESSION_STORAGE_UNAVAILABLE"}), 503

    access_payload = decode_token(tokens["access_token"])

    response = jsonify({
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "Bearer",
        "access_expires_at": access_payload["exp"],
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
        },
        "session_id": session.session_id,
        "idle_expires_at": session.idle_expires_at.isoformat(),
        "absolute_expires_at": session.absolute_expires_at.isoformat(),
    })
    response.headers["Cache-Control"] = "no-store"

    return response, 200
