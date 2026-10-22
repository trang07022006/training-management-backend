"""
Các endpoint API Quản lý Ghi danh học viên vào lớp (Enrollment Routes) - SCRUM-218.
- Ghi danh học viên đơn lẻ hoặc hàng loạt (218-01)
- Chặn ghi danh khi lớp đầy hoặc học viên đã có trong lớp (218-02)
- Ghi nhận ngày ghi danh và người thực hiện (218-03)
"""

import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity
from mysql.connector import Error as MySQLError

from app.services import enrollment_service
from app.services.enrollment_service import EnrollmentServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

enrollment_bp = Blueprint("enrollments", __name__, url_prefix="/api")


@enrollment_bp.post("/v1/classes/<class_id>/enrollments")
@enrollment_bp.post("/classes/<class_id>/enrollments")
@permission_required("course.manage")
def enroll_students_endpoint(class_id: str):
    """
    API Ghi danh học viên vào lớp (đơn lẻ hoặc hàng loạt) - SCRUM-218.
    Phân quyền: Quản lý đào tạo (course.manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    actor_id = get_jwt_identity()

    try:
        result = enrollment_service.enroll_students_service(class_id, payload, actor_id)
        return jsonify({
            "status": "success",
            "code": "ENROLLMENT_SUCCESS",
            "message": f"Ghi danh {result['enrolled_count']} học viên vào lớp thành công.",
            "data": result,
        }), 201
    except EnrollmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi ghi danh học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xử lý ghi danh.",
        }), 500


@enrollment_bp.get("/v1/classes/<class_id>/enrollments")
@enrollment_bp.get("/classes/<class_id>/enrollments")
@permission_required("course.view")
def get_class_roster_endpoint(class_id: str):
    """
    API Xem danh sách học viên trong lớp (Roster) - SCRUM-218.
    Bảo mật: Học viên (trainee) chỉ được xem lớp mình đã ghi danh, và response chỉ trả về STT + Họ tên.
    """
    from flask import g
    from app.services import authorization_service
    from app.repositories import student_repository, enrollment_repository

    user_id = getattr(g, "user_id", None) or get_jwt_identity()
    roles = authorization_service.get_user_role_codes(user_id) if user_id else []
    is_trainee = "trainee" in roles and not any(r in roles for r in ["admin", "training_manager", "trainer", "teacher"])

    if is_trainee:
        my_student = student_repository.get_student_by_user_id(user_id)
        if not my_student or not enrollment_repository.is_student_enrolled_in_class(class_id, my_student.id):
            return jsonify({
                "status": "error",
                "code": "FORBIDDEN_CLASS_ACCESS",
                "message": "Học viên chỉ được xem danh sách lớp mà mình đã ghi danh.",
            }), 403

    try:
        result = enrollment_service.get_class_roster_service(class_id, for_trainee=is_trainee)
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except EnrollmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi xem danh sách lớp: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất danh sách lớp.",
        }), 500
