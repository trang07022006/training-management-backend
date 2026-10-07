"""
Các endpoint quản lý chương trình đào tạo (SCRUM-122 - Activity A2).
Bảo vệ bằng RBAC decorator @permission_required('course.view').

Endpoints:
- GET /api/v1/training-programs       : Lấy danh sách chương trình đào tạo (hỗ trợ phân trang, lọc, tìm kiếm)
- GET /api/v1/training-programs/<id>  : Lấy chi tiết một chương trình đào tạo
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import training_program_service
from app.services.training_program_service import TrainingProgramServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

training_program_bp = Blueprint("training_programs", __name__, url_prefix="/api")


@training_program_bp.get("/v1/training-programs")
@training_program_bp.get("/training-programs")
@permission_required("course.view")
def list_training_programs():
    """
    API xem danh sách chương trình đào tạo (SCRUM-122 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Hỗ trợ tham số phân trang: page, page_size
    - Hỗ trợ bộ lọc: status (draft, active, archived)
    - Hỗ trợ tìm kiếm: search (mã hoặc tên chương trình)
    """
    page_raw = request.args.get("page", default=1)
    page_size_raw = request.args.get("page_size", default=20)
    status = request.args.get("status", default=None)
    search = request.args.get("search", default=None)

    try:
        result = training_program_service.get_training_programs_service(
            page_raw=page_raw,
            page_size_raw=page_size_raw,
            status=status,
            search=search,
        )
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách chương trình đào tạo: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất chương trình đào tạo.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc danh sách chương trình đào tạo: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@training_program_bp.get("/v1/training-programs/<program_id>")
@training_program_bp.get("/training-programs/<program_id>")
@permission_required("course.view")
def get_training_program_detail(program_id: str):
    """
    API xem chi tiết một chương trình đào tạo theo ID (SCRUM-122 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Trả về 404 nếu không tìm thấy chương trình
    """
    try:
        program_data = training_program_service.get_training_program_detail_service(program_id)
        return jsonify({
            "status": "success",
            "data": program_data,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc chi tiết chương trình đào tạo: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất chương trình đào tạo.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi đọc chi tiết chương trình đào tạo: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
