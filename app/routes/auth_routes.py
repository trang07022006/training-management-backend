from flask import Blueprint, jsonify, request
from flask_jwt_extended import decode_token, get_jwt, get_jwt_identity
from mysql.connector import Error as MySQLError

from app.services.auth_service import (
    AuthValidationError,
    authenticate_and_login,
    process_forgot_password_request,
    reset_password_with_token,
    validate_reset_token,
)
from app.services.change_password_service import (
    ChangePasswordError,
    change_password,
)
from app.utils.session_auth import session_required

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
        status = 403 if error.code in ("ACCOUNT_DISABLED", "ACCOUNT_INACTIVE", "ACCOUNT_LOCKED") else 401
        payload = {"code": error.code}
        if error.message:
            payload["message"] = error.message
        elif error.code == "INVALID_CREDENTIALS":
            payload["message"] = "Email hoặc mật khẩu không đúng"
        elif error.code == "ACCOUNT_LOCKED":
            payload["message"] = "Tài khoản tạm thời bị khóa 15 phút do nhập sai mật khẩu quá 5 lần. Vui lòng thử lại sau."
        elif error.code in ("ACCOUNT_INACTIVE", "ACCOUNT_DISABLED"):
            payload["message"] = "Tài khoản hiện không hoạt động. Vui lòng liên hệ quản trị viên."
        if getattr(error, "locked_until", None):
            payload["locked_until"] = error.locked_until.isoformat()
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
            "name": user.name,
            "role": user.role,
        },
        "session_id": session.session_id,
        "idle_expires_at": session.idle_expires_at.isoformat(),
        "absolute_expires_at": session.absolute_expires_at.isoformat(),
    })
    response.headers["Cache-Control"] = "no-store"

    return response, 200


@auth_bp.post("/forgot-password")
def forgot_password():
    if not request.is_json:
        return jsonify({"code": "INVALID_REQUEST", "message": "Yêu cầu không hợp lệ"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"code": "INVALID_REQUEST", "message": "Yêu cầu không hợp lệ"}), 400

    if "email" not in data:
        return jsonify({"code": "EMAIL_REQUIRED", "message": "Email là bắt buộc"}), 400

    email = data.get("email")

    try:
        result = process_forgot_password_request(email)
        return jsonify(result), 200
    except AuthValidationError as error:
        return jsonify({
            "code": error.code,
            "message": error.message,
        }), 400
    except MySQLError:
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500
    except Exception:
        # Không dùng mock database khi MySQL có lỗi
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500


@auth_bp.post("/reset-password")
def reset_password():
    if not request.is_json:
        return jsonify({"code": "INVALID_REQUEST", "message": "Yêu cầu không hợp lệ"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"code": "INVALID_REQUEST", "message": "Yêu cầu không hợp lệ"}), 400

    token = data.get("token") or data.get("reset_token")
    new_password = data.get("new_password") or data.get("password")

    if not isinstance(token, str) or not token.strip():
        return jsonify({"code": "TOKEN_REQUIRED", "message": "Token là bắt buộc"}), 400

    if not isinstance(new_password, str) or not new_password:
        return jsonify({"code": "PASSWORD_REQUIRED", "message": "Mật khẩu mới là bắt buộc"}), 400

    try:
        result = reset_password_with_token(
            raw_token=token.strip(),
            new_password=new_password,
        )
        return jsonify(result), 200
    except AuthValidationError as error:
        return jsonify({
            "code": error.code,
            "message": error.message,
        }), 400
    except MySQLError:
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500
    except Exception:
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500


@auth_bp.post("/verify-reset-token")
def verify_reset_token():
    if not request.is_json:
        return jsonify({"code": "INVALID_REQUEST", "message": "Yêu cầu không hợp lệ"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"code": "INVALID_REQUEST", "message": "Yêu cầu không hợp lệ"}), 400

    token = data.get("token") or data.get("reset_token")
    if not isinstance(token, str) or not token.strip():
        return jsonify({"code": "TOKEN_REQUIRED", "message": "Token là bắt buộc"}), 400

    try:
        validate_reset_token(raw_token=token.strip())
        return jsonify({"valid": True, "message": "Token hợp lệ"}), 200
    except AuthValidationError as error:
        return jsonify({
            "valid": False,
            "code": error.code,
            "message": error.message,
        }), 400
    except MySQLError:
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500
    except Exception:
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500


@auth_bp.post("/change-password")
@session_required
def change_password_endpoint():
    """
    API đổi mật khẩu cho người dùng đã đăng nhập (SCRUM-53).
    Identity luôn được lấy từ authenticated JWT/session, không tin user_id từ client.
    """
    if not request.is_json:
        return jsonify({
            "code": "INVALID_REQUEST",
            "message": "Payload yêu cầu phải ở định dạng JSON",
        }), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_REQUEST",
            "message": "Payload yêu cầu không hợp lệ",
        }), 400

    current_password = data.get("current_password")
    new_password = data.get("new_password")

    if not isinstance(current_password, str) or not current_password:
        return jsonify({
            "code": "CURRENT_PASSWORD_REQUIRED",
            "message": "Mật khẩu hiện tại là bắt buộc",
        }), 400

    if not isinstance(new_password, str) or not new_password:
        return jsonify({
            "code": "NEW_PASSWORD_REQUIRED",
            "message": "Mật khẩu mới là bắt buộc",
        }), 400

    # Lấy identity từ authenticated JWT/session, tuyệt đối không dùng user_id từ body
    user_id = get_jwt_identity()
    session_id = get_jwt().get("sid")

    try:
        result = change_password(
            user_id=user_id,
            current_password=current_password,
            new_password=new_password,
            current_session_id=session_id,
        )
        return jsonify(result), 200
    except ChangePasswordError as error:
        return jsonify({
            "code": error.code,
            "message": error.message,
        }), 400
    except MySQLError:
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu",
        }), 500
    except Exception:
        return jsonify({
            "code": "SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi đổi mật khẩu",
        }), 500
