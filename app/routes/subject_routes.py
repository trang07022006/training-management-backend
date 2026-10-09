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


@subject_bp.post("/v1/subjects")
@subject_bp.post("/subjects")
@permission_required("course.manage")
def create_subject():
    """
    API tạo mới môn học / học phần (SCRUM-123 - Activity A3).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Request body: JSON chứa code, name, credits, description, total_sessions, status
    - Trả về 201 Created khi thành công kèm Location header
    - Trả về 400 nếu dữ liệu không hợp lệ
    - Trả về 409 nếu trùng mã môn học
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    try:
        created_subject = subject_service.create_subject_service(data)
        response = jsonify({
            "status": "success",
            "message": "Tạo môn học thành công.",
            "data": created_subject,
        })
        response.status_code = 201
        response.headers["Location"] = f"/api/v1/subjects/{created_subject['id']}"
        return response
    except SubjectServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi tạo môn học: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tạo môn học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi tạo môn học: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@subject_bp.put("/v1/subjects/<subject_id>")
@subject_bp.put("/subjects/<subject_id>")
@permission_required("course.manage")
def update_subject(subject_id: str):
    """
    API cập nhật toàn bộ thông tin môn học (SCRUM-123 - Activity A4 - PUT).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - code, name, credits bắt buộc
    - description, total_sessions, status đặt về mặc định nếu thiếu
    - Trả về 200 OK khi thành công
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    try:
        updated_subject = subject_service.update_subject_service(subject_id, data)
        return jsonify({
            "status": "success",
            "message": "Cập nhật môn học thành công.",
            "data": updated_subject,
        }), 200
    except SubjectServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật môn học (PUT): %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật môn học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi cập nhật môn học (PUT): %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@subject_bp.patch("/v1/subjects/<subject_id>")
@subject_bp.patch("/subjects/<subject_id>")
@permission_required("course.manage")
def patch_subject(subject_id: str):
    """
    API cập nhật từng phần thông tin môn học (SCRUM-123 - Activity A4 - PATCH).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Chỉ cập nhật các trường được gửi
    - Trả về 200 OK khi thành công
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    try:
        updated_subject = subject_service.patch_subject_service(subject_id, data)
        return jsonify({
            "status": "success",
            "message": "Cập nhật môn học thành công.",
            "data": updated_subject,
        }), 200
    except SubjectServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật môn học (PATCH): %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật môn học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi cập nhật môn học (PATCH): %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@subject_bp.delete("/v1/subjects/<subject_id>")
@subject_bp.delete("/subjects/<subject_id>")
@permission_required("course.manage")
def delete_subject(subject_id: str):
    """
    API xóa một môn học / học phần (SCRUM-123 - Activity A5).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Trả về 200 OK khi xóa thành công
    - Trả về 400 nếu subject_id sai định dạng UUID
    - Trả về 404 nếu không tìm thấy môn học
    - Trả về 409 nếu môn học đang có dữ liệu phụ thuộc không được phép xóa
    """
    try:
        result = subject_service.delete_subject_service(subject_id)
        return jsonify({
            "status": "success",
            "message": "Xóa môn học thành công.",
            "data": result,
        }), 200
    except SubjectServiceError as err:
        err_body = {
            "code": err.code,
            "message": err.message,
        }
        if getattr(err, "reason", None):
            err_body["reason"] = err.reason
        if getattr(err, "details", None):
            err_body["details"] = err.details
        return jsonify(err_body), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi xóa môn học: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xóa môn học.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi xóa môn học: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500



