"""
Routes layer cho Chấm điểm bài nộp và Nhật ký sửa điểm - SCRUM-267.
"""

import logging
from flask import Blueprint, jsonify, request, g
from mysql.connector import Error as MySQLError

from app.services import submission_service
from app.services.submission_service import SubmissionServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

submission_bp = Blueprint("submissions", __name__, url_prefix="/api/v1")


def _error_response(exc: SubmissionServiceError):
    return jsonify({
        "code": exc.code,
        "message": exc.message,
        "error": {"code": exc.code, "message": exc.message},
    }), exc.status_code


def _db_error_response(action: str):
    return jsonify({
        "code": "DATABASE_ERROR",
        "message": f"Lỗi cơ sở dữ liệu khi {action}.",
        "error": {"code": "DATABASE_ERROR", "message": f"Lỗi cơ sở dữ liệu khi {action}."},
    }), 500


# GET /api/v1/assignments/<assignment_id>/submissions
@submission_bp.get("/assignments/<assignment_id>/submissions")
@permission_required("submission.view")
def list_submissions(assignment_id: str):
    """Giảng viên xem danh sách bài nộp và tiến độ chấm điểm."""
    try:
        data = submission_service.list_submissions_service(assignment_id)
        return jsonify({"status": "success", "data": data}), 200
    except SubmissionServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error list submissions: %s", exc)
        return _db_error_response("lấy danh sách bài nộp")


# GET /api/v1/submissions/<submission_id>
@submission_bp.get("/submissions/<submission_id>")
@permission_required("submission.view")
def get_submission_detail(submission_id: str):
    """
    Xem chi tiết bài nộp (file preview, repo link) kèm thông tin bài kế tiếp (Speed Grading Navigation).
    """
    try:
        data = submission_service.get_submission_detail_service(submission_id)
        return jsonify({"status": "success", "data": data}), 200
    except SubmissionServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error get submission: %s", exc)
        return _db_error_response("lấy chi tiết bài nộp")


# POST /api/v1/submissions/<submission_id>/grade
@submission_bp.post("/submissions/<submission_id>/grade")
@permission_required("submission.grade")
def grade_submission(submission_id: str):
    """
    Giảng viên chấm điểm hoặc sửa điểm bài nộp - SCRUM-267.
    Body: { score, feedback?, change_reason? }
    Tự động ghi nhật ký sửa điểm (Audit Log).
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = submission_service.grade_submission_service(
            submission_id=submission_id,
            payload=payload,
            graded_by=g.user_id,
        )
        return jsonify({
            "status": "success",
            "message": "Lưu điểm bài nộp thành công.",
            "data": data,
        }), 200
    except SubmissionServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error grade submission: %s", exc)
        return _db_error_response("chấm điểm bài nộp")


# POST /api/v1/assignments/<assignment_id>/publish-grades
@submission_bp.post("/assignments/<assignment_id>/publish-grades")
@permission_required("submission.publish")
def publish_grades(assignment_id: str):
    """
    Giảng viên bấm Công bố điểm cho cả lớp - SCRUM-267.
    """
    try:
        data = submission_service.publish_grades_service(
            assignment_id=assignment_id,
            published_by=g.user_id,
        )
        return jsonify({"status": "success", "data": data}), 200
    except SubmissionServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error publish grades: %s", exc)
        return _db_error_response("công bố điểm bài tập")


# GET /api/v1/submissions/<submission_id>/audit-logs
@submission_bp.get("/submissions/<submission_id>/audit-logs")
@permission_required("submission.view")
def list_audit_logs(submission_id: str):
    """Xem nhật ký tất cả các lần sửa điểm của bài nộp - SCRUM-267."""
    try:
        data = submission_service.list_audit_logs_service(submission_id)
        return jsonify({"status": "success", "data": data, "total": len(data)}), 200
    except SubmissionServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error list audit logs: %s", exc)
        return _db_error_response("lấy nhật ký sửa điểm")


# GET /api/v1/assignments/<assignment_id>/my-submission
@submission_bp.get("/assignments/<assignment_id>/my-submission")
@permission_required("submission.view_own")
def get_my_submission(assignment_id: str):
    """
    Học viên xem bài nộp và điểm của mình.
    Điểm chỉ hiển thị khi giảng viên đã bấm Công bố.
    """
    student_id = request.args.get("student_id") or g.user_id
    try:
        data = submission_service.get_my_submission_service(assignment_id, student_id)
        return jsonify({"status": "success", "data": data}), 200
    except SubmissionServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error get my submission: %s", exc)
        return _db_error_response("lấy bài nộp của bạn")
