"""
Các endpoint API Quản lý Lớp học (Class Routes) - SCRUM-217.
- Khai báo và mở lớp từ chương trình đào tạo (217-01)
- Kiểm tra mã lớp duy nhất (217-02)
- Cập nhật và xem vòng đời lớp: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ (217-03)
- Xem danh sách môn học sao chép của lớp (217-04)
"""

import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import class_service
from app.services.class_service import ClassServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

class_bp = Blueprint("classes", __name__, url_prefix="/api")


@class_bp.post("/v1/classes")
@class_bp.post("/classes")
@permission_required("course.manage")
def create_class_endpoint():
    """
    API mở lớp học mới từ chương trình đào tạo (SCRUM-217 - Sub-task 217-01).
    Phân quyền: Quản lý đào tạo (course.manage).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dữ liệu yêu cầu không hợp lệ.",
        }), 400

    try:
        created = class_service.create_class_service(payload)
        return jsonify({
            "status": "success",
            "code": "CLASS_CREATED",
            "message": "Mở lớp học từ chương trình đào tạo thành công.",
            "data": created,
        }), 201
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi mở lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu thông tin lớp học.",
        }), 500


@class_bp.get("/v1/classes")
@class_bp.get("/classes")
@permission_required("course.view")
def list_classes_endpoint():
    """
    API lấy danh sách lớp học có lọc theo chương trình, trạng thái, tìm kiếm.
    """
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    search = request.args.get("search")
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = int(request.args.get("page_size", 20))
    except (ValueError, TypeError):
        page_size = 20

    try:
        result = class_service.list_classes_service(
            program_id=program_id,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
        )
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất danh sách lớp học.",
        }), 500


@class_bp.get("/v1/classes/<class_id>")
@class_bp.get("/classes/<class_id>")
@permission_required("course.view")
def get_class_detail_endpoint(class_id: str):
    """
    API xem chi tiết thông tin lớp học kèm danh sách môn học đã sao chép (217-01 & 217-04).
    """
    try:
        detail = class_service.get_class_detail_service(class_id)
        return jsonify({
            "status": "success",
            "data": detail,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy chi tiết lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất thông tin lớp học.",
        }), 500


@class_bp.route("/v1/classes/<class_id>/status", methods=["PUT", "PATCH"])
@class_bp.route("/classes/<class_id>/status", methods=["PUT", "PATCH"])
@permission_required("course.manage")
def update_class_status_endpoint(class_id: str):
    """
    API cập nhật vòng đời trạng thái lớp học (SCRUM-217 - Sub-task 217-03).
    4 trạng thái hợp lệ: Chuẩn bị -> Đang học -> Kết thúc -> Huỷ.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "status" not in payload:
        return jsonify({
            "status": "error",
            "code": "STATUS_REQUIRED",
            "message": "Trạng thái mới của lớp học là bắt buộc.",
        }), 400

    new_status = payload.get("status")
    try:
        updated = class_service.update_class_lifecycle_status_service(class_id, new_status)
        return jsonify({
            "status": "success",
            "code": "STATUS_UPDATED",
            "message": f"Cập nhật trạng thái lớp học thành '{updated['status_label']}' thành công.",
            "data": updated,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi cập nhật trạng thái lớp học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi cập nhật trạng thái lớp học.",
        }), 500


@class_bp.get("/v1/classes/<class_id>/subjects")
@class_bp.get("/classes/<class_id>/subjects")
@permission_required("course.view")
def get_class_subjects_endpoint(class_id: str):
    """
    API xem riêng danh sách môn học của lớp đã sao chép từ chương trình (217-04).
    """
    try:
        subjects = class_service.get_class_subjects_service(class_id)
        return jsonify({
            "status": "success",
            "data": subjects,
        }), 200
    except ClassServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy danh sách môn học của lớp: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất môn học của lớp.",
        }), 500
