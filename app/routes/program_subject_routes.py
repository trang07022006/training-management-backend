"""
Các endpoint quản lý cấu trúc chương trình đào tạo và môn học liên kết (SCRUM-124).
Bảo vệ bằng RBAC decorator @permission_required:
- 'course.view' cho các API đọc (Activity A2)
- 'course.manage' cho các API ghi (thêm, sửa, xóa, sắp xếp, môn tiên quyết)

Endpoints Activity A2:
- GET /api/v1/training-programs/<program_id>/subjects
- GET /api/training-programs/<program_id>/subjects (alias)
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import program_subject_service
from app.services.program_subject_service import ProgramSubjectServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

program_subject_bp = Blueprint("program_subjects", __name__, url_prefix="/api")


@program_subject_bp.get("/v1/training-programs/<program_id>/subjects")
@program_subject_bp.get("/training-programs/<program_id>/subjects")
@permission_required("course.view")
def get_program_structure(program_id: str):
    """
    API xem danh sách và cấu trúc môn học của một chương trình đào tạo (SCRUM-124 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Hỗ trợ tham số lọc tùy chọn: semester, is_mandatory
    """
    semester = request.args.get("semester", default=None)
    is_mandatory = request.args.get("is_mandatory", default=None)

    try:
        data = program_subject_service.get_program_structure_service(
            program_id=program_id,
            semester_raw=semester,
            is_mandatory_raw=is_mandatory,
        )
        return jsonify(data), 200

    except ProgramSubjectServiceError as exc:
        return jsonify({
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when reading program structure: %s", exc)
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi truy vấn cấu trúc chương trình",
            }
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when reading program structure: %s", exc)
        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Lỗi hệ thống máy chủ nội bộ",
            }
        }), 500
