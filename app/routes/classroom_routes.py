import logging
from flask import Blueprint, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import classroom_service
from app.services.classroom_service import ClassroomServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

classroom_bp = Blueprint("classroom_bp", __name__, url_prefix="/api")


@classroom_bp.post("/v1/rooms")
@classroom_bp.post("/v1/classrooms")
@classroom_bp.post("/rooms")
@classroom_bp.post("/classrooms")
@permission_required("course.manage")
def create_classroom_endpoint():
    """
    API khai báo phòng học vật lý hoặc trực tuyến (SCRUM-221 - 221-01).
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
        created = classroom_service.create_classroom_service(payload)
        return jsonify({
            "status": "success",
            "code": "ROOM_CREATED",
            "message": "Khai báo phòng học thành công.",
            "data": created,
        }), 201
    except ClassroomServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi tạo phòng học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi lưu thông tin phòng học.",
        }), 500


@classroom_bp.get("/v1/rooms")
@classroom_bp.get("/v1/classrooms")
@classroom_bp.get("/rooms")
@classroom_bp.get("/classrooms")
@permission_required("course.view")
def list_classrooms_endpoint():
    """
    API xem danh sách phòng học (SCRUM-221).
    Phân quyền: course.view.
    """
    room_type = request.args.get("room_type")
    status = request.args.get("status")
    search = request.args.get("search")
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = int(request.args.get("page_size", 50))
    except (ValueError, TypeError):
        page_size = 50

    try:
        result = classroom_service.list_classrooms_service(
            room_type=room_type,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
        )
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except ClassroomServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi đọc danh sách phòng học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất danh sách phòng học.",
        }), 500


@classroom_bp.get("/v1/rooms/<classroom_id>")
@classroom_bp.get("/v1/classrooms/<classroom_id>")
@classroom_bp.get("/rooms/<classroom_id>")
@classroom_bp.get("/classrooms/<classroom_id>")
@permission_required("course.view")
def get_classroom_detail_endpoint(classroom_id: str):
    """
    API xem chi tiết phòng học (SCRUM-221).
    """
    try:
        detail = classroom_service.get_classroom_detail_service(classroom_id)
        return jsonify({
            "status": "success",
            "data": detail,
        }), 200
    except ClassroomServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi lấy thông tin phòng học: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi truy xuất thông tin phòng học.",
        }), 500


@classroom_bp.route("/v1/rooms/<classroom_id>/check-capacity", methods=["GET", "POST"])
@classroom_bp.route("/v1/classrooms/<classroom_id>/check-capacity", methods=["GET", "POST"])
@classroom_bp.route("/rooms/<classroom_id>/check-capacity", methods=["GET", "POST"])
@classroom_bp.route("/classrooms/<classroom_id>/check-capacity", methods=["GET", "POST"])
@permission_required("course.view")
def check_room_capacity_endpoint(classroom_id: str):
    """
    API kiểm tra và cảnh báo sĩ số lớp vượt sức chứa phòng học (SCRUM-221 - 221-02).
    """
    class_id = request.args.get("class_id")
    if not class_id and request.is_json:
        payload = request.get_json(silent=True) or {}
        class_id = payload.get("class_id")

    if not class_id:
        return jsonify({
            "status": "error",
            "code": "MISSING_CLASS_ID",
            "message": "Vui lòng cung cấp mã ID của lớp học để kiểm tra sức chứa.",
        }), 400

    try:
        result = classroom_service.check_room_capacity_service(classroom_id, str(class_id).strip())
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except ClassroomServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lỗi cơ sở dữ liệu khi kiểm tra sức chứa phòng: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lỗi cơ sở dữ liệu khi kiểm tra sức chứa phòng học.",
        }), 500
