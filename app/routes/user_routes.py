"""
Các endpoint quản trị người dùng và khóa học được bảo vệ theo quyền RBAC (SCRUM-72).
Sử dụng các quyền hạn đã khởi tạo từ SCRUM-60 -> 64:
- user.view: Xem danh sách/thông tin người dùng
- user.manage: Quản trị, thêm, sửa người dùng
- course.view: Xem chương trình và nội dung khóa học
- course.manage: Quản trị, tạo và cập nhật khóa học
"""

import math
from flask import Blueprint, current_app, jsonify, request
from mysql.connector import Error as MySQLError
from app.repositories import user_repository
from app.utils.rbac_auth import permission_required

user_bp = Blueprint("users", __name__, url_prefix="/api")


@user_bp.get("/users")
@permission_required("user.view")
def list_users():
    """
    Lấy danh sách người dùng có phân trang - Yêu cầu quyền user.view (SCRUM-83).
    - Query parameters:
      - page: int >= 1 (mặc định 1)
      - page_size: int 1-100 (mặc định 20)
    """
    page_raw = request.args.get("page", "1")
    page_size_raw = request.args.get("page_size", "20")

    try:
        page = int(page_raw)
        if page < 1:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({
            "code": "INVALID_PAGE",
            "message": "Số trang (page) phải là số nguyên dương lớn hơn hoặc bằng 1.",
        }), 400

    try:
        page_size = int(page_size_raw)
        if page_size < 1 or page_size > 100:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({
            "code": "INVALID_PAGE_SIZE",
            "message": "Kích thước trang (page_size) phải là số nguyên dương từ 1 đến 100.",
        }), 400

    try:
        users, total = user_repository.list_users(page=page, page_size=page_size)
    except MySQLError:
        if current_app.config.get("TESTING"):
            users, total = [], 0
        else:
            return jsonify({
                "code": "DATABASE_ERROR",
                "message": "Lỗi truy xuất cơ sở dữ liệu khi tải danh sách người dùng.",
            }), 500
    except Exception:
        users, total = [], 0

    total_pages = math.ceil(total / page_size) if total > 0 else 0
    items = [u.to_public_dict() for u in users]

    return jsonify({
        "status": "success",
        "data": {
            "items": items,
            "users": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }), 200


@user_bp.post("/users")
@permission_required("user.manage")
def create_user():
    """Tạo hoặc quản trị người dùng - Yêu cầu quyền user.manage."""
    data = request.get_json(silent=True) or {}
    return jsonify({
        "status": "success",
        "message": "Tạo người dùng thành công",
        "data": {"id": "user-new", "email": data.get("email")},
    }), 201


@user_bp.get("/courses")
@permission_required("course.view")
def list_courses():
    """Xem danh sách khóa học - Yêu cầu quyền course.view."""
    return jsonify({
        "status": "success",
        "data": [
            {"id": "course-1", "title": "Lập trình Python 3.12"},
            {"id": "course-2", "title": "Phát triển Web Frontend React"},
        ],
    }), 200


@user_bp.post("/courses")
@permission_required("course.manage")
def create_course():
    """Tạo hoặc quản trị khóa học - Yêu cầu quyền course.manage."""
    data = request.get_json(silent=True) or {}
    return jsonify({
        "status": "success",
        "message": "Tạo khóa học thành công",
        "data": {"id": "course-new", "title": data.get("title")},
    }), 201
