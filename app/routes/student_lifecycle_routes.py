"""
Các endpoint API Quản lý Vòng đời học viên (Student Lifecycle Routes) - SCRUM-252.
Bảo lưu (reserve), Chuyển lớp (transfer), Thôi học (drop) và Danh sách điểm danh theo ngày hiệu lực.
"""

import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from mysql.connector import Error as MySQLError

from app.services import student_lifecycle_service
from app.services.student_lifecycle_service import StudentLifecycleError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

student_lifecycle_bp = Blueprint("student_lifecycle", __name__, url_prefix="/api")


@student_lifecycle_bp.post("/v1/students/<student_id>/reserve")
@student_lifecycle_bp.post("/students/<student_id>/reserve")
@permission_required(
    "student.lifecycle_manage",
    message="Chức năng xử lý bảo lưu học viên chỉ dành riêng cho Quản lý đào tạo.",
)
def reserve_student_endpoint(student_id: str):
    """
    API xử lý bảo lưu học viên trong một lớp học theo ngày hiệu lực (SCRUM-252 - Lát cắt 252.1).
    Phân quyền: Quản lý đào tạo (student.lifecycle_manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
        }), 400

    actor_id = get_jwt_identity()

    try:
        result = student_lifecycle_service.reserve_student_service(student_id, payload, actor_id)
        return jsonify({
            "status": "success",
            "code": "RESERVE_SUCCESS",
            "message": f"Bảo lưu học viên {result.get('student_name', '')} tại lớp {result.get('class_code', '')} thành công.",
            "data": result,
        }), 200
    except StudentLifecycleError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi bảo lưu học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi thực hiện bảo lưu học viên.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi bảo lưu học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu bảo lưu.",
        }), 500


@student_lifecycle_bp.post("/v1/students/<student_id>/transfer")
@student_lifecycle_bp.post("/students/<student_id>/transfer")
@permission_required(
    "student.lifecycle_manage",
    message="Chức năng xử lý chuyển lớp chỉ dành riêng cho Quản lý đào tạo.",
)
def transfer_student_endpoint(student_id: str):
    """
    API xử lý chuyển lớp cho học viên theo ngày hiệu lực (SCRUM-252 - Lát cắt 252.2).
    Phân quyền: Quản lý đào tạo (student.lifecycle_manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
        }), 400

    actor_id = get_jwt_identity()

    try:
        result = student_lifecycle_service.transfer_student_service(student_id, payload, actor_id)
        return jsonify({
            "status": "success",
            "code": "TRANSFER_SUCCESS",
            "message": f"Chuyển lớp cho học viên {result.get('student_name', '')} từ lớp {result.get('source_class_code', '')} sang lớp {result.get('target_class_code', '')} thành công.",
            "data": result,
        }), 200
    except StudentLifecycleError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi chuyển lớp học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi thực hiện chuyển lớp học viên.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi chuyển lớp học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu chuyển lớp.",
        }), 500


@student_lifecycle_bp.post("/v1/students/<student_id>/drop")
@student_lifecycle_bp.post("/students/<student_id>/drop")
@permission_required(
    "student.lifecycle_manage",
    message="Chức năng xử lý thôi học chỉ dành riêng cho Quản lý đào tạo.",
)
def drop_student_endpoint(student_id: str):
    """
    API xử lý thôi học cho học viên theo ngày hiệu lực (SCRUM-252 - Lát cắt 252.3).
    Hỗ trợ scope = 'single' (thôi học 1 lớp) hoặc 'all' (thôi học toàn bộ khóa học).
    Phân quyền: Quản lý đào tạo (student.lifecycle_manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
        }), 400

    actor_id = get_jwt_identity()

    try:
        result = student_lifecycle_service.drop_student_service(student_id, payload, actor_id)
        msg = (
            f"Thôi học học viên {result.get('student_name', '')} toàn bộ khóa học thành công."
            if result.get("scope") == "all"
            else f"Thôi học học viên {result.get('student_name', '')} tại lớp đã chọn thành công."
        )
        return jsonify({
            "status": "success",
            "code": "DROP_SUCCESS",
            "message": msg,
            "data": result,
        }), 200
    except StudentLifecycleError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi thôi học học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi thực hiện thôi học học viên.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi thôi học học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu thôi học.",
        }), 500


@student_lifecycle_bp.get("/v1/classes/<class_id>/eligible-students")
@student_lifecycle_bp.get("/classes/<class_id>/eligible-students")
@permission_required("course.view")
def get_eligible_attendance_students_endpoint(class_id: str):
    """
    API truy vấn danh sách học viên đủ điều kiện điểm danh tại một ngày học cụ thể (SCRUM-252 AC 2).
    - Học viên bảo lưu sẽ không còn xuất hiện từ ngày hiệu lực (session_date >= effective_date).
    - Trước ngày hiệu lực, học viên vẫn xuất hiện bình thường.
    """
    session_date = request.args.get("session_date")
    if not session_date:
        return jsonify({
            "status": "error",
            "code": "MISSING_SESSION_DATE",
            "message": "Vui lòng cung cấp tham số session_date (YYYY-MM-DD).",
        }), 400

    try:
        result = student_lifecycle_service.get_eligible_attendance_students_service(class_id, session_date)
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except StudentLifecycleError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách điểm danh đủ điều kiện: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn danh sách học viên.",
        }), 500


@student_lifecycle_bp.get("/v1/students/<student_id>/lifecycle-history")
@student_lifecycle_bp.get("/students/<student_id>/lifecycle-history")
@permission_required("course.view")
def get_student_lifecycle_history_endpoint(student_id: str):
    """
    API lấy lịch sử biến động vòng đời (bảo lưu, chuyển lớp, thôi học) của học viên (SCRUM-252 AC 4).
    """
    try:
        history = student_lifecycle_service.get_student_lifecycle_history_service(student_id)
        return jsonify({
            "status": "success",
            "data": {
                "student_id": student_id,
                "total": len(history),
                "items": history,
            },
        }), 200
    except StudentLifecycleError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc lịch sử vòng đời học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất lịch sử học viên.",
        }), 500
