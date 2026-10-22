"""
Các endpoint API Quản lý hồ sơ học viên (Student Routes) - SCRUM-216.
- Xem danh sách và tìm kiếm học viên theo mã học viên, tên, số điện thoại
- Xem chi tiết hồ sơ học viên kèm lớp đang học và lịch sử các lớp đã học
- Sửa thông tin cá nhân, trình độ đầu vào, ghi chú
"""

import logging
from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity
from mysql.connector import Error as MySQLError

from app.services import schedule_service, student_service
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
    user_id = getattr(g, "user_id", None) or get_jwt_identity()
    from app.services import authorization_service
    roles = authorization_service.get_user_role_codes(user_id) if user_id else []
    if "trainee" in roles and not any(r in roles for r in ["admin", "training_manager", "trainer", "teacher"]):
        return jsonify({
            "status": "error",
            "code": "FORBIDDEN",
            "message": "Học viên không có quyền xem danh sách toàn bộ học viên.",
        }), 403

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



@student_bp.get("/v1/students/my-schedule")
@student_bp.get("/students/my-schedule")
@permission_required("schedule.personal_view")
def get_my_schedule_endpoint():
    """
    API xem thời khóa biểu cá nhân của học viên hoặc giảng viên đăng nhập (SCRUM-228).
    - Bảo mật: Xác thực danh tính từ JWT/phiên đăng nhập (g.user_id), không tin cậy query/body client gửi lên.
    - Phân quyền: Yêu cầu quyền schedule.personal_view và vai trò học viên hoặc giảng viên.
    - Quản trị viên/quản lý đào tạo không có vai trò học viên/giảng viên sẽ bị từ chối với 403.
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Yêu cầu đăng nhập để truy cập tài nguyên này.",
        }), 401

    from app.services import authorization_service
    roles = authorization_service.get_user_role_codes(user_id)
    if roles and not ("trainee" in roles or "trainer" in roles):
        return jsonify({
            "status": "error",
            "code": "FORBIDDEN",
            "message": "Tài khoản quản trị không sử dụng lịch cá nhân. Vui lòng truy cập trang Thời khóa biểu.",
        }), 403

    # Tuyệt đối không cho phép đổi student_id hoặc user_id trong query params (SCRUM-228 Requirement 3)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    ref_date = request.args.get("ref_date")
    ref_time = request.args.get("ref_time")
    context = request.args.get("context")

    try:
        data = schedule_service.get_my_personal_schedule_service(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            ref_date=ref_date,
            ref_time=ref_time,
            context=context,
        )
        return jsonify({
            "status": "success",
            "code": "MY_SCHEDULE_RETRIEVED",
            "data": data,
        }), 200
    except schedule_service.ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except Exception as err:
        logger.exception("Lỗi khi lấy lịch cá nhân của user %s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@student_bp.get("/v1/students/<student_id>/schedule")
@student_bp.get("/students/<student_id>/schedule")
@permission_required("schedule.manage", message="Chức năng xem lịch học viên chỉ dành riêng cho cán bộ quản lý đào tạo.")
def get_student_schedule_management_endpoint(student_id: str):
    """
    API quản lý: xem thời khóa biểu của một học viên bất kỳ (SCRUM-228 Requirement 3).
    Dành riêng cho Quản trị viên và Quản lý đào tạo (yêu cầu quyền schedule.view).
    """
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    ref_date = request.args.get("ref_date")
    ref_time = request.args.get("ref_time")

    try:
        data = schedule_service.get_student_schedule_by_student_id_service(
            student_id=student_id,
            date_from=date_from,
            date_to=date_to,
            ref_date=ref_date,
            ref_time=ref_time,
        )
        return jsonify({
            "status": "success",
            "code": "STUDENT_SCHEDULE_RETRIEVED",
            "data": data,
        }), 200
    except schedule_service.ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except Exception as err:
        logger.exception("Lỗi khi quản lý đọc lịch học viên %s: %s", student_id, err)
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
    user_id = getattr(g, "user_id", None) or get_jwt_identity()
    from app.services import authorization_service
    from app.repositories import student_repository
    roles = authorization_service.get_user_role_codes(user_id) if user_id else []
    if "trainee" in roles and not any(r in roles for r in ["admin", "training_manager", "trainer", "teacher"]):
        my_student = student_repository.get_student_by_user_id(user_id)
        if not my_student or str(my_student.id) != str(student_id):
            return jsonify({
                "status": "error",
                "code": "FORBIDDEN",
                "message": "Bạn không có quyền truy cập hồ sơ của học viên khác.",
            }), 403

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


@student_bp.get("/v1/students/<student_id>/absence-alerts")
@student_bp.get("/students/<student_id>/absence-alerts")
@permission_required(["course.view", "attendance.view"])
def get_student_absence_alerts_endpoint(student_id: str):
    """
    API xem danh sách cảnh báo vắng vượt ngưỡng đang hoạt động của học viên (SCRUM-257 - AC2).
    - Hiển thị trên hồ sơ học viên (Student Profile)
    - Trả về danh sách cảnh báo theo từng lớp đang vượt ngưỡng
    - Tự động lọc bỏ các cảnh báo đã tắt
    """
    user_id = getattr(g, "user_id", None) or get_jwt_identity()
    from app.services import authorization_service
    from app.repositories import student_repository
    roles = authorization_service.get_user_role_codes(user_id) if user_id else []
    if "trainee" in roles and not any(r in roles for r in ["admin", "training_manager", "trainer", "teacher"]):
        my_student = student_repository.get_student_by_user_id(user_id)
        if not my_student or str(my_student.id) != str(student_id):
            return jsonify({
                "status": "error",
                "code": "FORBIDDEN",
                "message": "Bạn không có quyền truy cập cảnh báo của học viên khác.",
            }), 403

    from app.services import absence_alert_service
    try:
        alerts = absence_alert_service.get_student_profile_absence_alerts_service(
            student_id=student_id,
            current_user_id=user_id,
        )
        return jsonify({
            "status": "success",
            "data": alerts,
        }), 200
    except Exception as err:
        logger.exception("Lỗi khi đọc cảnh báo vắng của học viên %s: %s", student_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
