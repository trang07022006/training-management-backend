"""
Các endpoint quản trị vai trò người dùng (User Role Management API - SCRUM-96 -> SCRUM-100).
- GET /api/users/<user_id>/roles : Xem danh sách vai trò của một người dùng (SCRUM-96)
- GET /api/roles                : Lấy danh mục các vai trò khả dụng (SCRUM-97)
- POST /api/users/<user_id>/roles: Phân vai trò cho người dùng (SCRUM-98)
- DELETE /api/users/<user_id>/roles/<role_id>: Gỡ vai trò khỏi người dùng (SCRUM-99)
Được bảo vệ bằng RBAC decorator @permission_required (SCRUM-100).
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import user_role_service
from app.services.user_role_service import UserRoleServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

user_role_bp = Blueprint("user_roles", __name__, url_prefix="/api")


@user_role_bp.get("/users/<user_id>/roles")
@permission_required("user.view")
def get_user_roles(user_id: str):
    """
    Xem danh sách vai trò hiện tại của người dùng (SCRUM-96).
    Yêu cầu quyền user.view.
    """
    try:
        data = user_role_service.get_user_roles(user_id)
        return jsonify({
            "status": "success",
            "data": data,
        }), 200
    except UserRoleServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc vai trò người dùng: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu khi đọc vai trò.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc vai trò: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@user_role_bp.get("/roles")
@permission_required("user.view")
def list_available_roles():
    """
    Lấy danh sách các vai trò khả dụng trong hệ thống (SCRUM-97).
    Yêu cầu quyền user.view.
    """
    try:
        items = user_role_service.get_available_roles()
        return jsonify({
            "status": "success",
            "data": {
                "items": items,
            },
        }), 200
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi tải danh mục vai trò: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu khi lấy danh sách vai trò.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi lấy danh sách vai trò: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@user_role_bp.post("/users/<user_id>/roles")
@permission_required("user.manage")
def assign_role_to_user(user_id: str):
    """
    Phân vai trò cho người dùng (SCRUM-98).
    Yêu cầu quyền user.manage.
    """
    body = request.get_json(silent=True) or {}
    role_id_or_code = body.get("role_id") or body.get("role_code") or body.get("role")

    if not role_id_or_code:
        return jsonify({
            "code": "ROLE_REQUIRED",
            "message": "Mã hoặc ID vai trò (role_id hoặc role_code) là bắt buộc.",
        }), 400

    try:
        result = user_role_service.assign_role_to_user(user_id, str(role_id_or_code))
        return jsonify({
            "status": "success",
            "message": "Phân vai trò cho người dùng thành công.",
            "data": result,
        }), 201
    except UserRoleServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi phân vai trò: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu khi phân vai trò.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi phân vai trò: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@user_role_bp.delete("/users/<user_id>/roles/<role_id>")
@permission_required("user.manage")
def revoke_role_from_user(user_id: str, role_id: str):
    """
    Gỡ vai trò khỏi người dùng (SCRUM-99).
    Yêu cầu quyền user.manage.
    """
    try:
        result = user_role_service.revoke_role_from_user(user_id, role_id)
        return jsonify({
            "status": "success",
            "message": "Gỡ vai trò khỏi người dùng thành công.",
            "data": result,
        }), 200
    except UserRoleServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi gỡ vai trò: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi kết nối cơ sở dữ liệu khi gỡ vai trò.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi gỡ vai trò: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
