"""
Routes layer cho quản lý buổi học của môn học (SCRUM-129 - Subject Sessions).
Bao gồm:
- GET /api/v1/subjects/<subject_id>/sessions và alias /api/subjects/<subject_id>/sessions
- GET /api/v1/subjects/<subject_id>/sessions/<session_id> và alias /api/subjects/<subject_id>/sessions/<session_id>
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import subject_session_service
from app.services.subject_session_service import SubjectSessionServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

subject_session_bp = Blueprint("subject_sessions", __name__, url_prefix="/api")


@subject_session_bp.get("/v1/subjects/<subject_id>/sessions")
@subject_session_bp.get("/subjects/<subject_id>/sessions")
@permission_required("course.view")
def get_subject_sessions(subject_id: str):
    """
    API xem danh sách các buổi học của một môn học (SCRUM-129 - Activity A2 / SCRUM-174).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Trả về tóm tắt môn học và danh sách buổi học sắp xếp theo session_number ASC.
    """
    try:
        data = subject_session_service.get_subject_sessions_service(subject_id)
        return jsonify({
            "status": "success",
            "data": data,
            "subject": data["subject"],
            "items": data["items"],
        }), 200

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when reading subject sessions: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn danh sách buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi truy vấn danh sách buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when reading subject sessions: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@subject_session_bp.get("/v1/subjects/<subject_id>/sessions/<session_id>")
@subject_session_bp.get("/subjects/<subject_id>/sessions/<session_id>")
@permission_required("course.view")
def get_subject_session_detail(subject_id: str, session_id: str):
    """
    API xem chi tiết một buổi học của môn học (SCRUM-129 - Activity A2).
    - Yêu cầu xác thực đăng nhập và quyền 'course.view'
    - Chống IDOR: Không cho phép đọc session_id không thuộc subject_id.
    """
    try:
        session_data = subject_session_service.get_subject_session_detail_service(
            subject_id=subject_id,
            session_id=session_id,
        )
        return jsonify({
            "status": "success",
            "data": session_data,
        }), 200

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when reading subject session detail: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy vấn chi tiết buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi truy vấn chi tiết buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when reading subject session detail: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@subject_session_bp.post("/v1/subjects/<subject_id>/sessions")
@subject_session_bp.post("/subjects/<subject_id>/sessions")
@permission_required("course.manage")
def create_subject_session(subject_id: str):
    """
    API thêm một buổi học mới cho môn học (SCRUM-129 - Activity A3 / SCRUM-175).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Trả về 201 Created cùng Header Location khi thành công.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}

    try:
        created_session = subject_session_service.create_subject_session_service(
            subject_id=subject_id,
            payload=payload,
        )
        location_header = f"/api/v1/subjects/{subject_id}/sessions/{created_session['id']}"
        response = jsonify({
            "status": "success",
            "data": created_session,
        })
        response.status_code = 201
        response.headers["Location"] = location_header
        return response

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when creating subject session: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi tạo buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi tạo buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when creating subject session: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@subject_session_bp.patch("/v1/subjects/<subject_id>/sessions/reorder")
@subject_session_bp.patch("/subjects/<subject_id>/sessions/reorder")
@permission_required("course.manage")
def reorder_subject_sessions(subject_id: str):
    """
    API sắp xếp lại thứ tự các buổi học của một môn học (SCRUM-129 - Activity A4).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Cập nhật số thứ tự 1..N theo mảng session_ids
    """
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}

    try:
        reordered = subject_session_service.reorder_subject_sessions_service(
            subject_id=subject_id,
            payload=payload,
        )
        return jsonify({
            "status": "success",
            "message": "Sắp xếp lại thứ tự buổi học thành công.",
            "data": reordered,
        }), 200

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when reordering subject sessions: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi sắp xếp lại buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi sắp xếp lại buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when reordering subject sessions: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@subject_session_bp.patch("/v1/subjects/<subject_id>/sessions/<session_id>")
@subject_session_bp.patch("/subjects/<subject_id>/sessions/<session_id>")
@permission_required("course.manage")
def update_subject_session(subject_id: str, session_id: str):
    """
    API cập nhật thông tin buổi học (SCRUM-129 - Activity A4 / SCRUM-175).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Cập nhật topic, objective
    """
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}

    try:
        updated = subject_session_service.update_subject_session_service(
            subject_id=subject_id,
            session_id=session_id,
            payload=payload,
        )
        return jsonify({
            "status": "success",
            "message": "Cập nhật buổi học thành công.",
            "data": updated,
        }), 200

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when updating subject session: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi cập nhật buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when updating subject session: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@subject_session_bp.delete("/v1/subjects/<subject_id>/sessions/<session_id>")
@subject_session_bp.delete("/subjects/<subject_id>/sessions/<session_id>")
@permission_required("course.manage")
def delete_subject_session(subject_id: str, session_id: str):
    """
    API xóa một buổi học của môn học (SCRUM-129 - Activity A4 / SCRUM-175).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Xóa buổi học và chuẩn hóa lại session_number 1..N
    """
    try:
        result = subject_session_service.delete_subject_session_service(
            subject_id=subject_id,
            session_id=session_id,
        )
        return jsonify({
            "status": "success",
            "message": result["message"],
            "data": result,
        }), 200

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when deleting subject session: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi xóa buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi xóa buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when deleting subject session: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Đã xảy ra lỗi hệ thống máy chủ nội bộ.",
            },
        }), 500


@subject_session_bp.post("/v1/subjects/<subject_id>/sessions/clone")
@subject_session_bp.post("/subjects/<subject_id>/sessions/clone")
@permission_required("course.manage")
def clone_subject_sessions(subject_id: str):
    """
    API nhân bản danh sách buổi học từ môn học khác (SCRUM-129 - Clone Sessions).
    - Yêu cầu xác thực đăng nhập và quyền 'course.manage'
    - Chạy trong 1 transaction an toàn (ALL OR NOTHING).
    """
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}

    try:
        result = subject_session_service.clone_subject_sessions_service(
            target_subject_id=subject_id,
            payload=payload,
        )
        return jsonify({
            "status": "success",
            "message": result["message"],
            "data": result,
        }), 201

    except SubjectSessionServiceError as exc:
        return jsonify({
            "code": exc.code,
            "message": exc.message,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }), exc.status_code

    except MySQLError as exc:
        logger.exception("MySQL database error when cloning subject sessions: %s", exc)
        return jsonify({
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi nhân bản buổi học.",
            "error": {
                "code": "DATABASE_ERROR",
                "message": "Lỗi cơ sở dữ liệu khi nhân bản buổi học.",
            },
        }), 500

    except Exception as exc:
        logger.exception("Unexpected error when cloning subject sessions: %s", exc)
        return jsonify({
            "code": "INTERNAL_ERROR",
            "message": "Không thể nhân bản danh sách buổi học. Vui lòng thử lại.",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Không thể nhân bản danh sách buổi học. Vui lòng thử lại.",
            },
        }), 500



