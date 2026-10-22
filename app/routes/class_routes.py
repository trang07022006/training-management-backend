"""
Các endpoint API Quản lý Lớp học (Class Routes) - SCRUM-217.
- Khai báo và mở lớp từ chương trình đào tạo (217-01)
- Kiểm tra mã lớp duy nhất (217-02)
- Cập nhật và xem vòng đời lớp: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ (217-03)
- Xem danh sách môn học sao chép của lớp (217-04)
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import class_service
from app.services.class_service import ClassServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

class_bp = Blueprint("classes", __name__, url_prefix="/api")


@class_bp.post("/v1/classes")
@class_bp.post("/classes")
@permission_required("course.manage")
def create_class_endpoint():
    """
    API mở lớp học mới từ chương trình đào tạo (SCRUM-217 - Sub-task 217-01).
    Phân quyền: Quản lý đào tạo (course.manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    try:
        created = class_service.create_class_service(payload)
        return jsonify({
            "status": "success",
            "code": "CLASS_CREATED",
            "message": "Mở lớp học từ chương trình đào tạo thành công.",
            "data": created,
        }), 201
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi mở lớp học: %s", err)
        err_msg = str(err)
        if getattr(err, "errno", None) == 1062 or "1062" in err_msg or "Duplicate entry" in err_msg:
            return jsonify({
                "status": "error",
                "code": "CLASS_CODE_ALREADY_EXISTS",
                "message": "Mã lớp đã tồn tại. Vui lòng chọn mã lớp khác.",
            }), 409
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu thông tin lớp học.",
        }), 500


@class_bp.get("/v1/classes")
@class_bp.get("/classes")
@permission_required("course.view")
def list_classes_endpoint():
    """
    API lấy danh sách lớp học có lọc theo chương trình, trạng thái, tìm kiếm.
    """
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    search = request.args.get("search")
    date_from = request.args.get("date_from") or request.args.get("from_date")
    date_to = request.args.get("date_to") or request.args.get("to_date")
    instructor_id = request.args.get("instructor_id")

    # Scope giảng viên (SCRUM-220 - 220-03): Giảng viên chỉ thấy lớp mình được phân công
    try:
        from flask_jwt_extended import get_jwt_identity
        from app.repositories import user_repository, user_role_repository
        current_user_id = get_jwt_identity()
        if current_user_id:
            user_record = user_repository.get_user_by_id(current_user_id)
            user_roles = set(user_role_repository.get_role_codes_by_user_id(current_user_id))
            if user_record and getattr(user_record, "role", None):
                user_roles.add(user_record.role)
            if "trainer" in user_roles and not (user_roles & {"admin", "training_manager"}):
                instructor_id = user_record.id
    except Exception:
        pass
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = int(request.args.get("page_size", 20))
    except (ValueError, TypeError):
        page_size = 20

    try:
        result = class_service.list_classes_service(
            program_id=program_id,
            status=status,
            search=search,
            date_from=date_from,
            date_to=date_to,
            instructor_id=instructor_id,
            page=page,
            page_size=page_size,
        )
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất danh sách lớp học.",
        }), 500


@class_bp.get("/v1/classes/<class_id>")
@class_bp.get("/classes/<class_id>")
@permission_required("course.view")
def get_class_detail_endpoint(class_id: str):
    """
    API xem chi tiết thông tin lớp học kèm danh sách môn học đã sao chép (217-01 & 217-04).
    """
    try:
        detail = class_service.get_class_detail_service(class_id)
        return jsonify({
            "status": "success",
            "data": detail,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy chi tiết lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất thông tin lớp học.",
        }), 500


@class_bp.route("/v1/classes/<class_id>/status", methods=["PUT", "PATCH"])
@class_bp.route("/classes/<class_id>/status", methods=["PUT", "PATCH"])
@permission_required("course.manage")
def update_class_status_endpoint(class_id: str):
    """
    API cập nhật vòng đời trạng thái lớp học (SCRUM-217 - Sub-task 217-03).
    4 trạng thái hợp lệ: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "status" not in payload:
        return jsonify({
            "status": "error",
            "code": "STATUS_REQUIRED",
            "message": "Trạng thái mới của lớp học là bắt buộc.",
        }), 400

    new_status = payload.get("status")
    try:
        updated = class_service.update_class_lifecycle_status_service(class_id, new_status)
        return jsonify({
            "status": "success",
            "code": "STATUS_UPDATED",
            "message": f"Cập nhật trạng thái lớp học thành '{updated['status_label']}' thành công.",
            "data": updated,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật trạng thái lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật trạng thái lớp học.",
        }), 500


@class_bp.get("/v1/classes/<class_id>/subjects")
@class_bp.get("/classes/<class_id>/subjects")
@permission_required("course.view")
def get_class_subjects_endpoint(class_id: str):
    """
    API xem riêng danh sách môn học của lớp đã sao chép từ chương trình (217-04).
    """
    try:
        subjects = class_service.get_class_subjects_service(class_id)
        return jsonify({
            "status": "success",
            "data": subjects,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy danh sách môn học của lớp: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất môn học của lớp.",
        }), 500


@class_bp.get("/v1/classes/<class_id>/subjects/<class_subject_id>/instructors")
@class_bp.get("/classes/<class_id>/subjects/<class_subject_id>/instructors")
@permission_required("course.view")
def get_class_subject_instructors_endpoint(class_id: str, class_subject_id: str):
    """
    API xem phân công giảng viên chính và trợ giảng của một môn trong lớp (SCRUM-220).
    Phân quyền: course.view.
    """
    try:
        result = class_service.get_class_subject_instructors_service(class_id, class_subject_id)
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách phân công giảng viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất thông tin phân công giảng viên.",
        }), 500


@class_bp.post("/v1/classes/<class_id>/subjects/<class_subject_id>/instructors")
@class_bp.post("/classes/<class_id>/subjects/<class_subject_id>/instructors")
@class_bp.put("/v1/classes/<class_id>/subjects/<class_subject_id>/instructors")
@class_bp.put("/classes/<class_id>/subjects/<class_subject_id>/instructors")
@permission_required("course.manage")
def assign_instructors_endpoint(class_id: str, class_subject_id: str):
    """
    API phân công giảng viên chính và trợ giảng theo từng môn của lớp (SCRUM-220).
    Phân quyền: Quản lý đào tạo (course.manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    try:
        result = class_service.assign_instructors_service(class_id, class_subject_id, payload)
        return jsonify({
            "status": "success",
            "code": "INSTRUCTORS_ASSIGNED",
            "message": "Phân công giảng viên và trợ giảng cho môn học thành công.",
            "data": result,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi phân công giảng viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu thông tin phân công giảng viên.",
        }), 500


@class_bp.get("/v1/classes/instructors/candidates")
@class_bp.get("/classes/instructors/candidates")
@permission_required("course.view")
def get_instructor_candidates_endpoint():
    """
    API lấy danh sách ứng viên giảng viên để phân công môn học (SCRUM-220).
    Chỉ yêu cầu quyền xem lớp/khóa học (course.view), không cần quyền quản trị tài khoản toàn bộ.
    """
    try:
        candidates = class_service.get_instructor_candidates_service()
        return jsonify({
            "status": "success",
            "data": candidates,
        }), 200
    except Exception as err:
        logger.error("Lỗi khi lấy danh sách ứng viên giảng viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "CANDIDATE_FETCH_FAILED",
            "message": "Không thể tải danh sách giảng viên. Vui lòng thử lại sau.",
        }), 500


@class_bp.get("/v1/classes/<class_id>/attendance-summary")
@class_bp.get("/classes/<class_id>/attendance-summary")
@permission_required(["attendance.view", "attendance.take", "course.view"])
def get_class_attendance_summary_endpoint(class_id: str):
    """
    API Bảng chuyên cần tổng hợp theo lớp học (SCRUM-256).
    """
    from flask import g
    from app.services import attendance_summary_service, authorization_service
    from app.services.attendance_summary_service import AttendanceServiceError

    user_id = getattr(g, "user_id", None)
    try:
        roles = authorization_service.get_user_role_codes(user_id) if user_id else []
        page = request.args.get("page", default=1, type=int)
        page_size = request.args.get("page_size", default=None, type=int)
        if page_size is None:
            page_size = request.args.get("limit", default=20, type=int)

        search_query = request.args.get("search", default=None, type=str)
        if search_query is None:
            search_query = request.args.get("q", default=None, type=str)

        sort_by = request.args.get("sort_by", default="student_code", type=str)
        sort_order = request.args.get("sort_order", default="asc", type=str)
        subject_id = request.args.get("subject_id", default=None, type=str)

        data = attendance_summary_service.get_class_attendance_summary(
            class_id=class_id,
            current_user_id=user_id,
            current_user_roles=roles,
            page=page,
            page_size=page_size,
            search_query=search_query,
            sort_by=sort_by,
            sort_order=sort_order,
            subject_id=subject_id,
        )
        return jsonify({
            "status": "success",
            "code": "CLASS_ATTENDANCE_SUMMARY_SUCCESS",
            "message": "Truy xuất bảng chuyên cần tổng hợp của lớp thành công.",
            "data": data,
        }), 200
    except AttendanceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": getattr(err, "data", None),
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi truy xuất bảng chuyên cần lớp %s: %s", class_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn bảng chuyên cần tổng hợp.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không xác định khi tải bảng chuyên cần tổng hợp lớp %s: %s", class_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi tải bảng chuyên cần tổng hợp.",
        }), 500

