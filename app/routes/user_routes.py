"""
Các endpoint quản trị người dùng và khóa học được bảo vệ theo quyền RBAC (SCRUM-72).
Sử dụng các quyền hạn đã khởi tạo từ SCRUM-60 -> 64:
- user.view: Xem danh sách/thông tin người dùng
- user.manage: Quản trị, thêm, sửa người dùng
- course.view: Xem chương trình và nội dung khóa học
- course.manage: Quản trị, tạo và cập nhật khóa học
"""

from flask import Blueprint, jsonify, request
from app.utils.rbac_auth import permission_required

user_bp = Blueprint("users", __name__, url_prefix="/api")


@user_bp.get("/users")
@permission_required("user.view")
def list_users():
    """Lấy danh sách người dùng - Yêu cầu quyền user.view."""
    return jsonify({
        "status": "success",
        "data": [
            {"id": "user-1", "email": "admin@daotao.edu.vn", "role": "admin"},
            {"id": "user-2", "email": "trainer@daotao.edu.vn", "role": "trainer"},
            {"id": "user-3", "email": "trainee@daotao.edu.vn", "role": "trainee"},
        ],
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
