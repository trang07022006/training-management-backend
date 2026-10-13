"""
Routes API quản lý Thời khóa biểu lớp học (Schedule Routes) - SCRUM-224.
- POST /api/v1/classes/<class_id>/schedules/preview: Xem trước lịch sinh tự động
- POST /api/v1/classes/<class_id>/schedules/generate: Xác nhận lưu lịch học chính thức
- GET /api/v1/classes/<class_id>/schedules: Lấy danh sách thời khóa biểu lớp học
- DELETE /api/v1/classes/<class_id>/schedules: Xoá thời khóa biểu của lớp học
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import schedule_service
from app.services.schedule_service import ScheduleServiceError
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
