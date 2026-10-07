"""
Các endpoint quản trị Lead nội bộ (SCRUM-126).
Bảo vệ bằng RBAC decorator @permission_required:
- 'course.manage' cho phép Admin và Quản lý đào tạo/tuyển sinh xem và quản trị Lead.
Tuyệt đối KHÔNG mở công khai (không cho khách vãng lai hoặc học viên xem PII).

Endpoints:
- GET /api/v1/leads           : Xem danh sách Lead (có phân trang cơ bản)
- GET /api/v1/leads/<lead_id> : Xem chi tiết một Lead theo ID
- PATCH /api/v1/leads/<lead_id>: Cập nhật trạng thái Lead (Activity A3)
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import lead_service
from app.services.lead_service import LeadServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

lead_bp = Blueprint("leads", __name__, url_prefix="/api")


@lead_bp.get("/v1/leads")
@lead_bp.get("/leads")
@permission_required("course.manage")
def list_leads():
    """
    API xem danh sách Lead có phân trang (SCRUM-126 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Phân trang: page, page_size.
    - Sắp xếp mặc định: created_at DESC.
    """
    page_raw = request.args.get("page", default=1)
    page_size_raw = request.args.get("page_size", default=20)

    try:
        result = lead_service.get_leads_service(
            page_raw=page_raw,
            page_size_raw=page_size_raw,
        )
        return jsonify({
            "status": "success",
            "data": result,
        }), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi tải danh sách Lead: %s", err)
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
        logger.exception("Lỗi không mong muốn khi tải danh sách Lead: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.get("/v1/leads/<lead_id>")
@lead_bp.get("/leads/<lead_id>")
@permission_required("course.manage")
def get_lead_detail(lead_id: str):
    """
    API xem chi tiết thông tin một Lead (SCRUM-126 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Kiểm tra UUID hợp lệ (400 nếu sai định dạng).
    - Trả về 404 LEAD_NOT_FOUND nếu không tìm thấy.
    """
    try:
        lead_data = lead_service.get_lead_by_id_service(lead_id)
        return jsonify({
            "status": "success",
            "data": lead_data,
        }), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi tải chi tiết Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi tải chi tiết Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500
