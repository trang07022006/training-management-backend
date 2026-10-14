"""
Decorator kiểm tra quyền truy cập API dựa trên RBAC (@permission_required) (SCRUM-70).
Phân biệt rõ ràng:
- Authentication (401): Chưa đăng nhập hoặc session không hợp lệ/hết hạn.
- Authorization (403): Đã đăng nhập nhưng không có quyền hạn cần thiết.
"""

from functools import wraps
from flask import g, jsonify, request
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    verify_jwt_in_request,
)
from mysql.connector import Error as MySQLError

from app.repositories.session_repository import get_session_by_id
from app.services.authorization_service import has_permission
from app.services.session_service import (
    SessionValidationError,
    validate_login_session,
)


def permission_required(permission_code: str):
    """
    Decorator bảo vệ API endpoint theo permission code (SCRUM-70).
    Luồng kiểm tra:
    1. Xác thực Authentication (JWT + Session trong database). Chưa đăng nhập -> 401.
    2. Xác định identity (user_id từ token/session hợp lệ, không tin client).
    3. Kiểm tra Authorization qua RBAC service / database.
    4. Không đủ quyền -> 403 (FORBIDDEN).
    5. Đủ quyền -> ALLOW.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            # 0. Nguyên tắc Default Deny (SCRUM-71): Nếu permission_code không được cấu hình rõ ràng -> DENY
            if not isinstance(permission_code, str) or not permission_code.strip():
                return jsonify({
                    "code": "FORBIDDEN",
                    "message": "Bạn không có quyền thực hiện thao tác này.",
                }), 403

            # 1. Xác thực JWT authentication
            try:
                verify_jwt_in_request(refresh=False, locations=["headers"])
            except Exception:
                return jsonify({
                    "code": "UNAUTHORIZED",
                    "message": "Yêu cầu đăng nhập để truy cập tài nguyên này",
                }), 401

            session_id = get_jwt().get("sid")
            user_id = get_jwt_identity()

            if any(
                not isinstance(value, str) or not value.strip()
                for value in (session_id, user_id)
            ):
                return jsonify({
                    "code": "SESSION_INVALID",
                    "message": "Phiên làm việc không hợp lệ hoặc thiếu thông tin định danh",
                }), 401

            # 2. Xác thực Session trong database nếu chưa có trong g
            session = getattr(g, "login_session", None)
            if session is None or session.session_id != session_id or session.user_id != user_id:
                try:
                    session = get_session_by_id(session_id)
                    if session is None or session.user_id != user_id:
                        return jsonify({
                            "code": "SESSION_INVALID",
                            "message": "Phiên làm việc không tồn tại hoặc không khớp với người dùng",
                        }), 401
                    validate_login_session(session)
                    g.login_session = session
                except SessionValidationError as error:
                    return jsonify({
                        "code": error.code,
                        "message": "Phiên làm việc đã hết hạn hoặc đã bị thu hồi",
                    }), 401
                except MySQLError:
                    return jsonify({
                        "code": "SESSION_STORAGE_UNAVAILABLE",
                        "message": "Hệ thống lưu trữ phiên tạm thời không khả dụng",
                    }), 503

            # 2.5 Kiểm tra bắt buộc đổi mật khẩu khi đăng nhập lần đầu (SCRUM-215)
            try:
                from app.repositories import user_repository
                user_record = user_repository.get_user_by_id(user_id)
                if user_record and getattr(user_record, "must_change_password", False):
                    return jsonify({
                        "code": "PASSWORD_CHANGE_REQUIRED",
                        "message": "Bạn cần đổi mật khẩu trước khi tiếp tục sử dụng hệ thống.",
                    }), 403
            except Exception:
                pass

            # 3. Kiểm tra Authorization từ database (Default Deny)
            # Tuyệt đối không lấy user_id hoặc permission từ request body/headers/params
            try:
                allowed = has_permission(user_id, permission_code)
            except MySQLError:
                return jsonify({
                    "code": "DATABASE_ERROR",
                    "message": "Lỗi kết nối cơ sở dữ liệu khi kiểm tra quyền hạn",
                }), 500
            except Exception:
                return jsonify({
                    "code": "AUTHORIZATION_ERROR",
                    "message": "Lỗi hệ thống khi kiểm tra quyền hạn",
                }), 500

            if not allowed:
                return jsonify({
                    "code": "FORBIDDEN",
                    "message": "Bạn không có quyền thực hiện thao tác này.",
                }), 403

            return view(*args, **kwargs)

        return wrapped
    return decorator


# Alias hỗ trợ quy ước đặt tên
require_permission = permission_required
