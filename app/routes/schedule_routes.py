"""
Routes API quản lý Thời khóa biểu lớp học (Schedule Routes) - SCRUM-224.
- POST /api/v1/classes/<class_id>/schedules/preview: Xem trước lịch sinh tự động
- POST /api/v1/classes/<class_id>/schedules/generate: Xác nhận lưu lịch học chính thức
- GET /api/v1/classes/<class_id>/schedules: Lấy danh sách thời khóa biểu lớp học
- DELETE /api/v1/classes/<class_id>/schedules: Xoá thời khóa biểu của lớp học
"""

import logging
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
@permission_required("course.manage")
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
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi xem trước thời khóa biểu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xem trước lịch học.",
        }), 500


@schedule_bp.post("/v1/classes/<class_id>/schedules/generate")
@schedule_bp.post("/classes/<class_id>/schedules/generate")
@permission_required("course.manage")
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

    try:
        saved_data = schedule_service.generate_schedule_service(class_id, payload)
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
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi DB khi lưu thời khóa biểu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu lịch học.",
        }), 500


@schedule_bp.get("/v1/classes/<class_id>/schedules")
@schedule_bp.get("/classes/<class_id>/schedules")
@permission_required("course.view")
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
@permission_required("course.manage")
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
@permission_required("course.manage")
def update_schedule_item_endpoint(class_id: str, schedule_id: str):
    """
    API sửa hoặc dời một buổi học đơn lẻ (SCRUM-226 AC 1, AC 3, AC 4).
    - Đổi ngày, giờ, ca, phòng, giảng viên dạy thay.
    - Chặn sửa buổi học đã điểm danh (AC 4).
    - Tái sử dụng kiểm tra xung đột SCRUM-225 (loại trừ chính buổi đang sửa).
    - Gửi thông báo thay đổi tới học viên và giảng viên của lớp (AC 3).
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = schedule_service.update_single_schedule_service(class_id, schedule_id, payload)
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
@permission_required("course.manage")
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
@permission_required("course.manage")
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


@schedule_bp.get("/v1/schedules/calendar")
@schedule_bp.get("/schedules/calendar")
@permission_required("course.view")
def get_calendar_schedules_endpoint():
    """
    API xem thời khóa biểu dạng lịch theo tuần và theo tháng kèm bộ lọc (SCRUM-227 AC 1, 2, 4).
    Query parameters:
    - date_from (YYYY-MM-DD): Ngày bắt đầu khoảng thời gian
    - date_to (YYYY-MM-DD): Ngày kết thúc khoảng thời gian
    - class_id: Lọc theo lớp học
    - instructor_id: Lọc theo giảng viên
    - room_id: Lọc theo phòng học
    - view_mode: Chế độ xem ('week' hoặc 'month')
    """
    params = {
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "class_id": request.args.get("class_id"),
        "instructor_id": request.args.get("instructor_id"),
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
@permission_required("course.view")
def get_my_schedule_alias_endpoint():
    """
    API xem thời khóa biểu cá nhân của học viên đăng nhập (SCRUM-228).
    """
    user_id = getattr(g, "user_id", None)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    ref_date = request.args.get("ref_date")
    ref_time = request.args.get("ref_time")

    try:
        data = schedule_service.get_my_personal_schedule_service(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            ref_date=ref_date,
            ref_time=ref_time,
        )
        return jsonify({
            "status": "success",
            "code": "MY_SCHEDULE_RETRIEVED",
            "data": data,
        }), 200
    except Exception as err:
        logger.exception("Lỗi khi lấy lịch học của học viên %s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@schedule_bp.get("/v1/schedules/<schedule_id>")
@schedule_bp.get("/schedules/<schedule_id>")
@permission_required("course.view")
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


