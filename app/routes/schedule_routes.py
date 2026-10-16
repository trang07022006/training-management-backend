"""
Routes API quản lý Thời khóa biểu lớp học (Schedule Routes) - SCRUM-224.
- POST /api/v1/classes/<class_id>/schedules/preview: Xem trước lịch sinh tự động
- POST /api/v1/classes/<class_id>/schedules/generate: Xác nhận lưu lịch học chính thức
- GET /api/v1/classes/<class_id>/schedules: Lấy danh sách thời khóa biểu lớp học
- DELETE /api/v1/classes/<class_id>/schedules: Xoá thời khóa biểu của lớp học
"""

import logging
import uuid
from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity
from mysql.connector import Error as MySQLError

from app.services import schedule_service
from app.services.schedule_service import ScheduleConflictError, ScheduleServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedules", __name__, url_prefix="/api")


@schedule_bp.post("/v1/classes/<class_id>/schedules/preview")
@schedule_bp.post("/classes/<class_id>/schedules/preview")
@permission_required("schedule.manage", message="Bạn không có quyền tạo hoặc xem trước thời khóa biểu cho lớp này.")
def preview_schedule_endpoint(class_id: str):
    """
    API xem trước thời khóa biểu sinh tự động theo mẫu lặp (SCRUM-224 - AC 3).
    Không ghi vào cơ sở dữ liệu.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    try:
        preview_data = schedule_service.preview_schedule_service(class_id, payload)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_PREVIEW_GENERATED",
            "message": "Xem trước thời khóa biểu thành công.",
            "data": preview_data,
        }), 200
    except ScheduleServiceError as err:
        resp = {
            "status": "error",
            "code": err.code,
            "message": err.message,
        }
        if err.field:
            resp["field"] = err.field
        if err.data is not None:
            resp["data"] = err.data
        return jsonify(resp), err.status_code
    except (MySQLError, Exception) as err:
        error_ref = f"ERR-{uuid.uuid4().hex[:8].upper()}"
        logger.exception("Lỗi máy chủ khi xem trước thời khóa biểu [%s]: %s", error_ref, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": f"Đã xảy ra lỗi máy chủ trong quá trình xem trước thời khóa biểu. Vui lòng thử lại sau. (Mã tra cứu: {error_ref})",
            "error_ref": error_ref,
        }), 500


@schedule_bp.post("/v1/classes/<class_id>/schedules/generate")
@schedule_bp.post("/classes/<class_id>/schedules/generate")
@permission_required("schedule.manage", message="Bạn không có quyền quản lý và lưu thời khóa biểu cho lớp này.")
def generate_schedule_endpoint(class_id: str):
    """
    API xác nhận lưu thời khóa biểu lớp học chính thức (SCRUM-224 - AC 1, 2, 4).
    Kiểm tra chống tạo trùng lặp qua cờ overwrite.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    actor_user_id = getattr(g, "user_id", None)
    try:
        saved_data = schedule_service.generate_schedule_service(class_id, payload, actor_user_id=actor_user_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_SAVED",
            "message": "Lưu thời khóa biểu lớp học thành công.",
            "data": saved_data,
        }), 201
    except ScheduleConflictError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": {
                "conflicts": err.conflicts,
            },
        }), err.status_code
    except ScheduleServiceError as err:
        resp = {
            "status": "error",
            "code": err.code,
            "message": err.message,
        }
        if err.field:
            resp["field"] = err.field
        if err.data is not None:
            resp["data"] = err.data
        return jsonify(resp), err.status_code
    except (MySQLError, Exception) as err:
        error_ref = f"ERR-{uuid.uuid4().hex[:8].upper()}"
        logger.exception("Lỗi máy chủ khi lưu thời khóa biểu [%s]: %s", error_ref, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": f"Đã xảy ra lỗi máy chủ trong quá trình lưu thời khóa biểu. Vui lòng thử lại sau. (Mã tra cứu: {error_ref})",
            "error_ref": error_ref,
        }), 500


@schedule_bp.get("/v1/classes/<class_id>/schedules")
@schedule_bp.get("/classes/<class_id>/schedules")
@permission_required("schedule.view")
def get_class_schedules_endpoint(class_id: str):
    """
    API lấy danh sách thời khóa biểu của một lớp học.
    """
    try:
        data = schedule_service.get_class_schedules_service(class_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULES_RETRIEVED",
            "message": "Lấy danh sách thời khóa biểu thành công.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi lấy thời khóa biểu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải lịch học.",
        }), 500


@schedule_bp.delete("/v1/classes/<class_id>/schedules")
@schedule_bp.delete("/classes/<class_id>/schedules")
@permission_required("schedule.manage")
def delete_class_schedules_endpoint(class_id: str):
    """
    API xóa toàn bộ thời khóa biểu của một lớp học.
    """
    try:
        data = schedule_service.delete_class_schedules_service(class_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULES_DELETED",
            "message": "Xóa thời khóa biểu thành công.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi xóa thời khóa biểu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xóa lịch học.",
        }), 500


@schedule_bp.put("/v1/classes/<class_id>/schedules/<schedule_id>")
@schedule_bp.put("/classes/<class_id>/schedules/<schedule_id>")
@permission_required("schedule.manage")
def update_schedule_item_endpoint(class_id: str, schedule_id: str):
    """
    API sửa hoặc dời một buổi học đơn lẻ (SCRUM-226 AC 1, AC 3, AC 4).
    - Đổi ngày, giờ, ca, phòng, giảng viên dạy thay.
    - Chặn sửa buổi học đã điểm danh (AC 4).
    - Tái sử dụng kiểm tra xung đột SCRUM-225 (loại trừ chính buổi đang sửa).
    - Gửi thông báo thay đổi tới học viên và giảng viên của lớp (AC 3).
    """
    payload = request.get_json(silent=True) or {}
    actor_user_id = getattr(g, "user_id", None)
    try:
        data = schedule_service.update_single_schedule_service(class_id, schedule_id, payload, actor_user_id=actor_user_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_UPDATED",
            "message": "Cập nhật buổi học thành công.",
            "data": data,
        }), 200
    except ScheduleConflictError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": {
                "conflicts": err.conflicts,
                "has_conflicts": True,
            },
        }), err.status_code
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi cập nhật buổi học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật lịch học.",
        }), 500


@schedule_bp.post("/v1/classes/<class_id>/schedules/<schedule_id>/cancel")
@schedule_bp.post("/classes/<class_id>/schedules/<schedule_id>/cancel")
@permission_required("schedule.manage")
def cancel_schedule_item_endpoint(class_id: str, schedule_id: str):
    """
    API hủy một buổi học đơn lẻ (SCRUM-226 AC 2, AC 3, AC 4).
    - Bắt buộc nhập lý do hủy (cancellation_reason) (AC 2).
    - Chặn hủy nếu buổi học đã điểm danh (AC 4).
    - Gửi thông báo hủy tới học viên và giảng viên của lớp (AC 3).
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = schedule_service.cancel_single_schedule_service(class_id, schedule_id, payload)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_CANCELLED",
            "message": "Hủy buổi học thành công.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi hủy buổi học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi hủy buổi học.",
        }), 500


@schedule_bp.get("/v1/classes/<class_id>/schedules/<schedule_id>/notifications")
@schedule_bp.get("/classes/<class_id>/schedules/<schedule_id>/notifications")
@permission_required("schedule.manage")
def get_schedule_notifications_endpoint(class_id: str, schedule_id: str):
    """
    API lấy danh sách thông báo đã phát cho một buổi học (SCRUM-226 AC 3).
    """
    try:
        data = schedule_service.list_schedule_notifications_service(class_id, schedule_id)
        return jsonify({
            "status": "success",
            "code": "NOTIFICATIONS_FETCHED",
            "message": "Lấy danh sách thông báo thành công.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi lấy thông báo buổi học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lấy thông báo.",
        }), 500


@schedule_bp.get("/v1/schedules/notifications/my")
@schedule_bp.get("/schedules/notifications/my")
@permission_required("schedule.personal_view")
def get_my_schedule_notifications_endpoint():
    """
    API lấy danh sách thông báo thay đổi thời khóa biểu của chính người dùng đăng nhập (SCRUM-226 AC 3).
    """
    user_id = getattr(g, "user_id", None)
    try:
        notifications = schedule_service.list_my_notifications_service(user_id)
        return jsonify({
            "status": "success",
            "code": "NOTIFICATIONS_RETRIEVED",
            "message": "Lấy danh sách thông báo thành công.",
            "data": notifications,
        }), 200
    except MySQLError as err:
        logger.error("Lỗi DB khi lấy thông báo cá nhân: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải danh sách thông báo.",
        }), 500


@schedule_bp.get("/v1/schedules/calendar")
@schedule_bp.get("/schedules/calendar")
@permission_required("schedule.view")
def get_calendar_schedules_endpoint():
    """
    API xem thời khóa biểu dạng lịch theo tuần và theo tháng kèm bộ lọc (SCRUM-227 AC 1, 2, 4).
    Kiểm soát phạm vi dữ liệu:
    - Quản trị viên / Quản lý đào tạo: Được xem lịch toàn trường hoặc lọc theo giảng viên/phòng/lớp bất kỳ.
    - Giảng viên (trainer): Bị giới hạn nghiêm ngặt chỉ xem các buổi học thuộc phân công của chính mình (giảng viên chính, trợ giảng, dạy thay).
    """
    user_id = getattr(g, "user_id", None)
    from app.services import authorization_service
    roles = authorization_service.get_user_role_codes(user_id) if user_id else []
    is_trainer_only = "trainer" in roles and not any(r in roles for r in ["admin", "training_manager"])

    requested_instructor = request.args.get("instructor_id")
    # Nếu là giảng viên thuần túy, bỏ qua requested_instructor để trainer_scope_user_id
    # bao trùm cả giảng viên chính, trợ giảng và dạy thay
    if is_trainer_only:
        instructor_scope_id = None
        trainer_scope_id = user_id
    else:
        instructor_scope_id = requested_instructor
        trainer_scope_id = None

    params = {
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "class_id": request.args.get("class_id"),
        "instructor_id": instructor_scope_id,
        "trainer_scope_user_id": trainer_scope_id,
        "room_id": request.args.get("room_id"),
        "view_mode": request.args.get("view_mode", "week"),
    }
    try:
        data = schedule_service.get_calendar_schedules_service(params)
        return jsonify({
            "status": "success",
            "code": "CALENDAR_SCHEDULES_RETRIEVED",
            "message": "Lấy lịch thời khóa biểu thành công.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi lấy lịch thời khóa biểu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lấy lịch học.",
        }), 500


@schedule_bp.get("/v1/schedules/my-schedule")
@schedule_bp.get("/schedules/my-schedule")
@permission_required("schedule.personal_view")
def get_my_schedule_alias_endpoint():
    """
    API xem thời khóa biểu cá nhân của học viên hoặc giảng viên đăng nhập (SCRUM-228).
    - Bảo mật: Xác thực danh tính từ JWT/phiên đăng nhập (g.user_id), không tin cậy query/body client gửi lên.
    - Phân quyền: Yêu cầu quyền schedule.personal_view và vai trò học viên hoặc giảng viên.
    - Hỗ trợ đa vai trò (trainer + trainee): chấp nhận query param ?context=teaching hoặc ?context=learning.
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


@schedule_bp.get("/v1/schedules/<schedule_id>")
@schedule_bp.get("/schedules/<schedule_id>")
@permission_required("schedule.view")
def get_schedule_detail_endpoint(schedule_id: str):
    """
    API lấy chi tiết một buổi học theo ID khi bấm vào buổi trên lịch (SCRUM-227 AC 3).
    """
    try:
        data = schedule_service.get_schedule_detail_service(schedule_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_DETAIL_RETRIEVED",
            "message": "Lấy chi tiết buổi học thành công.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi lấy chi tiết buổi học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lấy chi tiết buổi học.",
        }), 500


