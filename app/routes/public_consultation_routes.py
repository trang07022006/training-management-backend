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
from app.services.lead_service import LeadServiceError

logger = logging.getLogger(__name__)

public_consultation_bp = Blueprint("public_consultation", __name__, url_prefix="/api")


@public_consultation_bp.post("/v1/public/consultations")
@public_consultation_bp.post("/public/consultations")
def submit_public_consultation():
    """
    API gửi yêu cầu tư vấn công khai (SCRUM-125 - Activity A2).
    - Dành cho khách vãng lai, thí sinh, phụ huynh (không cần đăng nhập).
    - Yêu cầu tối thiểu: Họ tên và Số điện thoại.
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

    try:
        result = lead_service.create_public_consultation_service(body)
        return jsonify(result), 201

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
