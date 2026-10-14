"""
Các endpoint API Quản lý ngày nghỉ lễ (Holiday Routes) - SCRUM-224.
- Khai báo ngày nghỉ lễ mới
- Lấy danh sách ngày nghỉ lễ
- Xóa ngày nghỉ lễ
"""

import logging
from flask import Blueprint, jsonify, request
from app.services.holiday_service import (
    HolidayServiceError,
    create_holiday_service,
    delete_holiday_service,
    list_holidays_service,
)
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

holiday_bp = Blueprint("holidays", __name__, url_prefix="/api")


@holiday_bp.get("/v1/holidays")
@permission_required("course.view")
def list_holidays_endpoint():
    """Lấy danh sách các ngày nghỉ lễ đã khai báo (SCRUM-224)."""
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    try:
        items = list_holidays_service(from_date, to_date)
        return jsonify({
            "status": "success",
            "code": "HOLIDAYS_FETCHED",
            "message": "Lấy danh sách ngày nghỉ lễ thành công.",
            "data": {
                "items": items,
                "total": len(items),
            },
        }), 200
    except HolidayServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except Exception as exc:
        logger.exception("Lỗi hệ thống khi tải danh sách ngày nghỉ lễ: %s", exc)
        return jsonify({
            "status": "error",
            "code": "SERVER_ERROR",
            "message": "Lỗi máy chủ khi lấy danh sách ngày nghỉ lễ.",
        }), 500


@holiday_bp.post("/v1/holidays")
@permission_required("course.manage")
def create_holiday_endpoint():
    """Khai báo ngày nghỉ lễ mới (SCRUM-224)."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    try:
        created = create_holiday_service(payload)
        return jsonify({
            "status": "success",
            "code": "HOLIDAY_CREATED",
            "message": "Khai báo ngày nghỉ lễ thành công.",
            "data": created,
        }), 201
    except HolidayServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except Exception as exc:
        logger.exception("Lỗi hệ thống khi khai báo ngày nghỉ lễ: %s", exc)
        return jsonify({
            "status": "error",
            "code": "SERVER_ERROR",
            "message": "Lỗi máy chủ khi khai báo ngày nghỉ lễ.",
        }), 500


@holiday_bp.delete("/v1/holidays/<holiday_id>")
@permission_required("course.manage")
def delete_holiday_endpoint(holiday_id: str):
    """Xóa ngày nghỉ lễ (SCRUM-224)."""
    try:
        delete_holiday_service(holiday_id)
        return jsonify({
            "status": "success",
            "code": "HOLIDAY_DELETED",
            "message": "Xóa ngày nghỉ lễ thành công.",
        }), 200
    except HolidayServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except Exception as exc:
        logger.exception("Lỗi hệ thống khi xóa ngày nghỉ lễ: %s", exc)
        return jsonify({
            "status": "error",
            "code": "SERVER_ERROR",
            "message": "Lỗi máy chủ khi xóa ngày nghỉ lễ.",
        }), 500
