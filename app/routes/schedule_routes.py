"""
Routes API quáº£n lĂ½ Thá»i khĂ³a biá»ƒu lá»›p há»c (Schedule Routes) - SCRUM-224.
- POST /api/v1/classes/<class_id>/schedules/preview: Xem trÆ°á»›c lá»‹ch sinh tá»± Ä‘á»™ng
- POST /api/v1/classes/<class_id>/schedules/generate: XĂ¡c nháº­n lÆ°u lá»‹ch há»c chĂ­nh thá»©c
- GET /api/v1/classes/<class_id>/schedules: Láº¥y danh sĂ¡ch thá»i khĂ³a biá»ƒu lá»›p há»c
- DELETE /api/v1/classes/<class_id>/schedules: XoĂ¡ thá»i khĂ³a biá»ƒu cá»§a lá»›p há»c
"""

import logging
from flask import Blueprint, g, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import schedule_service
from app.services.schedule_service import ScheduleConflictError, ScheduleServiceError
from app.utils.rbac_auth import permission_required

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api")


@schedule_bp.post("/v1/classes/<class_id>/schedules/preview")
@schedule_bp.post("/classes/<class_id>/schedules/preview")
@permission_required("course.manage")
def preview_schedule_endpoint(class_id: str):
    """
    API xem trÆ°á»›c thá»i khĂ³a biá»ƒu sinh tá»± Ä‘á»™ng theo máº«u láº·p (SCRUM-224 - AC 3).
    KhĂ´ng ghi vĂ o cÆ¡ sá»Ÿ dá»¯ liá»‡u.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dá»¯ liá»‡u yĂªu cáº§u khĂ´ng há»£p lá»‡.",
        }), 400

    try:
        preview_data = schedule_service.preview_schedule_service(class_id, payload)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_PREVIEW_GENERATED",
            "message": "Xem trÆ°á»›c thá»i khĂ³a biá»ƒu thĂ nh cĂ´ng.",
            "data": preview_data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi xem trÆ°á»›c thá»i khĂ³a biá»ƒu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi xem trÆ°á»›c lá»‹ch há»c.",
        }), 500


@schedule_bp.post("/v1/classes/<class_id>/schedules/generate")
@schedule_bp.post("/classes/<class_id>/schedules/generate")
@permission_required("course.manage")
def generate_schedule_endpoint(class_id: str):
    """
    API xĂ¡c nháº­n lÆ°u thá»i khĂ³a biá»ƒu lá»›p há»c chĂ­nh thá»©c (SCRUM-224 - AC 1, 2, 4).
    Kiá»ƒm tra chá»‘ng táº¡o trĂ¹ng láº·p qua cá» overwrite.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({
            "status": "error",
            "code": "INVALID_JSON",
            "message": "Dá»¯ liá»‡u yĂªu cáº§u khĂ´ng há»£p lá»‡.",
        }), 400

    try:
        saved_data = schedule_service.generate_schedule_service(class_id, payload)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_SAVED",
            "message": "LÆ°u thá»i khĂ³a biá»ƒu lá»›p há»c thĂ nh cĂ´ng.",
            "data": saved_data,
        }), 201
    except ScheduleConflictError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": {
                "conflicts": err.conflicts,
            },
        }), err.status_code
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi lÆ°u thá»i khĂ³a biá»ƒu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi lÆ°u lá»‹ch há»c.",
        }), 500


@schedule_bp.get("/v1/classes/<class_id>/schedules")
@schedule_bp.get("/classes/<class_id>/schedules")
@permission_required("course.view")
def get_class_schedules_endpoint(class_id: str):
    """
    API láº¥y danh sĂ¡ch thá»i khĂ³a biá»ƒu cá»§a má»™t lá»›p há»c.
    """
    try:
        data = schedule_service.get_class_schedules_service(class_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULES_RETRIEVED",
            "message": "Láº¥y danh sĂ¡ch thá»i khĂ³a biá»ƒu thĂ nh cĂ´ng.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi láº¥y thá»i khĂ³a biá»ƒu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi táº£i lá»‹ch há»c.",
        }), 500


@schedule_bp.delete("/v1/classes/<class_id>/schedules")
@schedule_bp.delete("/classes/<class_id>/schedules")
@permission_required("course.manage")
def delete_class_schedules_endpoint(class_id: str):
    """
    API xĂ³a toĂ n bá»™ thá»i khĂ³a biá»ƒu cá»§a má»™t lá»›p há»c.
    """
    try:
        data = schedule_service.delete_class_schedules_service(class_id)
        return jsonify({
            "status": "success",
            "code": "SCHEDULES_DELETED",
            "message": "XĂ³a thá»i khĂ³a biá»ƒu thĂ nh cĂ´ng.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi xĂ³a thá»i khĂ³a biá»ƒu: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi xĂ³a lá»‹ch há»c.",
        }), 500


@schedule_bp.put("/v1/classes/<class_id>/schedules/<schedule_id>")
@schedule_bp.put("/classes/<class_id>/schedules/<schedule_id>")
@permission_required("course.manage")
def update_schedule_item_endpoint(class_id: str, schedule_id: str):
    """
    API sá»­a hoáº·c dá»i má»™t buá»•i há»c Ä‘Æ¡n láº» (SCRUM-226 AC 1, AC 3, AC 4).
    - Äá»•i ngĂ y, giá», ca, phĂ²ng, giáº£ng viĂªn dáº¡y thay.
    - Cháº·n sá»­a buá»•i há»c Ä‘Ă£ Ä‘iá»ƒm danh (AC 4).
    - TĂ¡i sá»­ dá»¥ng kiá»ƒm tra xung Ä‘á»™t SCRUM-225 (loáº¡i trá»« chĂ­nh buá»•i Ä‘ang sá»­a).
    - Gá»­i thĂ´ng bĂ¡o thay Ä‘á»•i tá»›i há»c viĂªn vĂ  giáº£ng viĂªn cá»§a lá»›p (AC 3).
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = schedule_service.update_single_schedule_service(class_id, schedule_id, payload)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_UPDATED",
            "message": "Cáº­p nháº­t buá»•i há»c thĂ nh cĂ´ng.",
            "data": data,
        }), 200
    except ScheduleConflictError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
            "data": {
                "conflicts": err.conflicts,
                "has_conflicts": True,
            },
        }), err.status_code
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi cáº­p nháº­t buá»•i há»c: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi cáº­p nháº­t lá»‹ch há»c.",
        }), 500


@schedule_bp.post("/v1/classes/<class_id>/schedules/<schedule_id>/cancel")
@schedule_bp.post("/classes/<class_id>/schedules/<schedule_id>/cancel")
@permission_required("course.manage")
def cancel_schedule_item_endpoint(class_id: str, schedule_id: str):
    """
    API há»§y má»™t buá»•i há»c Ä‘Æ¡n láº» (SCRUM-226 AC 2, AC 3, AC 4).
    - Báº¯t buá»™c nháº­p lĂ½ do há»§y (cancellation_reason) (AC 2).
    - Cháº·n há»§y náº¿u buá»•i há»c Ä‘Ă£ Ä‘iá»ƒm danh (AC 4).
    - Gá»­i thĂ´ng bĂ¡o há»§y tá»›i há»c viĂªn vĂ  giáº£ng viĂªn cá»§a lá»›p (AC 3).
    """
    payload = request.get_json(silent=True) or {}
    try:
        data = schedule_service.cancel_single_schedule_service(class_id, schedule_id, payload)
        return jsonify({
            "status": "success",
            "code": "SCHEDULE_CANCELLED",
            "message": "Há»§y buá»•i há»c thĂ nh cĂ´ng.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi há»§y buá»•i há»c: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi há»§y buá»•i há»c.",
        }), 500


@schedule_bp.get("/v1/classes/<class_id>/schedules/<schedule_id>/notifications")
@schedule_bp.get("/classes/<class_id>/schedules/<schedule_id>/notifications")
@permission_required("course.manage")
def get_schedule_notifications_endpoint(class_id: str, schedule_id: str):
    """
    API láº¥y danh sĂ¡ch thĂ´ng bĂ¡o Ä‘Ă£ phĂ¡t cho má»™t buá»•i há»c (SCRUM-226 AC 3).
    """
    try:
        data = schedule_service.list_schedule_notifications_service(class_id, schedule_id)
        return jsonify({
            "status": "success",
            "code": "NOTIFICATIONS_FETCHED",
            "message": "Láº¥y danh sĂ¡ch thĂ´ng bĂ¡o thĂ nh cĂ´ng.",
            "data": data,
        }), 200
    except ScheduleServiceError as err:
        return jsonify({
            "status": "error",
            "code": err.code,
            "message": err.message,
        }), err.status_code
    except MySQLError as err:
        logger.error("Lá»—i DB khi láº¥y thĂ´ng bĂ¡o buá»•i há»c: %s", err)
        return jsonify({
            "status": "error",
            "code": "DATABASE_ERROR",
            "message": "Lá»—i cÆ¡ sá»Ÿ dá»¯ liá»‡u khi láº¥y thĂ´ng bĂ¡o.",
        }), 500


# Legacy session-level APIs retained from SCRUM-226.
def _error(error):
    return jsonify({"code": error.code, "message": error.message}), error.status_code


def _notification_summary(rows):
    if not rows:
        return {"status": "not_required", "items": []}
    states = {row["status"] for row in rows}
    status = "failed" if "failed" in states else "pending" if "pending" in states else "sent"
    return {"status": status, "items": rows}


@schedule_bp.get("/schedule")
@permission_required("course.view")
def list_sessions():
    try:
        items = schedule_service.list_sessions(request.args.get("status"))
        return jsonify({"status": "success", "data": {"items": items}}), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "KhĂ´ng thá»ƒ truy xuáº¥t lá»‹ch há»c."}), 500


@schedule_bp.get("/schedule/<session_id>")
@permission_required("course.view")
def get_session(session_id):
    try:
        return jsonify({"status": "success", "data": schedule_service.get_session(session_id)}), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "KhĂ´ng thá»ƒ truy xuáº¥t buá»•i há»c."}), 500


@schedule_bp.get("/schedule/<session_id>/notifications")
@permission_required("course.view")
def get_notifications(session_id):
    try:
        rows = schedule_service.get_notification_status(session_id)
        return jsonify({"status": "success", "data": _notification_summary(rows)}), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "KhĂ´ng thá»ƒ truy xuáº¥t tráº¡ng thĂ¡i thĂ´ng bĂ¡o."}), 500


def _perform(session_id, operation, data):
    try:
        result = operation(
            session_id=session_id,
            actor_user_id=g.login_session.user_id,
            data=data,
            request_key=request.headers.get("Idempotency-Key"),
        )
        return jsonify({
            "status": "success",
            "message": "Thay Ä‘á»•i buá»•i há»c Ä‘Ă£ Ä‘Æ°á»£c lÆ°u.",
            "data": {
                "session": result["session"],
                "duplicate": result["duplicate"],
                "notifications": _notification_summary(result["notifications"]),
            },
        }), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "KhĂ´ng thá»ƒ cáº­p nháº­t buá»•i há»c."}), 500


@schedule_bp.put("/schedule/<session_id>")
@permission_required("course.manage")
def edit_session(session_id):
    data = request.get_json(silent=True)
    return _perform(session_id, schedule_service.edit_session, data)


@schedule_bp.post("/schedule/<session_id>/reschedule")
@permission_required("course.manage")
def reschedule_session(session_id):
    data = request.get_json(silent=True)
    return _perform(session_id, schedule_service.reschedule_session, data)


@schedule_bp.post("/schedule/<session_id>/cancel")
@permission_required("course.manage")
def cancel_session(session_id):
    data = request.get_json(silent=True)
    return _perform(session_id, schedule_service.cancel_session, data)
