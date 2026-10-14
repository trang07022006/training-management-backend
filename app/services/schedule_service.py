from datetime import datetime, timezone
import logging

from mysql.connector.errors import IntegrityError

from app.repositories import schedule_repository
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


class ScheduleError(Exception):
    def __init__(self, code, message, status_code=400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _parse_datetime(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ScheduleError("INVALID_DATETIME", f"{field} phải là thời gian ISO-8601 hợp lệ.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ScheduleError("INVALID_DATETIME", f"{field} phải là thời gian ISO-8601 hợp lệ.") from error
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def list_sessions(status=None):
    if status and status not in {"scheduled", "completed", "cancelled"}:
        raise ScheduleError("INVALID_STATUS", "Trạng thái buổi học không hợp lệ.")
    return schedule_repository.list_sessions(status)


def get_session(session_id):
    session = schedule_repository.get_session(session_id)
    if session is None:
        raise ScheduleError("SESSION_NOT_FOUND", "Không tìm thấy buổi học.", 404)
    return session


def get_notification_status(session_id):
    get_session(session_id)
    return schedule_repository.get_notification_status(session_id)


def _request_key(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ScheduleError("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key phải dài từ 1 đến 128 ký tự.")
    return value.strip()


def _notify(result, action):
    for notification in result["notifications"]:
        try:
            session = result["session"]
            start = session["starts_at"].isoformat(sep=" ")
            end = session["ends_at"].isoformat(sep=" ")
            send_email(
                to_email=notification["recipient_email"],
                subject=f"[Training] Buổi học {action}: {session['topic']}",
                text_content=(f"Buổi học {session['topic']} đã được {action}. "
                              f"Lịch hiện tại: {start} đến {end}. Trạng thái: {session['status']}."),
            )
            schedule_repository.update_notification(notification["id"], "sent")
        except Exception as error:
            # Schedule and audit are already committed; log failed delivery without rolling them back.
            logger.warning("Schedule notification failed (%s)", type(error).__name__)
            schedule_repository.update_notification(
                notification["id"], "failed", type(error).__name__[:64]
            )


def _apply(session_id, actor_user_id, action, changes, request_key):
    try:
        result = schedule_repository.apply_change(
            session_id, actor_user_id, action, changes, request_key
        )
    except IntegrityError as error:
        if getattr(error, "errno", None) == 1062 and request_key:
            raise ScheduleError("IDEMPOTENCY_CONFLICT", "Request key đã được dùng cho thao tác khác.", 409) from error
        raise
    if result is None:
        raise ScheduleError("SESSION_NOT_FOUND", "Không tìm thấy buổi học.", 404)
    if "conflict" in result:
        code = result["conflict"]
        if code == "SCHEDULE_CONFLICT":
            raise ScheduleError(code, "Giảng viên hoặc phòng học đã có lịch trong khoảng thời gian này.", 409)
        if code == "SESSION_NOT_SCHEDULED":
            raise ScheduleError(code, "Chỉ có thể thay đổi buổi học đang được lên lịch.", 409)
        if code == "IDEMPOTENCY_CONFLICT":
            raise ScheduleError(code, "Idempotency-Key đã được dùng cho thao tác khác.", 409)
        if code == "INVALID_CLASSROOM":
            raise ScheduleError(code, "Phòng học không tồn tại.", 400)
        raise ScheduleError(code, "Thời gian kết thúc phải sau thời gian bắt đầu.")
    if result["notifications"]:
        _notify(result, {"edited": "cập nhật", "rescheduled": "dời lịch", "cancelled": "hủy"}[action])
    statuses = schedule_repository.get_notification_status(session_id)
    return {"session": result["session"], "duplicate": result["duplicate"], "notifications": statuses}


def edit_session(session_id, actor_user_id, data, request_key=None):
    if not isinstance(data, dict) or not data:
        raise ScheduleError("INVALID_BODY", "Request body phải là JSON object không rỗng.")
    allowed = {"topic", "starts_at", "ends_at", "classroom_id"}
    if set(data) - allowed:
        raise ScheduleError("UNKNOWN_FIELDS", "Request chứa trường không được hỗ trợ.")
    changes = {}
    if "topic" in data:
        if not isinstance(data["topic"], str) or not data["topic"].strip() or len(data["topic"].strip()) > 200:
            raise ScheduleError("INVALID_TOPIC", "Chủ đề phải có từ 1 đến 200 ký tự.")
        changes["topic"] = data["topic"].strip()
    for field in ("starts_at", "ends_at"):
        if field in data:
            changes[field] = _parse_datetime(data[field], field)
    if "classroom_id" in data:
        if data["classroom_id"] is not None and (not isinstance(data["classroom_id"], str) or not data["classroom_id"].strip()):
            raise ScheduleError("INVALID_CLASSROOM", "classroom_id phải là chuỗi không rỗng hoặc null.")
        changes["classroom_id"] = data["classroom_id"].strip() if data["classroom_id"] else None
    return _apply(session_id, actor_user_id, "edited", changes, _request_key(request_key))


def reschedule_session(session_id, actor_user_id, data, request_key=None):
    if not isinstance(data, dict) or set(data) - {"starts_at", "ends_at", "classroom_id"}:
        raise ScheduleError("INVALID_BODY", "Chỉ cho phép starts_at, ends_at và classroom_id.")
    if "starts_at" not in data or "ends_at" not in data:
        raise ScheduleError("TIME_REQUIRED", "starts_at và ends_at là bắt buộc.")
    changes = {
        "starts_at": _parse_datetime(data["starts_at"], "starts_at"),
        "ends_at": _parse_datetime(data["ends_at"], "ends_at"),
    }
    if changes["ends_at"] <= changes["starts_at"]:
        raise ScheduleError("INVALID_TIME_RANGE", "Thời gian kết thúc phải sau thời gian bắt đầu.")
    if "classroom_id" in data:
        room = data["classroom_id"]
        if room is not None and (not isinstance(room, str) or not room.strip()):
            raise ScheduleError("INVALID_CLASSROOM", "classroom_id phải là chuỗi không rỗng hoặc null.")
        changes["classroom_id"] = room.strip() if room else None
    return _apply(session_id, actor_user_id, "rescheduled", changes, _request_key(request_key))


def cancel_session(session_id, actor_user_id, data, request_key=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - {"reason"}:
        raise ScheduleError("INVALID_BODY", "Request chỉ chấp nhận trường reason.")
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason.strip()) > 500:
        raise ScheduleError("INVALID_REASON", "Lý do hủy không được vượt quá 500 ký tự.")
    return _apply(session_id, actor_user_id, "cancelled", {
        "cancellation_reason": reason.strip() or None,
    }, _request_key(request_key))
