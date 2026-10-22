"""
Các endpoint quản lý chương trình đào tạo (SCRUM-122).
Bảo vệ bằng RBAC decorator @permission_required:
- 'course.view' cho các API đọc (Activity A2)
- 'course.manage' cho API tạo mới (Activity A3), cập nhật (Activity A4), xóa (Activity A5)

Endpoints:
- GET    /api/v1/training-programs               : Lấy danh sách chương trình đào tạo (hỗ trợ phân trang, lọc, tìm kiếm)
- GET    /api/v1/training-programs/<id>          : Lấy chi tiết một chương trình đào tạo
- POST   /api/v1/training-programs               : Tạo mới một chương trình đào tạo (yêu cầu quyền course.manage)
- PUT    /api/v1/training-programs/<program_id>  : Cập nhật toàn bộ thông tin chương trình đào tạo (yêu cầu quyền course.manage)
- PATCH  /api/v1/training-programs/<program_id>  : Cập nhật từng phần thông tin chương trình đào tạo (yêu cầu quyền course.manage)
- DELETE /api/v1/training-programs/<program_id>  : Xóa chương trình đào tạo an toàn (yêu cầu quyền course.manage)
"""

import logging
from flask import Blueprint, g, jsonify, request
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
    - Trả về 400 nếu ID sai định dạng UUID
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


@training_program_bp.post("/v1/training-programs")
@training_program_bp.post("/training-programs")
@permission_required("course.manage")
def create_training_program():
    """
    API tạo mới chương trình đào tạo (SCRUM-122 - Activity A3).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Request body: JSON chứa code, name, description, duration_semesters, status
    - Trả về 201 Created khi thành công kèm thông tin chương trình
    - Trả về 400 nếu dữ liệu không hợp lệ
    - Trả về 409 nếu trùng mã chương trình
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    try:
        created_program = training_program_service.create_training_program_service(data)
        response = jsonify({
            "status": "success",
            "message": "Tạo chương trình đào tạo thành công.",
            "data": created_program,
        })
        response.status_code = 201
        response.headers["Location"] = f"/api/v1/training-programs/{created_program['id']}"
        return response
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi tạo chương trình đào tạo: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tạo chương trình đào tạo.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi tạo chương trình đào tạo: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@training_program_bp.put("/v1/training-programs/<program_id>")
@training_program_bp.put("/training-programs/<program_id>")
@permission_required("course.manage")
def update_training_program(program_id: str):
    """
    API cập nhật toàn bộ thông tin chương trình đào tạo (SCRUM-122 - Activity A4 - PUT).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Request body: JSON chứa code, name, description, duration_semesters, status
    - Trả về 200 OK khi thành công kèm thông tin chương trình
    - Trả về 400 nếu dữ liệu không hợp lệ hoặc program_id sai định dạng
    - Trả về 404 nếu không tìm thấy chương trình
    - Trả về 409 nếu trùng mã chương trình
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    try:
        updated_program = training_program_service.update_training_program_service(program_id, data)
        return jsonify({
            "status": "success",
            "message": "Cập nhật chương trình đào tạo thành công.",
            "data": updated_program,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật chương trình đào tạo (PUT): %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật chương trình đào tạo.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi cập nhật chương trình đào tạo (PUT): %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@training_program_bp.patch("/v1/training-programs/<program_id>")
@training_program_bp.patch("/training-programs/<program_id>")
@permission_required("course.manage")
def patch_training_program(program_id: str):
    """
    API cập nhật từng phần thông tin chương trình đào tạo (SCRUM-122 - Activity A4 - PATCH).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Request body: JSON chứa ít nhất một trường cần cập nhật
    - Trả về 200 OK khi thành công kèm thông tin chương trình
    - Trả về 400 nếu dữ liệu không hợp lệ, rỗng hoặc program_id sai định dạng
    - Trả về 404 nếu không tìm thấy chương trình
    - Trả về 409 nếu trùng mã chương trình
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    try:
        updated_program = training_program_service.patch_training_program_service(program_id, data)
        return jsonify({
            "status": "success",
            "message": "Cập nhật chương trình đào tạo thành công.",
            "data": updated_program,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật chương trình đào tạo (PATCH): %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật chương trình đào tạo.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi cập nhật chương trình đào tạo (PATCH): %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@training_program_bp.delete("/v1/training-programs/<program_id>")
@training_program_bp.delete("/training-programs/<program_id>")
@permission_required("course.manage")
def delete_training_program(program_id: str):
    """
    API xóa một chương trình đào tạo (SCRUM-122 - Activity A5).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Trả về 200 OK khi xóa thành công
    - Trả về 400 nếu program_id sai định dạng UUID
    - Trả về 404 nếu không tìm thấy chương trình
    - Trả về 409 nếu chương trình đang có dữ liệu phụ thuộc không được phép xóa
    """
    try:
        result = training_program_service.delete_training_program_service(program_id)
        return jsonify({
            "status": "success",
            "message": "Xóa chương trình đào tạo thành công.",
            "data": result,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi xóa chương trình đào tạo: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xóa chương trình đào tạo.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi xóa chương trình đào tạo: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@training_program_bp.get("/v1/training-programs/<program_id>/absence-alert-threshold")
@training_program_bp.get("/training-programs/<program_id>/absence-alert-threshold")
@permission_required("course.view")
def get_program_absence_threshold(program_id: str):
    """
    API lấy cấu hình ngưỡng cảnh báo vắng và lịch sử audit của chương trình (SCRUM-257 - AC1).
    - Yêu cầu quyền 'course.view'
    - Trả về 200 OK kèm ngưỡng hiện hành và danh sách audit
    - Trả về 400 nếu program_id không đúng định dạng UUID
    - Trả về 404 nếu không tìm thấy chương trình
    """
    try:
        data = training_program_service.get_program_absence_threshold_service(program_id)
        return jsonify({
            "status": "success",
            "data": data,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy cấu hình ngưỡng cảnh báo vắng: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lấy cấu hình ngưỡng cảnh báo vắng.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi lấy cấu hình ngưỡng cảnh báo vắng: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500


@training_program_bp.put("/v1/training-programs/<program_id>/absence-alert-threshold")
@training_program_bp.put("/training-programs/<program_id>/absence-alert-threshold")
@permission_required("course.manage")
def update_program_absence_threshold(program_id: str):
    """
    API cập nhật ngưỡng cảnh báo vắng cho chương trình đào tạo (SCRUM-257 - AC1).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Request body: {"threshold": float, "reason": optional str}
      (hỗ trợ cả field "absence_alert_threshold")
    - Trả về 200 OK khi thành công kèm thông tin chương trình đã cập nhật
    - Trả về 400 nếu dữ liệu không hợp lệ (ngoài [0, 100], quá 2 chữ số thập phân, âm, ...)
    - Trả về 404 nếu không tìm thấy chương trình đào tạo
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là định dạng JSON hợp lệ.",
        }), 400

    raw_threshold = data.get("threshold")
    if raw_threshold is None:
        raw_threshold = data.get("absence_alert_threshold")

    if raw_threshold is None:
        return jsonify({
            "code": "INVALID_PARAMS",
            "message": "Trường 'threshold' hoặc 'absence_alert_threshold' là bắt buộc.",
        }), 400

    reason = data.get("reason")
    changed_by = getattr(g, "user_id", None) or "system"

    try:
        updated = training_program_service.update_program_absence_threshold_service(
            program_id=program_id,
            threshold_raw=raw_threshold,
            changed_by=changed_by,
            reason=reason,
        )
        return jsonify({
            "status": "success",
            "message": "Cập nhật ngưỡng cảnh báo vắng thành công.",
            "data": updated,
        }), 200
    except TrainingProgramServiceError as err:
        return jsonify({
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật ngưỡng cảnh báo vắng: %s", err)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật ngưỡng cảnh báo vắng.",
        }), 500
    except Exception as err:
        logger.exception("Lỗi không mong muốn khi cập nhật ngưỡng cảnh báo vắng: %s", err)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống khi xử lý yêu cầu.",
        }), 500
