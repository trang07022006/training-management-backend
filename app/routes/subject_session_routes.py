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

