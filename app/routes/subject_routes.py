"""
Các endpoint quản lý môn học / học phần (SCRUM-123).
Bảo vệ bằng RBAC decorator @permission_required:
- 'course.view' cho các API đọc (Activity A2)
- 'course.manage' cho các API tạo mới, cập nhật, xóa (các Activity tiếp theo)

Endpoints:
- GET /api/v1/subjects              : Lấy danh sách môn học (hỗ trợ phân trang, lọc, tìm kiếm)
- GET /api/v1/subjects/<subject_id> : Lấy chi tiết một môn học theo ID
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import subject_service
from app.services.subject_service import SubjectServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

subject_bp = Blueprint("subjects", __name__, url_prefix="/api")


@subject_bp.get("/v1/subjects")
@subject_bp.get("/subjects")
@permission_required("course.view")
def list_subjects():
    """
    API xem danh sách môn học (SCRUM-123 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Hỗ trợ tham số phân trang: page, page_size
    - Hỗ trợ bộ lọc: status (draft, active, archived)
    - Hỗ trợ tìm kiếm: search (mã hoặc tên môn học)
    """
    page_raw = request.args.get("page", default=1)
    page_size_raw = request.args.get("page_size", default=20)
    status = request.args.get("status", default=None)
    search = request.args.get("search", default=None)

    try:
        result = subject_service.get_subjects_service(
            page_raw=page_raw,
            page_size_raw=page_size_raw,
            status=status,
            search=search,
        )
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except SubjectServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách môn học: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất môn học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc danh sách môn học: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@subject_bp.get("/v1/subjects/<subject_id>")
@subject_bp.get("/subjects/<subject_id>")
@permission_required("course.view")
def get_subject_detail(subject_id: str):
    """
    API xem chi tiết một môn học theo ID (SCRUM-123 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Trả về 400 nếu ID sai định dạng UUID
    - Trả về 404 nếu không tìm thấy môn học
    """
    try:
        subject_data = subject_service.get_subject_detail_service(subject_id)
        return jsonify({
            "status": "success",
            "data": subject_data,
        }), 200
    except SubjectServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc chi tiết môn học: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất môn học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc chi tiết môn học: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
