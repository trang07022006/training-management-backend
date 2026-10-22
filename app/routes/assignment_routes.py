"""
Endpoints API cho phân hệ Bài tập và Yêu cầu làm lại (Assignment Routes) - SCRUM-269.
Bao gồm:
- POST /api/v1/submissions/<submission_id>/request-rework (AC1: Yêu cầu làm lại)
- POST /api/v1/submissions/<submission_id>/resubmit (AC2: Nộp lại theo hạn mới)
- GET /api/v1/submissions/<submission_id> (AC3: Chi tiết bài nộp & số lần làm lại & lịch sử)
- GET /api/v1/assignments/<assignment_id>/submissions (Danh sách bài nộp của bài tập)
- GET /api/v1/assignments/<assignment_id>/my-submission (Bài nộp của chính học viên)
"""

import logging
from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt
from mysql.connector import Error as MySQLError

from app.services import assignment_service
from app.services.assignment_service import AssignmentServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

assignment_bp = Blueprint("assignments", __name__, url_prefix="/api")


def _get_current_roles() -> list[str]:
    jwt_claims = get_jwt()
    roles = jwt_claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    single_role = jwt_claims.get("role")
    if single_role and single_role not in roles:
        roles.append(single_role)
    return roles


@assignment_bp.post("/v1/submissions/<submission_id>/request-rework")
@assignment_bp.post("/v1/submissions/<submission_id>/rework")
@permission_required("assignment.grade")
def request_rework_endpoint(submission_id: str):
    """
    AC1: Giảng viên yêu cầu học viên làm lại bài tập kèm nhận xét bắt buộc.
    Chuyển bài nộp sang trạng thái 'Cần làm lại' (needs_rework).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    roles = _get_current_roles()
    is_admin_or_mgr = any(r in ("admin", "training_manager") for r in roles)

    try:
        updated = assignment_service.request_rework_service(
            submission_id=submission_id,
            instructor_user_id=g.user_id,
            payload=payload,
            is_admin_or_manager=is_admin_or_mgr,
        )
        return jsonify({
            "status": "success",
            "code": "REWORK_REQUESTED",
            "message": "Yêu cầu làm lại bài tập thành công.",
            "data": updated,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi yêu cầu làm lại bài: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xử lý yêu cầu làm lại.",
        }), 500


@assignment_bp.post("/v1/submissions/<submission_id>/resubmit")
@permission_required("assignment.submit")
def resubmit_endpoint(submission_id: str):
    """
    AC2: Học viên nộp lại bài tập theo hạn mới.
    Bảo toàn toàn bộ các lần nộp cũ.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    try:
        updated = assignment_service.resubmit_service(
            submission_id=submission_id,
            student_user_id=g.user_id,
            payload=payload,
        )
        return jsonify({
            "status": "success",
            "code": "ASSIGNMENT_RESUBMITTED",
            "message": "Nộp lại bài tập thành công.",
            "data": updated,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi học viên nộp lại bài: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi nộp lại bài tập.",
        }), 500


@assignment_bp.get("/v1/submissions/<submission_id>")
@permission_required("assignment.view")
def get_submission_detail_endpoint(submission_id: str):
    """
    AC3: Xem chi tiết bài nộp, số lần yêu cầu làm lại và lịch sử các lần nộp/yêu cầu.
    """
    roles = _get_current_roles()
    try:
        detail = assignment_service.get_submission_detail_service(
            submission_id=submission_id,
            user_id=g.user_id,
            user_roles=roles,
        )
        return jsonify({
            "status": "success",
            "code": "SUBMISSION_DETAIL",
            "message": "Lấy chi tiết bài nộp thành công.",
            "data": detail,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy chi tiết bài nộp: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải thông tin bài nộp.",
        }), 500


@assignment_bp.get("/v1/assignments/<assignment_id>/submissions")
@permission_required("assignment.view")
def list_assignment_submissions_endpoint(assignment_id: str):
    """
    Lấy danh sách tất cả bài nộp của bài tập cho Giảng viên.
    """
    roles = _get_current_roles()
    is_admin_or_mgr = any(r in ("admin", "training_manager") for r in roles)

    try:
        result = assignment_service.list_assignment_submissions_service(
            assignment_id=assignment_id,
            instructor_user_id=g.user_id,
            is_admin_or_mgr=is_admin_or_mgr,
        )
        return jsonify({
            "status": "success",
            "code": "SUBMISSIONS_LIST",
            "message": "Lấy danh sách bài nộp thành công.",
            "data": result,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy danh sách bài nộp: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải danh sách bài nộp.",
        }), 500


@assignment_bp.get("/v1/assignments/<assignment_id>/my-submission")
@permission_required("assignment.submit")
def get_my_submission_endpoint(assignment_id: str):
    """
    Học viên lấy thông tin bài nộp của chính mình cho bài tập.
    """
    try:
        detail = assignment_service.get_my_submission_service(
            assignment_id=assignment_id,
            student_user_id=g.user_id,
        )
        return jsonify({
            "status": "success",
            "code": "MY_SUBMISSION",
            "message": "Lấy bài nộp của bạn thành công.",
            "data": detail,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy bài nộp của học viên: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải bài nộp của bạn.",
        }), 500


@assignment_bp.get("/v1/classes/<class_id>/assignments")
@permission_required("assignment.view")
def list_class_assignments_endpoint(class_id: str):
    """Lấy danh sách các bài tập của một lớp học."""
    roles = _get_current_roles()
    try:
        assignments = assignment_service.list_class_assignments_service(
            class_id=class_id,
            user_id=g.user_id,
            user_roles=roles,
        )
        return jsonify({
            "status": "success",
            "code": "ASSIGNMENTS_LIST",
            "message": "Lấy danh sách bài tập thành công.",
            "data": assignments,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy danh sách bài tập: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tải danh sách bài tập.",
        }), 500


@assignment_bp.post("/v1/classes/<class_id>/assignments")
@permission_required("assignment.grade")
def create_assignment_endpoint(class_id: str):
    """Giảng viên giao bài tập mới cho lớp học."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    roles = _get_current_roles()
    is_admin_or_mgr = any(r in ("admin", "training_manager") for r in roles)

    try:
        created = assignment_service.create_assignment_service(
            class_id=class_id,
            instructor_user_id=g.user_id,
            payload=payload,
            is_admin_or_mgr=is_admin_or_mgr,
        )
        return jsonify({
            "status": "success",
            "code": "ASSIGNMENT_CREATED",
            "message": "Giao bài tập mới thành công.",
            "data": created,
        }), 201
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi tạo bài tập mới: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi giao bài tập mới.",
        }), 500


@assignment_bp.post("/v1/submissions/<submission_id>/grade")
@permission_required("assignment.grade")
def grade_submission_endpoint(submission_id: str):
    """Giảng viên đánh giá, chấm điểm và xác nhận bài nộp của học viên."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    roles = _get_current_roles()
    is_admin_or_mgr = any(r in ("admin", "training_manager") for r in roles)

    try:
        graded = assignment_service.grade_submission_service(
            submission_id=submission_id,
            instructor_user_id=g.user_id,
            payload=payload,
            is_admin_or_mgr=is_admin_or_mgr,
        )
        return jsonify({
            "status": "success",
            "code": "SUBMISSION_GRADED",
            "message": "Đánh giá và xác nhận bài tập thành công.",
            "data": graded,
        }), 200
    except AssignmentServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi chấm điểm bài nộp: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi đánh giá bài nộp.",
        }), 500

