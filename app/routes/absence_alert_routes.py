"""
Routes quản lý cảnh báo học viên vắng vượt ngưỡng và thông báo (SCRUM-257).
Bảo vệ bằng RBAC decorator @permission_required:
- 'schedule.personal_view' hoặc authenticated user cho API xem thông báo cá nhân (AC3)
- 'attendance.view' / 'course.view' cho API xem cảnh báo lớp
"""

import logging
from flask import Blueprint, g, jsonify, request

from app.services import absence_alert_service
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

absence_alert_bp = Blueprint("absence_alerts", __name__, url_prefix="/api")


@absence_alert_bp.get("/v1/absence-alerts/notifications/my")
@absence_alert_bp.get("/absence-alerts/notifications/my")
@permission_required(["schedule.personal_view", "schedule.view", "course.view"])
def get_my_absence_alert_notifications_endpoint():
    """
    Lấy danh sách thông báo cảnh báo vắng vượt ngưỡng của chính người dùng đăng nhập (SCRUM-257 - AC3).
    Hỗ trợ query parameter: unread_only (true/false)
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Yêu cầu đăng nhập để truy cập tài nguyên này.",
        }), 401

    unread_only_param = request.args.get("unread_only", "false").lower() == "true"

    try:
        notifications = absence_alert_service.list_my_absence_alert_notifications_service(
            user_id=user_id, unread_only=unread_only_param
        )
        return jsonify({
            "status": "success",
            "code": "NOTIFICATIONS_RETRIEVED",
            "data": notifications,
        }), 200
    except Exception as err:
        logger.exception("Lỗi khi đọc thông báo cảnh báo vắng của user %s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@absence_alert_bp.post("/v1/absence-alerts/notifications/<notif_id>/read")
@absence_alert_bp.post("/absence-alerts/notifications/<notif_id>/read")
@permission_required(["schedule.personal_view", "schedule.view", "course.view"])
def mark_absence_alert_notification_read_endpoint(notif_id: str):
    """
    Đánh dấu thông báo cảnh báo vắng đã đọc (SCRUM-257 - AC3).
    Chỉ cho phép người nhận (recipient) đánh dấu thông báo của chính mình.
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Yêu cầu đăng nhập để truy cập tài nguyên này.",
        }), 401

    try:
        updated = absence_alert_service.mark_absence_alert_notification_read_service(
            notif_id=notif_id, user_id=user_id
        )
        if not updated:
            return jsonify({
                "status": "error",
                "code": "NOT_FOUND_OR_FORBIDDEN",
                "message": "Không tìm thấy thông báo hoặc bạn không có quyền cập nhật thông báo này.",
            }), 404

        return jsonify({
            "status": "success",
            "code": "NOTIFICATION_MARKED_READ",
            "message": "Đã đánh dấu thông báo là đã đọc.",
        }), 200
    except Exception as err:
        logger.exception("Lỗi khi đánh dấu đã đọc thông báo %s của user %s: %s", notif_id, user_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@absence_alert_bp.get("/v1/classes/<class_id>/absence-alerts")
@absence_alert_bp.get("/classes/<class_id>/absence-alerts")
@permission_required("attendance.view")
def get_class_absence_alerts_endpoint(class_id: str):
    """
    Lấy danh sách đánh giá cảnh báo vắng của toàn bộ học viên trong một lớp (SCRUM-257 - AC2, AC3).
    Yêu cầu quyền attendance.view hoặc giảng viên phụ trách lớp / quản lý đào tạo.
    """
    try:
        results = absence_alert_service.evaluate_class_absence_alerts(class_id=class_id, persist=True)
        return jsonify({
            "status": "success",
            "code": "ABSENCE_ALERTS_RETRIEVED",
            "data": results,
        }), 200
    except Exception as err:
        logger.exception("Lỗi khi lấy cảnh báo vắng của lớp %s: %s", class_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
