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
from flask_jwt_extended import get_jwt_identity
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
    search = request.args.get("search")
    status = request.args.get("status")
    interested_program_id = request.args.get("interested_program_id")
    assigned_to_user_id = request.args.get("assigned_to_user_id")
    source = request.args.get("source")
    date_from = request.args.get("date_from") or request.args.get("from_date")
    date_to = request.args.get("date_to") or request.args.get("to_date")
    sort_by = request.args.get("sort_by", default="created_at")
    sort_order = request.args.get("sort_order", default="DESC")

    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        result = lead_service.get_leads_service(
            page_raw=page_raw,
            page_size_raw=page_size_raw,
            search=search,
            status=status,
            interested_program_id=interested_program_id,
            assigned_to_user_id=assigned_to_user_id,
            source=source,
            date_from_raw=date_from,
            date_to_raw=date_to,
            sort_by=sort_by,
            sort_order=sort_order,
            actor_id=actor_id,
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


@lead_bp.get("/v1/leads/assignable-users")
@lead_bp.get("/leads/assignable-users")
@permission_required("course.manage")
def list_assignable_users():
    """
    API lấy danh sách nhân sự có thể tiếp nhận phân công Lead (SCRUM-127 - Activity A4).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Chỉ trả về danh sách tài khoản active có vai trò admin hoặc trainer.
    - Không trả về password_hash hoặc dữ liệu nhạy cảm.
    """
    try:
        users = lead_service.get_assignable_users_service()
        return jsonify({
            "status": "success",
            "data": users,
        }), 200

    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy danh sách nhân sự phân công: %s", err)
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
        logger.exception("Lỗi không mong muốn khi lấy danh sách nhân sự phân công: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.get("/v1/leads/pipeline")
@lead_bp.get("/leads/pipeline")
@permission_required("course.manage")
def get_lead_pipeline_endpoint():
    """
    API xem bảng phễu Lead (Kanban) theo 6 trạng thái chuẩn (SCRUM-213).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Tư vấn tuyển sinh chỉ thấy Lead được phân công cho mình.
    - Quản lý đào tạo và Admin xem toàn bộ dữ liệu Lead trong pipeline.
    """
    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        result = lead_service.get_lead_pipeline_service(actor_id=actor_id)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi tải bảng phễu Lead: %s", err)
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
        logger.exception("Lỗi không mong muốn khi tải bảng phễu Lead: %s", err)
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
    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        lead_data = lead_service.get_lead_by_id_service(lead_id, actor_id=actor_id)
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


@lead_bp.patch("/v1/leads/<lead_id>")
@lead_bp.patch("/leads/<lead_id>")
@permission_required("course.manage")
def update_lead_status_endpoint(lead_id: str):
    """
    API cập nhật trạng thái của một Lead (SCRUM-126 - Activity A3).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Chỉ cho phép cập nhật trường 'status'.
    - Kiểm tra trạng thái hợp lệ, cập nhật updated_at.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            "error": {
                "code": "INVALID_JSON",
                "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            },
        }), 400

    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        result = lead_service.update_lead_status_service(lead_id, body, actor_id=actor_id)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật trạng thái Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi cập nhật trạng thái Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.patch("/v1/leads/<lead_id>/assignment")
@lead_bp.patch("/leads/<lead_id>/assignment")
@permission_required("course.manage")
def assign_lead_endpoint(lead_id: str):
    """
    API phân công hoặc gỡ phân công Lead (SCRUM-127 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Body JSON: {"user_id": "<uuid>"} hoặc {"user_id": null}.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            "error": {
                "code": "INVALID_JSON",
                "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            },
        }), 400

    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        result = lead_service.assign_lead_service(lead_id, body, performed_by_user_id=actor_id)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi phân công Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi phân công Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.delete("/v1/leads/<lead_id>/assignment")
@lead_bp.delete("/leads/<lead_id>/assignment")
@permission_required("course.manage")
def unassign_lead_endpoint(lead_id: str):
    """
    API gỡ phân công Lead bằng phương thức DELETE (SCRUM-127 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    """
    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        result = lead_service.assign_lead_service(lead_id, None, performed_by_user_id=actor_id)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi gỡ phân công Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi gỡ phân công Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.post("/v1/leads/bulk-assignment")
@lead_bp.post("/leads/bulk-assignment")
@permission_required("course.manage")
def bulk_assign_leads_endpoint():
    """
    API phân công hoặc gỡ phân công đồng loạt nhiều Lead (SCRUM-127 - Activity A10).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Body JSON: {"lead_ids": ["uuid-1", "uuid-2"], "user_id": "<uuid>" hoặc null}.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            "error": {
                "code": "INVALID_JSON",
                "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            },
        }), 400

    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        result = lead_service.bulk_assign_leads_service(body, performed_by_user_id=actor_id)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi phân công đồng loạt Lead: %s", err)
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
        logger.exception("Lỗi không mong muốn khi phân công đồng loạt Lead: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.get("/v1/leads/<lead_id>/history")
@lead_bp.get("/leads/<lead_id>/history")
@permission_required("course.manage")
def get_lead_history_endpoint(lead_id: str):
    """
    API xem lịch sử chuyển giao / phân công của một Lead (SCRUM-127 - Activity A8).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    """
    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        history = lead_service.get_lead_assignment_history_service(lead_id, actor_id=actor_id)
        return jsonify({
            "status": "success",
            "data": history,
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
        logger.error("Lỗi cơ sở dữ liệu khi lấy lịch sử Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi lấy lịch sử Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.get("/v1/leads/<lead_id>/status-history")
@lead_bp.get("/leads/<lead_id>/status-history")
@permission_required("course.manage")
def get_lead_status_history_endpoint(lead_id: str):
    """
    API xem lịch sử thay đổi trạng thái của một Lead (SCRUM-213).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    """
    actor_id = None
    try:
        actor_id = get_jwt_identity()
    except Exception:
        pass

    try:
        history = lead_service.get_lead_status_history_service(lead_id, actor_id=actor_id)
        return jsonify({
            "status": "success",
            "data": history,
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
        logger.error("Lỗi cơ sở dữ liệu khi lấy lịch sử trạng thái Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi lấy lịch sử trạng thái Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500




@lead_bp.get("/v1/leads/check-phone")
@lead_bp.get("/leads/check-phone")
@permission_required("course.manage")
def check_lead_phone_endpoint():
    """
    API kiểm tra số điện thoại có trùng với lead đã có hay không (SCRUM-126).
    - Query params: phone (bắt buộc), exclude_id (tùy chọn).
    """
    phone = request.args.get("phone")
    exclude_id = request.args.get("exclude_id")

    try:
        result = lead_service.check_lead_phone_service(phone, exclude_id)
        return jsonify({
            "status": "success",
            "data": result,
        }), 200

    except Exception as err:
        logger.exception("Lỗi khi kiểm tra trùng số điện thoại Lead: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi khi kiểm tra số điện thoại.",
        }), 500


@lead_bp.post("/v1/leads")
@lead_bp.post("/leads")
@permission_required("course.manage")
def create_lead_endpoint():
    """
    API tạo khách hàng tiềm năng thủ công (SCRUM-126 - Tạo Lead).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Body JSON: { full_name, phone, email, source, interested_program_id, message }.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            "error": {
                "code": "INVALID_JSON",
                "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            },
        }), 400

    try:
        result = lead_service.create_manual_lead_service(body)
        return jsonify(result), 201

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
        logger.error("Lỗi cơ sở dữ liệu khi tạo Lead: %s", err)
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
        logger.exception("Lỗi không mong muốn khi tạo Lead: %s", err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.put("/v1/leads/<lead_id>")
@lead_bp.put("/leads/<lead_id>")
@permission_required("course.manage")
def update_lead_endpoint(lead_id: str):
    """
    API cập nhật thông tin chi tiết một Lead (SCRUM-126 - Sửa Lead).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'.
    - Body JSON: { full_name, phone, email, source, interested_program_id, message }.
    """
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            "error": {
                "code": "INVALID_JSON",
                "message": "Dữ liệu yêu cầu phải là JSON hợp lệ.",
            },
        }), 400

    try:
        result = lead_service.update_lead_info_service(lead_id, body)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật thông tin Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi cập nhật thông tin Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@lead_bp.delete("/v1/leads/<lead_id>")
@lead_bp.delete("/leads/<lead_id>")
@permission_required("lead.delete")
def delete_lead_endpoint(lead_id: str):
    """
    API xóa khách hàng tiềm năng (SCRUM-126).
    - Yêu cầu xác thực đăng nhập và quyền 'lead.delete' (chỉ dành cho Quản lý đào tạo).
    - Kiểm tra ID hợp lệ (400 nếu sai).
    - Trả về 404 nếu không tìm thấy.
    """
    try:
        result = lead_service.delete_lead_service(lead_id)
        return jsonify(result), 200

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
        logger.error("Lỗi cơ sở dữ liệu khi xóa Lead %s: %s", lead_id, err)
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
        logger.exception("Lỗi không mong muốn khi xóa Lead %s: %s", lead_id, err)
        return jsonify({
            "status": "error",
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500



