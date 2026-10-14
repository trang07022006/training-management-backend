from flask import Blueprint, g, jsonify, request
from mysql.connector import Error as MySQLError

from app.services import schedule_service
from app.utils.rbac_auth import permission_required


schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")


def _error(error):
    return jsonify({"code": error.code, "message": error.message}), error.status_code


def _notification_summary(rows):
    if not rows:
        return {"status": "not_required", "items": []}
    states = {row["status"] for row in rows}
    status = "failed" if "failed" in states else "pending" if "pending" in states else "sent"
    return {"status": status, "items": rows}


@schedule_bp.get("")
@permission_required("course.view")
def list_sessions():
    try:
        items = schedule_service.list_sessions(request.args.get("status"))
        return jsonify({"status": "success", "data": {"items": items}}), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "Không thể truy xuất lịch học."}), 500


@schedule_bp.get("/<session_id>")
@permission_required("course.view")
def get_session(session_id):
    try:
        return jsonify({"status": "success", "data": schedule_service.get_session(session_id)}), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "Không thể truy xuất buổi học."}), 500


@schedule_bp.get("/<session_id>/notifications")
@permission_required("course.view")
def get_notifications(session_id):
    try:
        rows = schedule_service.get_notification_status(session_id)
        return jsonify({"status": "success", "data": _notification_summary(rows)}), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "Không thể truy xuất trạng thái thông báo."}), 500


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
            "message": "Thay đổi buổi học đã được lưu.",
            "data": {
                "session": result["session"],
                "duplicate": result["duplicate"],
                "notifications": _notification_summary(result["notifications"]),
            },
        }), 200
    except schedule_service.ScheduleError as error:
        return _error(error)
    except MySQLError:
        return jsonify({"code": "DATABASE_ERROR", "message": "Không thể cập nhật buổi học."}), 500


@schedule_bp.put("/<session_id>")
@permission_required("course.manage")
def edit_session(session_id):
    data = request.get_json(silent=True)
    return _perform(session_id, schedule_service.edit_session, data)


@schedule_bp.post("/<session_id>/reschedule")
@permission_required("course.manage")
def reschedule_session(session_id):
    data = request.get_json(silent=True)
    return _perform(session_id, schedule_service.reschedule_session, data)


@schedule_bp.post("/<session_id>/cancel")
@permission_required("course.manage")
def cancel_session(session_id):
    data = request.get_json(silent=True)
    return _perform(session_id, schedule_service.cancel_session, data)
