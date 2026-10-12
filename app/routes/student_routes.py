"""
Các endpoint API Quản lý hồ sơ học viên (Student Routes) - SCRUM-216.
- Xem danh sách và tìm kiếm học viên theo mã học viên, tên, số điện thoại
- Xem chi tiết hồ sơ học viên kèm lớp đang học và lịch sử các lớp đã học
- Sửa thông tin cá nhân, trình độ đầu vào, ghi chú
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import student_service
from app.services.student_service import StudentServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

student_bp = Blueprint("students", __name__, url_prefix="/api")


@student_bp.get("/v1/students")
@student_bp.get("/students")
@permission_required("course.view")
def list_students_endpoint():
    """
    API xem danh sách học viên và tìm kiếm (SCRUM-216 - Sub-task 216-01 & 216-03).
    - Phân quyền: Quản lý đào tạo (course.view / course.manage).
    - Query params:
        search: Tìm kiếm theo mã học viên, tên, số điện thoại
        page: Số trang (mặc định 1)
        page_size: Kích thước trang (mặc định 20)
    """
    search = request.args.get("search", default=None)
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = int(request.args.get("page_size", 20))
    except (ValueError, TypeError):
        page_size = 20

    try:
        result = student_service.list_students_service(search=search, page=page, page_size=page_size)
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except StudentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất danh sách học viên.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc danh sách học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@student_bp.get("/v1/students/<student_id>")
@student_bp.get("/students/<student_id>")
@permission_required("course.view")
def get_student_detail_endpoint(student_id: str):
    """
    API xem chi tiết hồ sơ học viên (SCRUM-216 - Sub-task 216-01 & 216-02).
    - Bao gồm: thông tin cá nhân, trình độ đầu vào, ghi chú, lớp đang học và lịch sử lớp.
    """
    try:
        data = student_service.get_student_detail_service(student_id)
        return jsonify({
            "status": "success",
            "data": data,
        }), 200
    except StudentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc chi tiết học viên %s: %s", student_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi đọc hồ sơ học viên.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc chi tiết học viên %s: %s", student_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@student_bp.put("/v1/students/<student_id>")
@student_bp.put("/students/<student_id>")
@student_bp.patch("/v1/students/<student_id>")
@student_bp.patch("/students/<student_id>")
@permission_required("course.manage")
def update_student_profile_endpoint(student_id: str):
    """
    API cập nhật thông tin hồ sơ học viên (SCRUM-216 - Sub-task 216-01).
    - Sửa thông tin cá nhân (full_name, phone, email)
    - Sửa trình độ đầu vào (entry_level)
    - Sửa ghi chú (notes)
    """
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
        }), 400

    try:
        updated = student_service.update_student_profile_service(student_id, body)
        return jsonify({
            "status": "success",
            "message": "Cập nhật hồ sơ học viên thành công.",
            "data": updated,
        }), 200
    except StudentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật hồ sơ học viên %s: %s", student_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật hồ sơ học viên.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi cập nhật hồ sơ học viên %s: %s", student_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
