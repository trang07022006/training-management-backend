"""
Routes layer cho Rubric và chấm điểm bài tập - SCRUM-268.

Blueprints:
  rubric_bp   : /api/v1/rubric-templates
  assignment_bp: /api/v1/classes/<class_id>/assignments

Tích hợp vào main.py:
  from app.routes.rubric_routes import rubric_bp, assignment_bp
  app.register_blueprint(rubric_bp)
  app.register_blueprint(assignment_bp)
"""

import logging
from flask import Blueprint, jsonify, request, g
from mysql.connector import Error as MySQLError

from app.services import rubric_service
from app.services.rubric_service import RubricServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)


# ============================================================
# Blueprint 1: Rubric Templates
# ============================================================
rubric_bp = Blueprint("rubric_templates", __name__, url_prefix="/api/v1/rubric-templates")


def _error_response(exc: RubricServiceError):
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


def _internal_error_response(action: str):
    return jsonify({
        "code": "INTERNAL_ERROR",
        "message": f"Lỗi hệ thống khi {action}.",
        "error": {"code": "INTERNAL_ERROR", "message": f"Lỗi hệ thống khi {action}."},
    }), 500


# GET /api/v1/rubric-templates
@rubric_bp.get("")
@permission_required("rubric.view")
def list_rubric_templates():
    """
    Danh sách mẫu rubric.
    Query: ?my=true -> chỉ lấy template do mình tạo
    """
    try:
        my = request.args.get("my", "false").lower() == "true"
        created_by = g.user_id if my else None
        data = rubric_service.list_rubric_templates_service(created_by=created_by)
        return jsonify({"status": "success", "data": data, "total": len(data)}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error list rubric templates: %s", exc)
        return _db_error_response("lấy danh sách mẫu rubric")
    except Exception as exc:
        logger.exception("Unexpected error list rubric templates: %s", exc)
        return _internal_error_response("lấy danh sách mẫu rubric")


# POST /api/v1/rubric-templates
@rubric_bp.post("")
@permission_required("rubric.manage")
def create_rubric_template():
    """
    Tạo mẫu rubric mới kèm tiêu chí.
    Body: { name, description?, criteria: [{name, weight, max_score, description?}] }
    Ràng buộc: tổng weight của criteria = 100%
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = rubric_service.create_rubric_template_service(payload, created_by=g.user_id)
        return jsonify({"status": "success", "data": data}), 201
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error create rubric template: %s", exc)
        return _db_error_response("tạo mẫu rubric")
    except Exception as exc:
        logger.exception("Unexpected error create rubric template: %s", exc)
        return _internal_error_response("tạo mẫu rubric")


# GET /api/v1/rubric-templates/<template_id>
@rubric_bp.get("/<template_id>")
@permission_required("rubric.view")
def get_rubric_template(template_id: str):
    """Chi tiết mẫu rubric kèm danh sách tiêu chí."""
    try:
        data = rubric_service.get_rubric_template_service(template_id)
        return jsonify({"status": "success", "data": data}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error get rubric template: %s", exc)
        return _db_error_response("lấy chi tiết mẫu rubric")
    except Exception as exc:
        logger.exception("Unexpected error get rubric template: %s", exc)
        return _internal_error_response("lấy chi tiết mẫu rubric")


# PATCH /api/v1/rubric-templates/<template_id>
@rubric_bp.patch("/<template_id>")
@permission_required("rubric.manage")
def update_rubric_template(template_id: str):
    """
    Cập nhật mẫu rubric.
    - Nếu có 'criteria' trong body -> thay thế toàn bộ tiêu chí (tổng weight phải = 100%).
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = rubric_service.update_rubric_template_service(
            template_id, payload, current_user_id=g.user_id
        )
        return jsonify({
            "status": "success",
            "message": "Cập nhật mẫu rubric thành công.",
            "data": data,
        }), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error update rubric template: %s", exc)
        return _db_error_response("cập nhật mẫu rubric")
    except Exception as exc:
        logger.exception("Unexpected error update rubric template: %s", exc)
        return _internal_error_response("cập nhật mẫu rubric")


# DELETE /api/v1/rubric-templates/<template_id>
@rubric_bp.delete("/<template_id>")
@permission_required("rubric.manage")
def delete_rubric_template(template_id: str):
    """
    Xóa mềm mẫu rubric.
    Từ chối nếu template đang được gắn với bài tập.
    """
    try:
        result = rubric_service.delete_rubric_template_service(template_id)
        return jsonify({"status": "success", "message": result["message"]}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error delete rubric template: %s", exc)
        return _db_error_response("xóa mẫu rubric")
    except Exception as exc:
        logger.exception("Unexpected error delete rubric template: %s", exc)
        return _internal_error_response("xóa mẫu rubric")


# ============================================================
# Blueprint 2: Assignments (theo lớp)
# ============================================================
assignment_bp = Blueprint(
    "assignments", __name__, url_prefix="/api/v1/classes/<class_id>/assignments"
)


# GET /api/v1/classes/<class_id>/assignments
@assignment_bp.get("")
@permission_required("grade.manage")
def list_assignments(class_id: str):
    """Danh sách bài tập của lớp."""
    try:
        data = rubric_service.list_assignments_service(class_id)
        return jsonify({"status": "success", "data": data, "total": len(data)}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error list assignments: %s", exc)
        return _db_error_response("lấy danh sách bài tập")
    except Exception as exc:
        logger.exception("Unexpected error list assignments: %s", exc)
        return _internal_error_response("lấy danh sách bài tập")


# POST /api/v1/classes/<class_id>/assignments
@assignment_bp.post("")
@permission_required("grade.manage")
def create_assignment(class_id: str):
    """
    Tạo bài tập mới cho lớp.
    Body: { title, description?, rubric_template_id?, max_score? }
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = rubric_service.create_assignment_service(
            class_id, payload, created_by=g.user_id
        )
        return jsonify({"status": "success", "data": data}), 201
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error create assignment: %s", exc)
        return _db_error_response("tạo bài tập")
    except Exception as exc:
        logger.exception("Unexpected error create assignment: %s", exc)
        return _internal_error_response("tạo bài tập")


# GET /api/v1/classes/<class_id>/assignments/<assignment_id>
@assignment_bp.get("/<assignment_id>")
@permission_required("grade.manage")
def get_assignment(class_id: str, assignment_id: str):
    """Chi tiết bài tập."""
    try:
        data = rubric_service.get_assignment_service(assignment_id)
        return jsonify({"status": "success", "data": data}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error get assignment: %s", exc)
        return _db_error_response("lấy chi tiết bài tập")
    except Exception as exc:
        logger.exception("Unexpected error get assignment: %s", exc)
        return _internal_error_response("lấy chi tiết bài tập")


# PATCH /api/v1/classes/<class_id>/assignments/<assignment_id>
@assignment_bp.patch("/<assignment_id>")
@permission_required("grade.manage")
def update_assignment(class_id: str, assignment_id: str):
    """Cập nhật bài tập (title, description, rubric_template_id, max_score)."""
    payload = request.get_json(silent=True) or {}
    try:
        data = rubric_service.update_assignment_service(assignment_id, payload)
        return jsonify({
            "status": "success",
            "message": "Cập nhật bài tập thành công.",
            "data": data,
        }), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error update assignment: %s", exc)
        return _db_error_response("cập nhật bài tập")
    except Exception as exc:
        logger.exception("Unexpected error update assignment: %s", exc)
        return _internal_error_response("cập nhật bài tập")


# DELETE /api/v1/classes/<class_id>/assignments/<assignment_id>
@assignment_bp.delete("/<assignment_id>")
@permission_required("grade.manage")
def delete_assignment(class_id: str, assignment_id: str):
    """Xóa mềm bài tập."""
    try:
        result = rubric_service.delete_assignment_service(assignment_id)
        return jsonify({"status": "success", "message": result["message"]}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error delete assignment: %s", exc)
        return _db_error_response("xóa bài tập")
    except Exception as exc:
        logger.exception("Unexpected error delete assignment: %s", exc)
        return _internal_error_response("xóa bài tập")


# ============================================================
# Grading APIs (trong context assignment)
# ============================================================

# GET /api/v1/classes/<class_id>/assignments/<assignment_id>/grades
@assignment_bp.get("/<assignment_id>/grades")
@permission_required("grade.manage")
def list_grades(class_id: str, assignment_id: str):
    """
    Giảng viên xem điểm tất cả học viên của bài tập.
    Bao gồm điểm tổng và điểm chi tiết từng tiêu chí.
    """
    try:
        data = rubric_service.list_grades_service(assignment_id)
        return jsonify({"status": "success", "data": data, "total": len(data)}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error list grades: %s", exc)
        return _db_error_response("lấy danh sách điểm")
    except Exception as exc:
        logger.exception("Unexpected error list grades: %s", exc)
        return _internal_error_response("lấy danh sách điểm")


# POST /api/v1/classes/<class_id>/assignments/<assignment_id>/grades/<student_id>
@assignment_bp.post("/<assignment_id>/grades/<student_id>")
@permission_required("grade.manage")
def grade_student(class_id: str, assignment_id: str, student_id: str):
    """
    Giảng viên chấm điểm học viên theo rubric - SCRUM-268.
    Body: {
        criteria_scores: [{criteria_id, score, comment?}, ...],
        feedback?: str
    }
    Hệ thống tự động tính total_score = Σ(score_i / max_score_i * weight_i) / 10
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = rubric_service.grade_student_service(
            assignment_id=assignment_id,
            student_id=student_id,
            payload=payload,
            graded_by=g.user_id,
        )
        return jsonify({
            "status": "success",
            "message": "Chấm điểm thành công.",
            "data": data,
        }), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error grade student: %s", exc)
        return _db_error_response("chấm điểm học viên")
    except Exception as exc:
        logger.exception("Unexpected error grade student: %s", exc)
        return _internal_error_response("chấm điểm học viên")


# GET /api/v1/classes/<class_id>/assignments/<assignment_id>/my-grade
@assignment_bp.get("/<assignment_id>/my-grade")
@permission_required("grade.view_own")
def get_my_grade(class_id: str, assignment_id: str):
    """
    Học viên xem điểm của chính mình - SCRUM-268.
    Trả về: điểm tổng + điểm chi tiết từng tiêu chí + nhận xét.
    student_id lấy từ JWT (g.user_id -> tìm student_id tương ứng).
    """
    payload = request.get_json(silent=True) or {}
    # student_id phải được resolve từ user_id trong JWT
    # Frontend cần truyền student_id hoặc backend resolve qua student_repository
    student_id = payload.get("student_id") or request.args.get("student_id")
    if not student_id:
        return jsonify({
            "code": "INVALID_PARAMS",
            "message": "student_id là bắt buộc.",
        }), 400
    try:
        data = rubric_service.get_my_grade_service(assignment_id, student_id)
        return jsonify({"status": "success", "data": data}), 200
    except RubricServiceError as exc:
        return _error_response(exc)
    except MySQLError as exc:
        logger.exception("DB error get my grade: %s", exc)
        return _db_error_response("lấy điểm bài tập")
    except Exception as exc:
        logger.exception("Unexpected error get my grade: %s", exc)
        return _internal_error_response("lấy điểm bài tập")
