"""
Blueprint định nghĩa các API Lịch sử điểm danh cá nhân của Học viên (SCRUM-258).
- GET /api/v1/me/attendance-history
- GET /api/v1/students/my-attendance-history
"""

import logging
from flask import Blueprint, g, jsonify, request

from app.services import attendance_history_service
from app.services.attendance_history_service import AttendanceHistoryError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

attendance_history_bp = Blueprint("attendance_history", __name__, url_prefix="/api")


@attendance_history_bp.get("/v1/me/attendance-history")
@attendance_history_bp.get("/me/attendance-history")
@attendance_history_bp.get("/v1/students/my-attendance-history")
@attendance_history_bp.get("/students/my-attendance-history")
@permission_required("schedule.personal_view")
def get_my_attendance_history_endpoint():
    """
    API xem lịch sử điểm danh cá nhân của học viên đăng nhập (SCRUM-258).
    - Bảo mật: Xác thực danh tính từ JWT/phiên đăng nhập (g.user_id), không tin cậy student_id client gửi lên.
    - Phân quyền: Yêu cầu quyền schedule.personal_view (thuộc vai trò trainee chuẩn).
    - Thống kê toàn lớp: Tính P, L, E, U, D và tỷ lệ chuyên cần (AC1).
    - Cảnh báo ngưỡng vắng: Tính số buổi còn lại R và hiển thị cảnh báo theo ngưỡng chương trình (AC2).
    """
    user_id = getattr(g, "user_id", None)
    if not user_id:
        return jsonify({
            "status": "error",
            "code": "UNAUTHORIZED",
            "message": "Yêu cầu đăng nhập để truy cập tài nguyên này.",
        }), 401

    class_id = request.args.get("class_id")
    status_filter = request.args.get("status")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    page = request.args.get("page", 1)
    page_size = request.args.get("page_size", 20)
    sort_order = request.args.get("sort_order", "desc")

    try:
        data = attendance_history_service.get_my_attendance_history_service(
            user_id=user_id,
            class_id=class_id,
            status_filter=status_filter,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
            sort_by="learning_date",
            sort_order=sort_order,
        )
        return jsonify({
            "status": "success",
            "code": "ATTENDANCE_HISTORY_RETRIEVED",
            "message": "Lấy lịch sử điểm danh cá nhân thành công.",
            "data": data,
        }), 200
    except AttendanceHistoryError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except Exception as err:
        logger.exception("Lỗi khi lấy lịch sử điểm danh của user %s: %s", user_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
