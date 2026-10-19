"""
Routes API Điểm danh học viên theo buổi học (Attendance Routes) - SCRUM-254.
- GET /api/v1/schedules/<schedule_id>/attendance: Mở sổ điểm danh buổi học
"""

import logging
from flask import Blueprint, g, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import attendance_service, authorization_service
from app.services.attendance_service import (
    AttendanceServiceError,
    ForbiddenAttendanceAccessError,
    SessionNotFoundError,
)
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

attendance_bp = Blueprint("attendance", __name__, url_prefix="/api")


@attendance_bp.get("/v1/schedules/<schedule_id>/attendance")
@attendance_bp.get("/schedules/<schedule_id>/attendance")
@permission_required(["attendance.view", "attendance.take"], message="Bạn không có quyền truy cập chức năng điểm danh.")
def get_session_attendance_endpoint(schedule_id: str):
    """
    API mở sổ điểm danh của một buổi học (Lát 1 — SCRUM-254).
    - Hiển thị thông tin buổi học: lớp, môn, ngày, giờ, phòng, giảng viên.
    - Danh sách học viên đủ điều kiện theo ngày học.
    - Kết quả điểm danh đã lưu hoặc trạng thái chưa điểm danh (null).
    - Kiểm soát quyền: Giảng viên phụ trách hoặc Quản lý đào tạo.
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Không tìm thấy thông tin người dùng trong phiên làm việc.",
        }), 401

    try:
        roles = authorization_service.get_user_role_codes(user_id)
        page = request.args.get("page", default=1, type=int)
        limit = request.args.get("limit", default=10, type=int)
        search_query = request.args.get("q", default=None, type=str)
        data = attendance_service.get_session_attendance_sheet(
            schedule_id=schedule_id,
            current_user_id=user_id,
            current_user_roles=roles,
            page=page,
            limit=limit,
            search_query=search_query,
        )
        return jsonify({
            "status": "success",
            "code": "ATTENDANCE_SHEET_RETRIEVED",
            "message": "Tải sổ điểm danh thành công.",
            "data": data,
        }), 200
    except AttendanceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi mở sổ điểm danh schedule_id=%s: %s", schedule_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn thông tin điểm danh.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không xác định khi mở sổ điểm danh: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi mở sổ điểm danh.",
        }), 500


@attendance_bp.post("/v1/schedules/<schedule_id>/attendance")
@attendance_bp.post("/schedules/<schedule_id>/attendance")
@permission_required(["attendance.take", "attendance.manage"], message="Bạn không có quyền thực hiện hoặc lưu điểm danh.")
def save_session_attendance_endpoint(schedule_id: str):
    """
    API lưu kết quả điểm danh cho một buổi học (Lát 2 — SCRUM-254).
    - Lưu nguyên tử trong Transaction.
    - Cập nhật cờ attendance_checked trên class_schedules.
    - Ghi lịch sử kiểm toán vào attendance_audit_logs.
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Không tìm thấy thông tin người dùng trong phiên làm việc.",
        }), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu gửi lên không đúng định dạng JSON.",
        }), 400

    try:
        roles = authorization_service.get_user_role_codes(user_id)
        result = attendance_service.save_session_attendance_service(
            schedule_id=schedule_id,
            payload=payload,
            current_user_id=user_id,
            current_user_roles=roles,
        )
        sheet_data = dict(result["sheet"])
        sheet_data["updated_count"] = result["updated_count"]
        return jsonify({
            "status": "success",
            "code": "ATTENDANCE_SAVED",
            "message": f"Lưu kết quả điểm danh thành công cho {result['updated_count']} học viên.",
            "data": sheet_data,
        }), 200
    except AttendanceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lưu điểm danh schedule_id=%s: %s", schedule_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu kết quả điểm danh.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không xác định khi lưu điểm danh: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi lưu kết quả điểm danh.",
        }), 500


@attendance_bp.get("/v1/schedules/<schedule_id>/attendance/history")
@attendance_bp.get("/schedules/<schedule_id>/attendance/history")
@permission_required(["attendance.view", "attendance.take", "attendance.manage"], message="Bạn không có quyền xem lịch sử điểm danh.")
def get_session_attendance_history_endpoint(schedule_id: str):
    """
    API truy vấn lịch sử chỉnh sửa điểm danh của buổi học (Lát 3 — SCRUM-254).
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Không tìm thấy thông tin người dùng trong phiên làm việc.",
        }), 401

    try:
        roles = authorization_service.get_user_role_codes(user_id)
        history_list = attendance_service.get_session_attendance_history_service(
            schedule_id=schedule_id,
            current_user_id=user_id,
            current_user_roles=roles,
        )
        return jsonify({
            "status": "success",
            "code": "ATTENDANCE_HISTORY_RETRIEVED",
            "message": "Lấy lịch sử chỉnh sửa điểm danh thành công.",
            "data": history_list,
        }), 200
    except AttendanceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc lịch sử điểm danh schedule_id=%s: %s", schedule_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải lịch sử điểm danh.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không xác định khi tải lịch sử điểm danh: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi tải lịch sử điểm danh.",
        }), 500
