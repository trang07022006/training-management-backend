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


@program_subject_bp.post("/v1/training-programs/<program_id>/subjects")
@program_subject_bp.post("/training-programs/<program_id>/subjects")
@permission_required("course.manage")
def add_subject_to_program(program_id: str):
    """
    API gắn môn học vào chương trình đào tạo (SCRUM-124 - Activity A3).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Body JSON: subject_id (bắt buộc), semester (tùy chọn), is_mandatory (tùy chọn), order_index (tùy chọn)
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "error": {
                "code": "INVALID_PARAMS",
                "message": "Dữ liệu JSON không hợp lệ hoặc bị thiếu",
            }
        }), 400

    try:
        result = program_subject_service.add_subject_to_program_service(program_id, body)
        return jsonify(result), 201

    except ProgramSubjectServiceError as exc:
        return jsonify({
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when adding subject to program: %s", exc)
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi gắn môn học vào chương trình",
            }
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when adding subject to program: %s", exc)
        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Lỗi hệ thống máy chủ nội bộ",
            }
        }), 500


@program_subject_bp.patch("/v1/training-programs/<program_id>/subjects/<program_subject_id>")
@program_subject_bp.patch("/training-programs/<program_id>/subjects/<program_subject_id>")
@permission_required("course.manage")
def update_program_subject(program_id: str, program_subject_id: str):
    """
    API cập nhật metadata của môn học trong chương trình đào tạo (SCRUM-124 - Activity A3).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Body JSON: semester, is_mandatory, order_index
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "error": {
                "code": "INVALID_PARAMS",
                "message": "Dữ liệu JSON không hợp lệ hoặc bị thiếu",
            }
        }), 400

    try:
        result = program_subject_service.update_program_subject_service(program_id, program_subject_id, body)
        return jsonify(result), 200

    except ProgramSubjectServiceError as exc:
        return jsonify({
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when updating program subject: %s", exc)
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi cập nhật môn học trong chương trình",
            }
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when updating program subject: %s", exc)
        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Lỗi hệ thống máy chủ nội bộ",
            }
        }), 500


@program_subject_bp.patch("/v1/training-programs/<program_id>/subjects/reorder")
@program_subject_bp.patch("/training-programs/<program_id>/subjects/reorder")
@permission_required("course.manage")
def reorder_program_subjects(program_id: str):
    """
    API sắp xếp lại thứ tự học các môn trong chương trình đào tạo (SCRUM-124 - Activity A4).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Body JSON: { "semester": ..., "ordered_ids": [...] } hoặc { "semester": ..., "items": [...] }
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "error": {
                "code": "INVALID_PARAMS",
                "message": "Dữ liệu JSON không hợp lệ hoặc bị thiếu",
            }
        }), 400

    try:
        result = program_subject_service.reorder_program_subjects_service(program_id, body)
        return jsonify(result), 200

    except ProgramSubjectServiceError as exc:
        return jsonify({
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when reordering program subjects: %s", exc)
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi sắp xếp lại môn học trong chương trình",
            }
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when reordering program subjects: %s", exc)
        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Lỗi hệ thống máy chủ nội bộ",
            }
        }), 500


@program_subject_bp.delete("/v1/training-programs/<program_id>/subjects/<program_subject_id>")
@program_subject_bp.delete("/training-programs/<program_id>/subjects/<program_subject_id>")
@permission_required("course.manage")
def remove_program_subject(program_id: str, program_subject_id: str):
    """
    API gỡ môn học khỏi khung chương trình đào tạo an toàn (SCRUM-124 - Activity A4).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Không xóa master training_programs hay subjects
    - Chặn nếu môn đang làm prerequisite cho môn khác (409 PROGRAM_SUBJECT_IN_USE)
    """
    try:
        result = program_subject_service.remove_program_subject_service(program_id, program_subject_id)
        return jsonify(result), 200

    except ProgramSubjectServiceError as exc:
        return jsonify({
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when removing program subject: %s", exc)
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi gỡ môn học khỏi chương trình",
            }
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when removing program subject: %s", exc)
        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Lỗi hệ thống máy chủ nội bộ",
            }
        }), 500


