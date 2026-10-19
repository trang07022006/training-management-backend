"""
Routes API Đơn xin phép vắng (Absence Request Routes) - SCRUM-255.
"""

import logging
from flask import Blueprint, g, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import absence_request_service, authorization_service
from app.services.absence_request_service import (
    AbsenceServiceError,
    ForbiddenAbsenceAccessError,
    NotAStudentError,
    RequestNotFoundError,
)
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

absence_request_bp = Blueprint("absence_request", __name__, url_prefix="/api")


@absence_request_bp.get("/v1/absence-requests/eligible-sessions")
@absence_request_bp.get("/absence-requests/eligible-sessions")
@permission_required("absence.request", message="Chỉ học viên mới có quyền truy cập danh sách buổi học xin phép vắng.")
def get_eligible_sessions_endpoint():
    """
    API lấy danh sách các buổi học hợp lệ để học viên gửi đơn xin phép vắng (SCRUM-255 Lát 1).
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Không tìm thấy thông tin người dùng trong phiên làm việc.",
        }), 401

    try:
        sessions = absence_request_service.get_eligible_sessions_for_current_student(user_id)
        return jsonify({
            "status": "success",
            "code": "ELIGIBLE_SESSIONS_RETRIEVED",
            "message": "Lấy danh sách buổi học hợp lệ thành công.",
            "data": sessions,
        }), 200
    except AbsenceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi truy vấn buổi học hợp lệ user_id=%s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn danh sách buổi học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi hệ thống khi lấy danh sách buổi học hợp lệ: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi lấy danh sách buổi học.",
        }), 500


@absence_request_bp.post("/v1/absence-requests")
@absence_request_bp.post("/absence-requests")
@permission_required("absence.request", message="Chỉ học viên mới có quyền gửi đơn xin phép vắng.")
def submit_absence_request_endpoint():
    """
    API nộp đơn xin phép vắng mới (SCRUM-255 Lát 1).
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
            "code": "INVALID_PAYLOAD",
            "message": "Dữ liệu yêu cầu không đúng định dạng JSON.",
        }), 400

    try:
        created = absence_request_service.submit_absence_request_service(
            user_id=user_id,
            payload=payload,
        )
        return jsonify({
            "status": "success",
            "code": "ABSENCE_REQUEST_SUBMITTED",
            "message": "Gửi đơn xin phép vắng thành công. Đơn đang chờ giảng viên xem xét.",
            "data": created,
        }), 201
    except AbsenceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi nộp đơn xin phép vắng user_id=%s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu đơn xin phép vắng.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi hệ thống khi nộp đơn xin phép vắng: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi gửi đơn xin phép vắng.",
        }), 500


@absence_request_bp.get("/v1/absence-requests/my")
@absence_request_bp.get("/absence-requests/my")
@permission_required("absence.request", message="Chỉ học viên mới có quyền xem danh sách đơn của mình.")
def list_my_absence_requests_endpoint():
    """
    API lấy danh sách đơn xin phép vắng của học viên đang đăng nhập (SCRUM-255 Lát 1).
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Không tìm thấy thông tin người dùng trong phiên làm việc.",
        }), 401

    try:
        status_filter = request.args.get("status", default=None, type=str)
        search_query = request.args.get("q", default=None, type=str)
        page = request.args.get("page", default=1, type=int)
        limit = request.args.get("limit", default=10, type=int)

        data = absence_request_service.list_my_absence_requests_service(
            user_id=user_id,
            status_filter=status_filter,
            search_query=search_query,
            page=page,
            limit=limit,
        )
        return jsonify({
            "status": "success",
            "code": "MY_ABSENCE_REQUESTS_RETRIEVED",
            "message": "Tải danh sách đơn xin phép vắng thành công.",
            "data": data,
        }), 200
    except AbsenceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy danh sách đơn user_id=%s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn danh sách đơn xin phép vắng.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi hệ thống khi lấy danh sách đơn cá nhân: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi tải danh sách đơn.",
        }), 500


@absence_request_bp.get("/v1/absence-requests/<request_id>")
@absence_request_bp.get("/absence-requests/<request_id>")
@permission_required(["absence.request", "absence.view", "absence.review"], message="Bạn không có quyền xem đơn này.")
def get_absence_request_endpoint(request_id: str):
    """
    API xem chi tiết đơn xin phép vắng (SCRUM-255).
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
        data = absence_request_service.get_absence_request_detail_service(
            request_id=request_id,
            current_user_id=user_id,
            current_user_roles=roles,
        )
        return jsonify({
            "status": "success",
            "code": "ABSENCE_REQUEST_RETRIEVED",
            "message": "Tải thông tin chi tiết đơn thành công.",
            "data": data,
        }), 200
    except AbsenceServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": err.data,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi xem đơn request_id=%s: %s", request_id, err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn thông tin đơn.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi hệ thống khi xem chi tiết đơn: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi tải chi tiết đơn.",
        }), 500
