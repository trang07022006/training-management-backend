from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity
from mysql.connector import Error as MySQLError

from app.services.change_password_service import (
    ChangePasswordError,
    change_password,
)
from app.utils.session_auth import session_required

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


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
