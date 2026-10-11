"""
Các endpoint công khai phục vụ đăng ký tư vấn tuyển sinh (SCRUM-125).
HOÀN TOÀN KHÔNG YÊU CẦU ĐĂNG NHẬP / BEARER TOKEN.

Endpoints:
- POST /api/v1/public/consultations
- POST /api/public/consultations (alias)
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import lead_service
from app.services.lead_service import LeadServiceError, LeadRateLimitError

logger = logging.getLogger(__name__)

public_consultation_bp = Blueprint("public_consultation", __name__, url_prefix="/api")


def _get_client_ip() -> str:
    """Lấy địa chỉ IP của client từ request (hỗ trợ reverse proxy headers X-Forwarded-For)."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if parts:
            return parts[0]
    real_ip = request.headers.get("X-Real-IP")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return request.remote_addr or "127.0.0.1"


@public_consultation_bp.post("/v1/public/consultations")
@public_consultation_bp.post("/public/consultations")
def submit_public_consultation():
    """
    API gửi yêu cầu tư vấn công khai (SCRUM-125 - Activity A2).
    - Dành cho khách vãng lai, thí sinh, phụ huynh (không cần đăng nhập).
    - Yêu cầu tối thiểu: Họ tên và Số điện thoại.
    - Chống spam / rate limit theo Phone, Email, IP (429 Too Many Requests).
    - Lưu vào cơ sở dữ liệu với trạng thái 'new' và nguồn 'public_form'.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            "error": {
                "code": "INVALID_JSON",
                "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            },
        }), 400

    client_ip = _get_client_ip()

    try:
        result = lead_service.create_public_consultation_service(body, client_ip=client_ip)
        return jsonify(result), 201

    except LeadRateLimitError as err:
        response = jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "error": {
                "code": err.code,
                "message": err.message,
            },
            "retry_after_seconds": err.retry_after_seconds,
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(err.retry_after_seconds)
        return response

    except LeadServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "error": {
                "code": err.code,
                "message": err.message,
            },
        }), err.status_code

    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lưu yêu cầu tư vấn công khai: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Đã xảy ra lỗi cơ sở dữ liệu. Vui lòng thử lại sau.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Đã xảy ra lỗi cơ sở dữ liệu. Vui lòng thử lại sau.",
            },
        }), 500

    except Exception as err:
        logger.exception("Lỗi không mong muốn khi xử lý yêu cầu tư vấn công khai: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@public_consultation_bp.get("/v1/public/training-programs")
@public_consultation_bp.get("/public/training-programs")
def get_public_training_programs():
    """
    API lấy danh sách chương trình đào tạo mở công khai cho form tư vấn (SCRUM-125 - Activity A3).
    - Hoàn toàn KHÔNG yêu cầu đăng nhập / token.
    - Chỉ trả về các chương trình đang 'active'.
    - Không để lộ thông tin nhạy cảm / quản trị nội bộ.
    """
    try:
        programs = lead_service.get_public_training_programs_service()
        return jsonify({
            "status": "success",
            "data": programs,
        }), 200

    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi tải danh sách chương trình công khai: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Đã xảy ra lỗi cơ sở dữ liệu. Vui lòng thử lại sau.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Đã xảy ra lỗi cơ sở dữ liệu. Vui lòng thử lại sau.",
            },
        }), 500

    except Exception as err:
        logger.exception("Lỗi không mong muốn khi tải danh sách chương trình công khai: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500
