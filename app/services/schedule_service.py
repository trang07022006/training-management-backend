"""
Service quản lý Thời khóa biểu lớp học (Schedule Service) - SCRUM-224.
- Sinh thời khóa biểu tự động theo mẫu lặp (thứ trong tuần, ca học, ngày bắt đầu, số buổi).
- Tự động bỏ qua ngày nghỉ lễ đã khai báo và sinh đủ số buổi yêu cầu.
- Xem trước thời khóa biểu (preview) không lưu DB.
- Gắn từng buổi học với bài học trong môn học.
- Lưu lịch học chính thức với kiểm tra idempotency / chống lặp.
"""

from datetime import date, datetime, timedelta, time
import logging
from typing import Any

from app.models.class_schedule import ClassSchedule
from app.database.connection import get_db_connection
from app.repositories import schedule_repository
from app.repositories import (
    class_repository,
    class_schedule_repository,
    holiday_repository,
    subject_session_repository,
    user_repository,
    user_role_repository,
)
from app.services import authorization_service
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

# Định nghĩa các ca học tiêu chuẩn
DEFAULT_SHIFTS = {
    "shift_1": {"code": "shift_1", "name": "Ca 1 (07:30 - 09:30)", "start_time": "07:30:00", "end_time": "09:30:00"},
    "shift_2": {"code": "shift_2", "name": "Ca 2 (09:45 - 11:45)", "start_time": "09:45:00", "end_time": "11:45:00"},
    "shift_3": {"code": "shift_3", "name": "Ca 3 (13:30 - 15:30)", "start_time": "13:30:00", "end_time": "15:30:00"},
    "shift_4": {"code": "shift_4", "name": "Ca 4 (15:45 - 17:45)", "start_time": "15:45:00", "end_time": "17:45:00"},
    "shift_5": {"code": "shift_5", "name": "Ca 5 (18:00 - 20:30)", "start_time": "18:00:00", "end_time": "20:30:00"},
}

WEEKDAY_NAMES_VI = {
    0: "Thứ 2",
    1: "Thứ 3",
    2: "Thứ 4",
    3: "Thứ 5",
    4: "Thứ 6",
    5: "Thứ 7",
    6: "Chủ nhật",
}


class ScheduleServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, field: str | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        self.data = data


class ScheduleConflictError(ScheduleServiceError):
    def __init__(self, message: str, conflicts: list[dict], code: str = "SCHEDULE_CONFLICT_DETECTED"):
        super().__init__(code, message, status_code=409, data={"conflicts": conflicts})
        self.conflicts = conflicts


class ScheduleNotFoundError(ScheduleServiceError):
    def __init__(self, message: str = "Không tìm thấy buổi học."):
        super().__init__("SCHEDULE_NOT_FOUND", message, status_code=404)


class ScheduleAttendanceCheckedError(ScheduleServiceError):
    def __init__(self, message: str = "Không thể sửa hoặc hủy buổi học đã được điểm danh."):
        super().__init__("SCHEDULE_ATTENDANCE_ALREADY_CHECKED", message, status_code=400)


class ScheduleValidationError(ScheduleServiceError):
    def __init__(self, message: str, code: str = "INVALID_SCHEDULE_DATA", status_code: int = 400):
        super().__init__(code, message, status_code=status_code)


def normalize_time_str(val: Any) -> str:
    """Chuẩn hóa giá trị thời gian (time, timedelta, str) thành chuỗi HH:MM:SS có zero-padding (SCRUM-224/226)."""
    if val is None:
        return ""
    if isinstance(val, (datetime, time)):
        return val.strftime("%H:%M:%S")
    if isinstance(val, timedelta):
        total_seconds = int(val.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    s = str(val).strip()
    parts = s.split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            sec = int(parts[2]) if len(parts) > 2 else 0
            return f"{h:02d}:{m:02d}:{sec:02d}"
        except ValueError:
            pass
    return s


def parse_time_obj(val: Any) -> time:
    """Chuyển đổi giá trị thời gian thành đối tượng datetime.time để so sánh chính xác theo giờ phút giây."""
    if isinstance(val, time):
        return val
    if isinstance(val, datetime):
        return val.time()
    norm_s = normalize_time_str(val)
    return datetime.strptime(norm_s, "%H:%M:%S").time()


def check_conflict_override_permission(actor_user_id: str | None) -> None:
    """
    Kiểm tra quyền ghi đè xung đột lịch học (SCRUM-225).
    Chỉ Quản lý đào tạo (training_manager) hoặc người dùng có quyền schedule.manage mới được phép ghi đè.
    Admin thuần túy không được phép ghi đè.
    """
    if not actor_user_id:
        raise ScheduleServiceError(
            "SCHEDULE_OVERRIDE_FORBIDDEN",
            "Bạn không có quyền ghi đè xung đột lịch. Thao tác này chỉ dành cho Quản lý đào tạo.",
            status_code=403,
        )
    actor_roles = set(user_role_repository.get_role_codes_by_user_id(actor_user_id))
    u = user_repository.get_user_by_id(actor_user_id)
    if u and u.role:
        actor_roles.add(u.role)
    from app.services.authorization_service import has_permission
    if not (has_permission(actor_user_id, "schedule.manage") or "training_manager" in actor_roles):
        raise ScheduleServiceError(
            "SCHEDULE_OVERRIDE_FORBIDDEN",
            "Bạn không có quyền ghi đè xung đột lịch. Thao tác này chỉ dành cho Quản lý đào tạo.",
            status_code=403,
        )


def parse_day_of_week(val: Any) -> int | None:
    """
    Chuẩn hóa thứ trong tuần sang số nguyên 0..6 (theo chuẩn Python datetime.weekday: 0=Thứ 2, 6=Chủ nhật).
    Hỗ trợ cả format tiếng Việt và ISO:
    - 2, "2", "thu 2", "thứ 2", "t2", "mon", "monday" -> 0
    - 3, "3", "thu 3", "thứ 3", "t3", "tue", "tuesday" -> 1
    - 4, "4", "thu 4", "thứ 4", "t4", "wed", "wednesday" -> 2
    - 5, "5", "thu 5", "thứ 5", "t5", "thu", "thursday" -> 3
    - 6, "6", "thu 6", "thứ 6", "t6", "fri", "friday" -> 4
    - 7, "7", "thu 7", "thứ 7", "t7", "sat", "saturday" -> 5
    - 8, "8", "cn", "chu nhat", "chủ nhật", "sun", "sunday", 0, "0" -> 6
    """
    if val is None:
        return None
    s = str(val).strip().lower()
    mapping = {
        "2": 0, "thu 2": 0, "thứ 2": 0, "t2": 0, "mon": 0, "monday": 0,
        "3": 1, "thu 3": 1, "thứ 3": 1, "t3": 1, "tue": 1, "tuesday": 1,
        "4": 2, "thu 4": 2, "thứ 4": 2, "t4": 2, "wed": 2, "wednesday": 2,
        "5": 3, "thu 5": 3, "thứ 5": 3, "t5": 3, "thu": 3, "thursday": 3,
        "6": 4, "thu 6": 4, "thứ 6": 4, "t6": 4, "fri": 4, "friday": 4,
        "7": 5, "thu 7": 5, "thứ 7": 5, "t7": 5, "sat": 5, "saturday": 5,
        "8": 6, "cn": 6, "chu nhat": 6, "chủ nhật": 6, "sun": 6, "sunday": 6,
        "0": 6, # Nhiều thư viện dùng 0 là Sunday
    }
    return mapping.get(s)


def resolve_shift_and_time(payload: dict) -> tuple[str, str, str]:
    """
    Xác định tên ca học, giờ bắt đầu và giờ kết thúc từ payload (SCRUM-224 - AC 1).
    Validation: Giờ bắt đầu phải trước giờ kết thúc buổi học.
    """
    shift_code = payload.get("shift")
    start_time_in = payload.get("start_time")
    end_time_in = payload.get("end_time")

    if shift_code and str(shift_code).lower() in DEFAULT_SHIFTS:
        shift_data = DEFAULT_SHIFTS[str(shift_code).lower()]
        shift_name = shift_data["name"]
        start_time = start_time_in or shift_data["start_time"]
        end_time = end_time_in or shift_data["end_time"]
    elif not start_time_in or not end_time_in:
        norm = str(shift_code).strip().lower() if shift_code else ""
        if "ca 1" in norm or norm == "1":
            shift_name, start_time, end_time = DEFAULT_SHIFTS["shift_1"]["name"], DEFAULT_SHIFTS["shift_1"]["start_time"], DEFAULT_SHIFTS["shift_1"]["end_time"]
        elif "ca 2" in norm or norm == "2":
            shift_name, start_time, end_time = DEFAULT_SHIFTS["shift_2"]["name"], DEFAULT_SHIFTS["shift_2"]["start_time"], DEFAULT_SHIFTS["shift_2"]["end_time"]
        elif "ca 3" in norm or norm == "3":
            shift_name, start_time, end_time = DEFAULT_SHIFTS["shift_3"]["name"], DEFAULT_SHIFTS["shift_3"]["start_time"], DEFAULT_SHIFTS["shift_3"]["end_time"]
        elif "ca 4" in norm or norm == "4":
            shift_name, start_time, end_time = DEFAULT_SHIFTS["shift_4"]["name"], DEFAULT_SHIFTS["shift_4"]["start_time"], DEFAULT_SHIFTS["shift_4"]["end_time"]
        elif "ca 5" in norm or norm == "5":
            shift_name, start_time, end_time = DEFAULT_SHIFTS["shift_5"]["name"], DEFAULT_SHIFTS["shift_5"]["start_time"], DEFAULT_SHIFTS["shift_5"]["end_time"]
        else:
            raise ScheduleServiceError("INVALID_SHIFT_TIME", "Vui lòng chọn ca học hoặc nhập giờ bắt đầu và kết thúc hợp lệ.", field="shift")
    else:
        shift_name = str(shift_code) if shift_code else "Tùy chỉnh"
        start_time = start_time_in
        end_time = end_time_in

    norm_start = normalize_time_str(start_time)
    norm_end = normalize_time_str(end_time)
    try:
        t_start = parse_time_obj(norm_start)
        t_end = parse_time_obj(norm_end)
        if t_start >= t_end:
            raise ScheduleServiceError("INVALID_TIME_RANGE", "Giờ bắt đầu phải trước giờ kết thúc buổi học.", status_code=400, field="end_time")
    except ValueError:
        raise ScheduleServiceError("INVALID_SHIFT_TIME", "Định dạng giờ học không hợp lệ (HH:MM:SS).", status_code=400, field="shift")

    return shift_name, norm_start, norm_end


def _build_schedule_sessions(
    class_id: str,
    payload: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Hàm lõi sinh danh sách các buổi học theo mẫu lặp và bỏ qua ngày lễ (AC 1, 2, 4).
    Trả về: (generated_sessions, skipped_holidays)
    """
    # 1. Kiểm tra lớp học
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy thông tin lớp học.", status_code=404)

    # 2. Kiểm tra các thứ trong tuần
    raw_days = payload.get("days_of_week")
    if not raw_days or not isinstance(raw_days, (list, tuple)):
        raise ScheduleServiceError("DAYS_OF_WEEK_REQUIRED", "Vui lòng chọn ít nhất một thứ trong tuần để sinh lịch.", status_code=400, field="days_of_week")

    days_set = set()
    for d in raw_days:
        parsed_day = parse_day_of_week(d)
        if parsed_day is not None:
            days_set.add(parsed_day)

    if not days_set:
        raise ScheduleServiceError("INVALID_DAYS_OF_WEEK", "Danh sách thứ trong tuần không hợp lệ. Vui lòng chọn lại.", status_code=400, field="days_of_week")

    # 3. Kiểm tra ngày bắt đầu
    start_date_str = payload.get("start_date")
    if not start_date_str:
        raise ScheduleServiceError("START_DATE_REQUIRED", "Ngày bắt đầu không được để trống.", status_code=400, field="start_date")
    try:
        if isinstance(start_date_str, date):
            start_date_val = start_date_str
        else:
            start_date_val = datetime.strptime(str(start_date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ScheduleServiceError("INVALID_START_DATE", "Ngày bắt đầu phải theo định dạng YYYY-MM-DD.", status_code=400, field="start_date")

    # 4. Kiểm tra số buổi
    raw_total = payload.get("total_sessions")
    if raw_total is None or str(raw_total).strip() == "":
        raise ScheduleServiceError("TOTAL_SESSIONS_REQUIRED", "Số buổi học không được để trống.", status_code=400, field="total_sessions")
    try:
        total_sessions = int(raw_total)
    except (ValueError, TypeError):
        raise ScheduleServiceError("INVALID_TOTAL_SESSIONS", "Số buổi học phải là số nguyên dương.", status_code=400, field="total_sessions")

    if total_sessions < 1 or total_sessions > 200:
        raise ScheduleServiceError("INVALID_TOTAL_SESSIONS", "Số buổi học phải từ 1 đến 200 buổi.", status_code=400, field="total_sessions")

    # 5. Xác định ca học & thời gian
    shift_name, start_time, end_time = resolve_shift_and_time(payload)

    # 6. Lấy danh sách ngày nghỉ lễ đã khai báo (AC 2)
    holidays = holiday_repository.list_holidays()
    holiday_map = {}
    for h in holidays:
        h_date_str = h.holiday_date.strftime("%Y-%m-%d") if isinstance(h.holiday_date, (date, datetime)) else str(h.holiday_date)
        holiday_map[h_date_str] = h.name

    # 7. Lấy danh sách bài học môn học (AC 4)
    subject_id = payload.get("subject_id")
    class_subject_id = payload.get("class_subject_id")

    if subject_id or class_subject_id:
        class_subjects = class_repository.get_class_subjects(class_id)
        if not class_subjects:
            raise ScheduleServiceError(
                "SUBJECT_NOT_IN_CLASS",
                "Lớp học chưa có môn học nào hoặc môn học đã chọn không thuộc lớp này. Vui lòng cấu hình môn học cho lớp trước.",
                status_code=400,
                field="subject_id",
            )

        valid_subject_ids = {cs.subject_id for cs in class_subjects}
        valid_cs_ids = {cs.id for cs in class_subjects}

        matched = False
        if class_subject_id and class_subject_id in valid_cs_ids:
            matched = True
            for cs in class_subjects:
                if cs.id == class_subject_id:
                    subject_id = cs.subject_id
                    break
        elif subject_id and subject_id in valid_subject_ids:
            matched = True
            for cs in class_subjects:
                if cs.subject_id == subject_id:
                    class_subject_id = cs.id
                    break

        if not matched:
            raise ScheduleServiceError(
                "SUBJECT_NOT_IN_CLASS",
                "Môn học đã chọn không thuộc lớp này. Vui lòng chọn lại.",
                status_code=400,
                field="subject_id",
            )

    lessons = []
    if subject_id:
        lessons = subject_session_repository.list_subject_sessions_by_subject(subject_id)

    # Thông tin phòng học & giảng viên mặc định (nếu có)
    raw_room_id = payload.get("room_id")
    canonical_room_id = None
    if raw_room_id and str(raw_room_id).strip():
        r_val = str(raw_room_id).strip()
        from app.repositories import classroom_repository
        cr_room, _ = classroom_repository.find_unique_classroom_by_code_or_name(r_val)
        if not cr_room:
            raise ScheduleServiceError("ROOM_NOT_FOUND", "Phòng học không tồn tại trong danh mục hệ thống.", status_code=400, field="room_id")
        if cr_room.status != "active":
            raise ScheduleServiceError(
                "ROOM_NOT_ACTIVE",
                f"Phòng học '{cr_room.room_name}' ({cr_room.room_code}) đang ở trạng thái không khả dụng ({cr_room.status}).",
                status_code=400,
                field="room_id",
            )
        canonical_room_id = cr_room.id

    room_id = canonical_room_id
    instructor_id = payload.get("instructor_id")

    # 8. Vòng lặp sinh lịch đủ số buổi yêu cầu, bỏ qua ngày lễ
    generated_sessions = []
    skipped_holidays = []
    curr_date = start_date_val
    generated_count = 0
    max_days_guard = 1500  # Ngăn chặn infinite loop

    days_checked = 0
    while generated_count < total_sessions and days_checked < max_days_guard:
        days_checked += 1
        curr_weekday = curr_date.weekday()
        curr_date_str = curr_date.strftime("%Y-%m-%d")

        if curr_weekday in days_set:
            if curr_date_str in holiday_map:
                # Bỏ qua ngày nghỉ lễ nhưng không tăng generated_count (AC 2)
                skipped_holidays.append({
                    "date": curr_date_str,
                    "holiday_name": holiday_map[curr_date_str],
                    "day_of_week": WEEKDAY_NAMES_VI.get(curr_weekday, ""),
                    "reason": f"Nghỉ lễ: {holiday_map[curr_date_str]}",
                })
            else:
                generated_count += 1
                # Gắn bài học môn học (AC 4)
                topic = f"Buổi {generated_count}"
                subject_session_id = None
                if lessons:
                    if generated_count <= len(lessons):
                        matched_lesson = lessons[generated_count - 1]
                        topic = f"Buổi {generated_count}: {matched_lesson.topic}"
                        subject_session_id = matched_lesson.id
                    else:
                        topic = f"Buổi {generated_count}: Ôn tập / Thực hành"

                session_dict = {
                    "session_number": generated_count,
                    "learning_date": curr_date_str,
                    "day_of_week": WEEKDAY_NAMES_VI.get(curr_weekday, ""),
                    "shift": shift_name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "topic": topic,
                    "subject_id": subject_id,
                    "class_subject_id": class_subject_id,
                    "subject_session_id": subject_session_id,
                    "room_id": room_id,
                    "instructor_id": instructor_id,
                }
                generated_sessions.append(session_dict)

        curr_date += timedelta(days=1)

    return generated_sessions, skipped_holidays


def detect_schedule_conflicts(
    sessions: list[dict],
    exclude_class_id: str | None = None,
    exclude_schedule_id: str | None = None,
) -> list[dict]:
    """
    Kiểm tra xung đột lịch giảng viên và phòng học (SCRUM-225 - AC 1, AC 2).
    - Kiểm tra giao nhau thời gian (start_1 < end_2 AND end_1 > start_2).
    - Kiểm tra xung đột nội bộ giữa các buổi trong cùng đợt tạo.
    - Kiểm tra xung đột với các buổi học đã lưu trong cơ sở dữ liệu.
    """
    conflicts: list[dict] = []
    seen_conflict_keys = set()

    def add_conflict(c: dict):
        key = (
            c["conflict_type"],
            c["session_number"],
            c["learning_date"],
            c.get("conflicting_schedule_id") or c.get("conflicting_session_number"),
        )
        if key not in seen_conflict_keys:
            seen_conflict_keys.add(key)
            conflicts.append(c)

    # 1. Kiểm tra xung đột nội bộ giữa các buổi trong chính đợt tạo
    n = len(sessions)
    for i in range(n):
        si = sessions[i]
        for j in range(i + 1, n):
            sj = sessions[j]
            if si["learning_date"] == sj["learning_date"]:
                # Kiểm tra giao nhau thời gian thực tế
                if si["start_time"] < sj["end_time"] and si["end_time"] > sj["start_time"]:
                    # Xung đột giảng viên
                    if si.get("instructor_id") and si.get("instructor_id") == sj.get("instructor_id"):
                        add_conflict({
                            "conflict_type": "instructor",
                            "session_number": si["session_number"],
                            "learning_date": si["learning_date"],
                            "start_time": si["start_time"],
                            "end_time": si["end_time"],
                            "instructor_id": si.get("instructor_id"),
                            "room_id": None,
                            "conflicting_session_number": sj["session_number"],
                            "conflicting_class_code": "Đợt tạo hiện tại",
                            "conflicting_start_time": sj["start_time"],
                            "conflicting_end_time": sj["end_time"],
                            "message": (
                                f"Buổi #{si['session_number']} và Buổi #{sj['session_number']} "
                                f"bị trùng Giảng viên trong cùng khung giờ "
                                f"({si['learning_date']} {si['start_time']} - {si['end_time']})."
                            ),
                        })
                    # Xung đột phòng học
                    if si.get("room_id") and si.get("room_id") == sj.get("room_id"):
                        add_conflict({
                            "conflict_type": "room",
                            "session_number": si["session_number"],
                            "learning_date": si["learning_date"],
                            "start_time": si["start_time"],
                            "end_time": si["end_time"],
                            "instructor_id": None,
                            "room_id": si.get("room_id"),
                            "conflicting_session_number": sj["session_number"],
                            "conflicting_class_code": "Đợt tạo hiện tại",
                            "conflicting_start_time": sj["start_time"],
                            "conflicting_end_time": sj["end_time"],
                            "message": (
                                f"Buổi #{si['session_number']} và Buổi #{sj['session_number']} "
                                f"bị trùng Phòng học ({si['room_id']}) trong cùng khung giờ "
                                f"({si['learning_date']} {si['start_time']} - {si['end_time']})."
                            ),
                        })

    # 2. Kiểm tra xung đột với lịch đã lưu trong database
    for s in sessions:
        inst_id = s.get("instructor_id")
        r_id = s.get("room_id")
        if inst_id or r_id:
            db_conflicts = class_schedule_repository.find_conflicts_for_slot(
                learning_date=s["learning_date"],
                start_time=s["start_time"],
                end_time=s["end_time"],
                instructor_id=inst_id,
                room_id=r_id,
                exclude_class_id=exclude_class_id,
                exclude_schedule_id=exclude_schedule_id,
            )
            for db_c in db_conflicts:
                # Xung đột giảng viên
                if inst_id and db_c.get("instructor_id") == inst_id:
                    add_conflict({
                        "conflict_type": "instructor",
                        "session_number": s["session_number"],
                        "learning_date": s["learning_date"],
                        "start_time": s["start_time"],
                        "end_time": s["end_time"],
                        "instructor_id": inst_id,
                        "instructor_name": db_c.get("instructor_name") or inst_id,
                        "room_id": None,
                        "conflicting_schedule_id": db_c["id"],
                        "conflicting_class_id": db_c["class_id"],
                        "conflicting_class_code": db_c["class_code"],
                        "conflicting_session_number": db_c["session_number"],
                        "conflicting_start_time": db_c["start_time"],
                        "conflicting_end_time": db_c["end_time"],
                        "message": (
                            f"Buổi #{s['session_number']} ({s['learning_date']} {s['start_time']} - {s['end_time']}) "
                            f"bị trùng Giảng viên ({db_c.get('instructor_name') or inst_id}) "
                            f"với Buổi #{db_c['session_number']} của Lớp {db_c['class_code']} "
                            f"({db_c['start_time']} - {db_c['end_time']})."
                        ),
                    })
                # Xung đột phòng học
                if r_id and db_c.get("room_id") == r_id:
                    add_conflict({
                        "conflict_type": "room",
                        "session_number": s["session_number"],
                        "learning_date": s["learning_date"],
                        "start_time": s["start_time"],
                        "end_time": s["end_time"],
                        "instructor_id": None,
                        "room_id": r_id,
                        "conflicting_schedule_id": db_c["id"],
                        "conflicting_class_id": db_c["class_id"],
                        "conflicting_class_code": db_c["class_code"],
                        "conflicting_session_number": db_c["session_number"],
                        "conflicting_start_time": db_c["start_time"],
                        "conflicting_end_time": db_c["end_time"],
                        "message": (
                            f"Buổi #{s['session_number']} ({s['learning_date']} {s['start_time']} - {s['end_time']}) "
                            f"bị trùng Phòng học ({r_id}) "
                            f"với Buổi #{db_c['session_number']} của Lớp {db_c['class_code']} "
                            f"({db_c['start_time']} - {db_c['end_time']})."
                        ),
                    })

    return conflicts


def preview_schedule_service(class_id: str, payload: dict) -> dict:
    """
    API xem trước danh sách buổi học trước khi lưu (SCRUM-224 - AC 3, SCRUM-225 - AC 1, AC 2).
    Không ghi bất kỳ dữ liệu nào vào cơ sở dữ liệu.
    Cảnh báo rõ ràng các buổi đang xung đột giảng viên hoặc phòng học.
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    sessions, skipped = _build_schedule_sessions(class_id, payload)

    # Kiểm tra xung đột (SCRUM-225)
    overwrite = bool(payload.get("overwrite", False))
    conflicts = detect_schedule_conflicts(
        sessions,
        exclude_class_id=class_id if overwrite else None,
    )

    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "total_requested": payload.get("total_sessions"),
        "total_generated": len(sessions),
        "start_date": sessions[0]["learning_date"] if sessions else None,
        "end_date": sessions[-1]["learning_date"] if sessions else None,
        "schedules": sessions,
        "skipped_holidays": skipped,
        "conflicts": conflicts,
        "has_conflicts": len(conflicts) > 0,
    }


def generate_schedule_service(class_id: str, payload: dict, actor_user_id: str | None = None) -> dict:
    """
    API lưu thời khóa biểu chính thức vào cơ sở dữ liệu (SCRUM-224 & SCRUM-225).
    - SCRUM-224: Kiểm tra chống lặp / cờ overwrite trong một transaction nguyên tử có rollback.
    - SCRUM-225: Kiểm tra xung đột lịch giảng viên / phòng học. Trùng là lỗi chặn,
      không cho lưu, trừ khi Quản trị viên/Quản lý đào tạo xác nhận ghi đè (allow_conflict_override=True).
    - Bảo vệ dữ liệu điểm danh: chặn ghi đè nếu lớp đã có buổi học được điểm danh.
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    # Kiểm tra lịch hiện có
    existing_count = class_schedule_repository.count_schedules_by_class_id(class_id)
    overwrite = bool(payload.get("overwrite", False))

    if existing_count > 0 and not overwrite:
        date_range_str = ""
        try:
            existing_schedules = class_schedule_repository.list_schedules_by_class_id(class_id)
            if existing_schedules:
                min_date = existing_schedules[0].learning_date
                max_date = existing_schedules[-1].learning_date
                min_str = min_date.strftime("%d/%m/%Y") if hasattr(min_date, "strftime") else str(min_date)
                max_str = max_date.strftime("%d/%m/%Y") if hasattr(max_date, "strftime") else str(max_date)
                date_range_str = f" (từ ngày {min_str} đến ngày {max_str})"
        except Exception:
            pass

        raise ScheduleServiceError(
            "SCHEDULE_ALREADY_EXISTS",
            f"Lớp học đã có {existing_count} buổi học trong thời khóa biểu{date_range_str}. "
            f"Nếu bạn có quyền quản lý và muốn thay thế toàn bộ lịch này, vui lòng bật tùy chọn 'Ghi đè lịch đã có'.",
            status_code=409,
        )

    # Kiểm tra điểm danh trước khi cho phép ghi đè (SCRUM-224/226)
    if existing_count > 0 and overwrite:
        attended_count = class_schedule_repository.count_attendance_checked_by_class_id(class_id)
        if attended_count > 0:
            raise ScheduleAttendanceCheckedError(
                f"Không thể ghi đè thời khóa biểu vì lớp học đã có {attended_count} buổi học được điểm danh. Thao tác bị chặn để bảo vệ dữ liệu điểm danh."
            )

    # Sinh danh sách buổi học
    session_dicts, skipped = _build_schedule_sessions(class_id, payload)

    # Kiểm tra xung đột lịch tại thời điểm lưu (SCRUM-225 - AC 1, AC 2, AC 3)
    conflicts = detect_schedule_conflicts(
        session_dicts,
        exclude_class_id=class_id if overwrite else None,
    )

    allow_conflict_override = bool(payload.get("allow_conflict_override", False))
    if allow_conflict_override:
        # Không tin cờ client: kiểm tra quyền hạn thực tế tại backend (SCRUM-225)
        check_conflict_override_permission(actor_user_id)

    if conflicts and not allow_conflict_override:
        has_instructor = any(c.get("conflict_type") == "instructor" for c in conflicts)
        has_room = any(c.get("conflict_type") == "room" for c in conflicts)

        if has_instructor and not has_room:
            first_c = conflicts[0]
            inst_name = first_c.get("instructor_name") or first_c.get("instructor_id") or "giảng viên"
            date_val = first_c.get("learning_date")
            time_val = f"{first_c.get('start_time')} - {first_c.get('end_time')}"
            cls_code = first_c.get("conflicting_class_code") or "lớp khác"
            if len(conflicts) == 1:
                conflict_msg = (
                    f"Trùng lịch giảng viên: Giảng viên {inst_name} đã có lịch dạy vào ngày {date_val} lúc {time_val} (Lớp {cls_code})."
                )
            else:
                conflict_msg = (
                    f"Trùng lịch giảng viên ({len(conflicts)} buổi): Giảng viên {inst_name} bị trùng lịch, ví dụ ngày {date_val} lúc {time_val} (Lớp {cls_code})."
                )
        elif has_room and not has_instructor:
            first_c = conflicts[0]
            r_id = first_c.get("room_id") or "phòng học"
            date_val = first_c.get("learning_date")
            time_val = f"{first_c.get('start_time')} - {first_c.get('end_time')}"
            cls_code = first_c.get("conflicting_class_code") or "lớp khác"
            if len(conflicts) == 1:
                conflict_msg = (
                    f"Trùng phòng học: Phòng {r_id} đã có lịch sử dụng vào ngày {date_val} lúc {time_val} (Lớp {cls_code})."
                )
            else:
                conflict_msg = (
                    f"Trùng phòng học ({len(conflicts)} buổi): Phòng {r_id} bị trùng lịch, ví dụ ngày {date_val} lúc {time_val} (Lớp {cls_code})."
                )
        else:
            conflict_msg = (
                f"Phát hiện {len(conflicts)} xung đột lịch về giảng viên hoặc phòng học. "
                f"Hệ thống đã chặn lưu để tránh trùng giờ dạy. "
                f"Quản lý đào tạo cần xác nhận ghi đè để lưu lịch này."
            )
        raise ScheduleConflictError(conflict_msg, conflicts, code="SCHEDULE_CONFLICT_DETECTED")

    if conflicts and allow_conflict_override:
        logger.warning(
            "Người dùng %s đã xác nhận ghi đè %d xung đột lịch cho lớp %s (%s)",
            actor_user_id or "unspecified",
            len(conflicts),
            class_id,
            class_obj.class_code,
        )

    # Chuẩn bị model ClassSchedule để lưu batch
    schedule_models = []
    for s in session_dicts:
        model = ClassSchedule(
            id="",
            class_id=class_id,
            session_number=s["session_number"],
            topic=s["topic"],
            learning_date=s["learning_date"],
            shift=s["shift"],
            start_time=s["start_time"],
            end_time=s["end_time"],
            class_subject_id=s.get("class_subject_id"),
            subject_id=s.get("subject_id"),
            subject_session_id=s.get("subject_session_id"),
            room_id=s.get("room_id"),
            instructor_id=s.get("instructor_id"),
            status="scheduled",
            cancellation_reason=None,
            attendance_checked=False,
        )
        schedule_models.append(model)

    # Thực hiện thay thế hoặc chèn trong transaction nguyên tử có khóa hàng và rollback (SCRUM-224/226)
    try:
        saved_models = class_schedule_repository.replace_schedules_in_transaction(class_id, schedule_models)
    except RuntimeError as err:
        if "ATTENDANCE_CHECKED_LOCK" in str(err):
            raise ScheduleAttendanceCheckedError(
                "Không thể ghi đè thời khóa biểu vì lớp học đã có buổi học được điểm danh. Dữ liệu điểm danh được bảo vệ tuyệt đối."
            )
        raise

    # Cảnh báo sức chứa lớp học nếu phòng được gán là phòng vật lý
    capacity_warning = None
    if session_dicts and session_dicts[0].get("room_id"):
        from app.repositories import classroom_repository
        first_r_id = session_dicts[0]["room_id"]
        cr_room = classroom_repository.get_classroom_by_id(first_r_id)
        if cr_room and cr_room.room_type == "physical" and cr_room.capacity:
            effective_class_size = max(class_obj.max_capacity, class_obj.enrolled_count or 0)
            if effective_class_size > cr_room.capacity:
                capacity_warning = (
                    f"Sĩ số lớp vượt sức chứa phòng. (Lớp: {effective_class_size} học viên – "
                    f"Phòng: {cr_room.capacity} chỗ)"
                )

    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "total_saved": len(saved_models),
        "start_date": session_dicts[0]["learning_date"] if session_dicts else None,
        "end_date": session_dicts[-1]["learning_date"] if session_dicts else None,
        "schedules": [m.to_dict() for m in saved_models],
        "skipped_holidays": skipped,
        "conflicts": conflicts,
        "overridden_conflicts_count": len(conflicts) if allow_conflict_override else 0,
        "capacity_warning": capacity_warning,
    }


def get_class_schedules_service(class_id: str) -> dict:
    """Lấy danh sách thời khóa biểu của một lớp học kèm thông tin giảng viên và phòng học."""
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    schedules = class_schedule_repository.list_schedules_by_class_id(class_id)
    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "total": len(schedules),
        "schedules": [s.to_dict() for s in schedules],
    }


def delete_class_schedules_service(class_id: str) -> dict:
    """Xóa toàn bộ thời khóa biểu của một lớp học (chỉ khi chưa có buổi nào điểm danh)."""
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    attended_count = class_schedule_repository.count_attendance_checked_by_class_id(class_id)
    if attended_count > 0:
        raise ScheduleAttendanceCheckedError(
            f"Không thể xóa thời khóa biểu vì lớp học đã có {attended_count} buổi học được điểm danh. Thao tác bị chặn để bảo vệ dữ liệu điểm danh."
        )

    deleted_count = class_schedule_repository.delete_schedules_by_class_id(class_id)
    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "deleted_count": deleted_count,
    }


def dispatch_schedule_change_notifications(
    class_id: str,
    schedule: ClassSchedule,
    change_type: str,
    cancellation_reason: str | None = None,
    old_instructor_id: str | None = None,
) -> int:
    """
    Gửi thông báo thay đổi buổi học tới giảng viên và toàn bộ học viên của lớp (SCRUM-226 AC 3).
    Lưu bản ghi vào schedule_notifications và ghi log nghiệp vụ.
    Ánh xạ chính xác recipient_id với user_id của học viên để người dùng xem được thông báo.
    """
    class_obj = class_repository.get_class_by_id(class_id)
    class_code = class_obj.class_code if class_obj else class_id

    # Định dạng ngày giờ hiển thị
    ld_str = schedule.learning_date.strftime("%d/%m/%Y") if hasattr(schedule.learning_date, "strftime") else str(schedule.learning_date)
    st_str = normalize_time_str(schedule.start_time)[:5]
    et_str = normalize_time_str(schedule.end_time)[:5]

    if change_type == "cancelled":
        title = f"[ICTU] Thông báo hủy buổi học #{schedule.session_number} - Lớp {class_code}"
        message = (
            f"Buổi học #{schedule.session_number} ({schedule.topic}) của lớp {class_code} "
            f"dự kiến ngày {ld_str} ({st_str} - {et_str}) đã bị hủy.\n"
            f"Lý do: {cancellation_reason or schedule.cancellation_reason or 'Không có lý do cụ thể'}."
        )
    elif change_type == "rescheduled":
        title = f"[ICTU] Thông báo dời lịch buổi học #{schedule.session_number} - Lớp {class_code}"
        message = (
            f"Buổi học #{schedule.session_number} ({schedule.topic}) của lớp {class_code} "
            f"đã được dời sang ngày {ld_str}, khung giờ {st_str} - {et_str}"
            f"{f', phòng {schedule.room_name or schedule.room_id}' if (schedule.room_name or schedule.room_id) else ''}."
        )
    else:
        title = f"[ICTU] Thông báo cập nhật buổi học #{schedule.session_number} - Lớp {class_code}"
        message = (
            f"Buổi học #{schedule.session_number} ({schedule.topic}) của lớp {class_code} ngày {ld_str} "
            f"đã được cập nhật thông tin giảng viên / phòng học."
        )

    notifications_to_save: list[dict] = []
    seen_recipient_ids = set()

    # 1. Học viên ghi danh trong lớp (Chỉ phát thông báo tới học viên đã liên kết tài khoản người dùng)
    students = class_schedule_repository.get_class_enrollment_recipients(class_id)
    unlinked_students_count = 0
    for s in students:
        raw_uid = s.get("user_id")
        if not raw_uid:
            unlinked_students_count += 1
            logger.warning(
                "Bỏ qua phát thông báo hệ thống cho học viên %s (ID hồ sơ: %s) do chưa liên kết tài khoản người dùng.",
                s.get("full_name"),
                s.get("id"),
            )
            continue
        rec_id = str(raw_uid).strip()
        if rec_id and rec_id not in seen_recipient_ids:
            seen_recipient_ids.add(rec_id)
            notifications_to_save.append({
                "schedule_id": schedule.id,
                "class_id": class_id,
                "recipient_type": "student",
                "recipient_id": rec_id,
                "recipient_name": s.get("full_name") or "Học viên",
                "recipient_email": s.get("email"),
                "change_type": change_type,
                "title": title,
                "message": message,
            })

    # 2. Giảng viên phụ trách hiện tại
    if schedule.instructor_id and schedule.instructor_id not in seen_recipient_ids:
        seen_recipient_ids.add(schedule.instructor_id)
        inst_info = class_schedule_repository.get_user_info_by_id(schedule.instructor_id)
        notifications_to_save.append({
            "schedule_id": schedule.id,
            "class_id": class_id,
            "recipient_type": "instructor",
            "recipient_id": schedule.instructor_id,
            "recipient_name": inst_info.get("name") if inst_info else "Giảng viên",
            "recipient_email": inst_info.get("email") if inst_info else None,
            "change_type": change_type,
            "title": title,
            "message": message,
        })

    # 3. Giảng viên cũ (nếu thay đổi giảng viên dạy thay)
    if old_instructor_id and old_instructor_id != schedule.instructor_id and old_instructor_id not in seen_recipient_ids:
        seen_recipient_ids.add(old_instructor_id)
        old_inst_info = class_schedule_repository.get_user_info_by_id(old_instructor_id)
        notifications_to_save.append({
            "schedule_id": schedule.id,
            "class_id": class_id,
            "recipient_type": "instructor",
            "recipient_id": old_instructor_id,
            "recipient_name": old_inst_info.get("name") if old_inst_info else "Giảng viên",
            "recipient_email": old_inst_info.get("email") if old_inst_info else None,
            "change_type": change_type,
            "title": title,
            "message": message + " (Bạn đã được gỡ khỏi buổi học này do có giảng viên dạy thay).",
        })

    if notifications_to_save:
        class_schedule_repository.insert_schedule_notifications_batch(notifications_to_save)
        logger.info(
            "Đã phát %d thông báo thay đổi TKB (loại: %s) cho lớp %s buổi #%s",
            len(notifications_to_save),
            change_type,
            class_code,
            schedule.session_number,
        )

    return len(notifications_to_save)


def update_single_schedule_service(class_id: str, schedule_id: str, payload: dict, actor_user_id: str | None = None) -> dict:
    """
    Sửa hoặc dời một buổi học đơn lẻ (SCRUM-226 AC 1, AC 3, AC 4):
    - Đổi được ngày, giờ, phòng, giảng viên dạy thay.
    - Chặn sửa buổi học đã bị hủy (SCRUM-226).
    - Chặn sửa buổi học đã điểm danh (AC 4).
    - Tái sử dụng kiểm tra xung đột của SCRUM-225 (loại trừ chính buổi đang sửa).
    - Gửi thông báo tới học viên và giảng viên của lớp (AC 3).
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    schedule = class_schedule_repository.get_schedule_by_id(schedule_id)
    if not schedule or str(schedule.class_id) != str(class_id):
        raise ScheduleNotFoundError("Không tìm thấy buổi học trong lớp này.")

    # SCRUM-226: Mặc định chặn sửa buổi đã hủy
    if schedule.status == "cancelled":
        raise ScheduleValidationError("Không thể sửa hoặc đổi lịch buổi học đã bị hủy.")

    # AC 4: Không sửa được buổi đã điểm danh
    if schedule.attendance_checked:
        raise ScheduleAttendanceCheckedError("Không thể sửa hoặc dời buổi học đã được điểm danh.")

    # Thu thập dữ liệu cập nhật
    new_date = payload.get("learning_date") or schedule.learning_date
    if isinstance(new_date, str):
        try:
            datetime.strptime(new_date, "%Y-%m-%d")
        except ValueError:
            raise ScheduleValidationError("Định dạng ngày học không hợp lệ (cần YYYY-MM-DD).")

    new_shift = payload.get("shift") if "shift" in payload else schedule.shift
    new_start = payload.get("start_time") or schedule.start_time
    new_end = payload.get("end_time") or schedule.end_time

    if new_shift and new_shift in DEFAULT_SHIFTS and ("start_time" not in payload or not payload["start_time"]):
        new_start = DEFAULT_SHIFTS[new_shift]["start_time"]
        new_end = DEFAULT_SHIFTS[new_shift]["end_time"]

    str_start = normalize_time_str(new_start)
    str_end = normalize_time_str(new_end)
    try:
        t_start = parse_time_obj(str_start)
        t_end = parse_time_obj(str_end)
        if t_start >= t_end:
            raise ScheduleValidationError("Giờ bắt đầu phải trước giờ kết thúc buổi học.")
    except ValueError:
        raise ScheduleValidationError("Định dạng giờ học không hợp lệ (HH:MM:SS).")

    # Cho phép xóa gán phòng hoặc giảng viên khi gửi null hoặc rỗng
    if "room_id" in payload:
        raw_r = payload.get("room_id")
        new_room = str(raw_r).strip() if raw_r and str(raw_r).strip() else None
    else:
        new_room = schedule.room_id

    # Rà soát và kiểm tra phòng học theo danh mục chuẩn (SCRUM-221/226)
    from app.repositories import classroom_repository
    selected_classroom = None
    capacity_warning = None

    if new_room is not None:
        if new_room == schedule.room_id:
            # Người dùng không thay đổi trường phòng học (chỉ sửa các trường khác như ngày, giờ, topic...)
            # Bảo toàn dữ liệu phòng cũ (kể cả chuỗi legacy như 'P301') để tránh âm thầm xóa hay gán nhầm.
            selected_classroom, _ = classroom_repository.find_unique_classroom_by_code_or_name(new_room)
        else:
            # Người dùng chủ động chọn phòng mới: bắt buộc kiểm tra phòng tồn tại và trạng thái
            selected_classroom, match_type = classroom_repository.find_unique_classroom_by_code_or_name(new_room)
            if not selected_classroom:
                raise ScheduleValidationError("Phòng học không tồn tại trong danh mục hệ thống.", code="ROOM_NOT_FOUND")
            if selected_classroom.status != "active":
                raise ScheduleValidationError(
                    f"Phòng học '{selected_classroom.room_name}' ({selected_classroom.room_code}) đang ở trạng thái không khả dụng ({selected_classroom.status}).",
                    code="ROOM_NOT_ACTIVE",
                )
            # Chuẩn hóa về ID phòng chuẩn trong catalog
            new_room = selected_classroom.id

    # Cảnh báo sức chứa nếu là phòng vật lý
    if selected_classroom and selected_classroom.room_type == "physical" and selected_classroom.capacity:
        effective_class_size = max(class_obj.max_capacity, class_obj.enrolled_count or 0)
        if effective_class_size > selected_classroom.capacity:
            capacity_warning = (
                f"Sĩ số lớp vượt sức chứa phòng. (Lớp: {effective_class_size} học viên – "
                f"Phòng: {selected_classroom.capacity} chỗ)"
            )

    if "instructor_id" in payload:
        raw_inst = payload.get("instructor_id")
        new_instructor = str(raw_inst).strip() if raw_inst and str(raw_inst).strip() else None
    else:
        new_instructor = schedule.instructor_id

    new_topic = payload.get("topic") if "topic" in payload else schedule.topic
    allow_conflict_override = bool(payload.get("allow_conflict_override", False))
    if allow_conflict_override:
        check_conflict_override_permission(actor_user_id)

    # Tái sử dụng kiểm tra xung đột SCRUM-225 (loại trừ chính buổi đang sửa)
    conflicts = class_schedule_repository.find_conflicts_for_slot(
        learning_date=new_date,
        start_time=str_start,
        end_time=str_end,
        instructor_id=new_instructor or None,
        room_id=new_room or None,
        exclude_schedule_id=schedule.id,
    )

    if conflicts and not allow_conflict_override:
        raise ScheduleConflictError(
            f"Phát hiện xung đột lịch cho buổi học #{schedule.session_number}. Cần Quản lý đào tạo xác nhận ghi đè.",
            conflicts,
        )

    # Xác định trạng thái mới: nếu ngày hoặc giờ thay đổi thì là 'rescheduled'
    date_changed = str(new_date) != str(schedule.learning_date)
    time_changed = str_start[:5] != normalize_time_str(schedule.start_time)[:5]
    if date_changed or time_changed:
        change_type = "rescheduled"
    else:
        change_type = "updated"

    old_instructor = schedule.instructor_id

    # Cập nhật thông tin
    schedule.learning_date = new_date
    schedule.start_time = str_start
    schedule.end_time = str_end
    schedule.shift = new_shift
    schedule.room_id = new_room
    schedule.instructor_id = new_instructor
    if new_topic:
        schedule.topic = str(new_topic).strip()
    schedule.status = change_type

    updated_schedule = class_schedule_repository.update_schedule_item(schedule)

    # Gửi thông báo tới học viên và giảng viên (AC 3)
    recipients_count = dispatch_schedule_change_notifications(
        class_id=class_id,
        schedule=updated_schedule,
        change_type=change_type,
        old_instructor_id=old_instructor,
    )

    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "schedule": updated_schedule.to_dict(),
        "notifications_sent": recipients_count,
        "overridden_conflicts_count": len(conflicts) if allow_conflict_override else 0,
        "conflicts": conflicts if allow_conflict_override else [],
        "capacity_warning": capacity_warning,
    }


def cancel_single_schedule_service(class_id: str, schedule_id: str, payload: dict) -> dict:
    """
    Hủy một buổi học đơn lẻ (SCRUM-226 AC 2, AC 3, AC 4):
    - Bắt buộc nhập lý do hủy (cancellation_reason) (AC 2).
    - Chặn hủy nếu buổi học đã điểm danh (AC 4).
    - Học viên và giảng viên của lớp nhận được thông báo thay đổi (AC 3).
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    schedule = class_schedule_repository.get_schedule_by_id(schedule_id)
    if not schedule or str(schedule.class_id) != str(class_id):
        raise ScheduleNotFoundError("Không tìm thấy buổi học trong lớp này.")

    # AC 4: Không hủy được buổi đã điểm danh
    if schedule.attendance_checked:
        raise ScheduleAttendanceCheckedError("Không thể hủy buổi học đã được điểm danh.")

    # AC 2: Bắt buộc nhập lý do hủy
    reason = (payload.get("reason") or payload.get("cancellation_reason") or "").strip()
    if not reason:
        raise ScheduleValidationError("Lý do hủy buổi học là bắt buộc.", code="MISSING_CANCELLATION_REASON", status_code=400)

    schedule.status = "cancelled"
    schedule.cancellation_reason = reason

    updated_schedule = class_schedule_repository.update_schedule_item(schedule)

    # AC 3: Gửi thông báo hủy tới học viên và giảng viên
    recipients_count = dispatch_schedule_change_notifications(
        class_id=class_id,
        schedule=updated_schedule,
        change_type="cancelled",
        cancellation_reason=reason,
    )

    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "schedule": updated_schedule.to_dict(),
        "notifications_sent": recipients_count,
        "cancellation_reason": reason,
    }


def list_schedule_notifications_service(class_id: str, schedule_id: str | None = None) -> list[dict]:
    """Lấy danh sách thông báo thay đổi lịch học đã phát (SCRUM-226 AC 3)."""
    return class_schedule_repository.list_schedule_notifications(schedule_id=schedule_id, class_id=class_id)


def get_calendar_schedules_service(params: dict[str, Any]) -> dict[str, Any]:
    """
    Lấy danh sách thời khóa biểu dạng lịch tuần/tháng kèm bộ lọc (SCRUM-227 AC 1, 2, 4).
    Params:
    - date_from: YYYY-MM-DD
    - date_to: YYYY-MM-DD
    - class_id: ID lớp học
    - instructor_id: ID giảng viên
    - room_id: Mã / Tên phòng học
    - view_mode: 'week' | 'month' (mặc định 'week')
    - trainer_scope_user_id: ID giảng viên nếu người gọi là giảng viên (để giới hạn phạm vi)
    """
    date_from = (params.get("date_from") or "").strip() or None
    date_to = (params.get("date_to") or "").strip() or None
    class_id = (params.get("class_id") or "").strip() or None
    instructor_id = (params.get("instructor_id") or "").strip() or None
    room_id = (params.get("room_id") or "").strip() or None
    trainer_scope_user_id = params.get("trainer_scope_user_id")
    view_mode = (params.get("view_mode") or "week").strip().lower()
    if view_mode not in ("week", "month"):
        view_mode = "week"

    cal_kwargs: dict[str, Any] = {
        "date_from": date_from,
        "date_to": date_to,
        "class_id": class_id,
        "instructor_id": instructor_id,
        "room_id": room_id,
    }
    if trainer_scope_user_id:
        cal_kwargs["trainer_scope_user_id"] = trainer_scope_user_id

    schedules = class_schedule_repository.list_calendar_schedules(**cal_kwargs)

    return {
        "total": len(schedules),
        "date_from": date_from,
        "date_to": date_to,
        "view_mode": view_mode,
        "filters": {
            "class_id": class_id,
            "instructor_id": instructor_id,
            "room_id": room_id,
            "trainer_scoped": bool(trainer_scope_user_id),
        },
        "schedules": schedules,
    }


def get_schedule_detail_service(schedule_id: str) -> dict[str, Any]:
    """
    Lấy chi tiết một buổi học theo ID phục vụ popup xem chi tiết trên lịch (SCRUM-227 AC 3).
    """
    detail = class_schedule_repository.get_schedule_detail_by_id(schedule_id)
    if not detail:
        raise ScheduleNotFoundError("Không tìm thấy buổi học.")
    return detail


def get_my_personal_schedule_service(
    user_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ref_date: str | None = None,
    ref_time: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """
    Lấy thời khóa biểu cá nhân của người dùng đăng nhập (SCRUM-228).
    - Hỗ trợ tài khoản đa vai trò (trainer + trainee): cho phép chuyển đổi linh hoạt qua query ?context=teaching hoặc ?context=learning.
    - Học viên: lấy theo lớp đã ghi danh, trả về profile_linked, student, enrolled_classes, next_session, week_sessions.
    - Giảng viên: lấy theo phân công giảng dạy (chính, trợ giảng, dạy thay), trả về instructor, assigned_classes, assignment_status, next_session, week_sessions.
    - Phân biệt rõ: chưa được phân công vs đã phân công nhưng chưa có lịch.
    """
    if not user_id:
        raise ScheduleServiceError("UNAUTHORIZED", "Yêu cầu đăng nhập để truy cập lịch cá nhân.", status_code=401)

    # 1. Xác định thời gian mốc (cho phép truyền ref_date/ref_time phục vụ test)
    if ref_date and ref_date.strip():
        try:
            today = datetime.strptime(ref_date.strip(), "%Y-%m-%d").date()
        except Exception:
            today = datetime.now().date()
    else:
        today = datetime.now().date()

    if ref_time and ref_time.strip():
        current_time_str = ref_time.strip()
    else:
        current_time_str = datetime.now().strftime("%H:%M:%S")

    today_str = today.strftime("%Y-%m-%d")

    # 2. Xác định khoảng tuần (mặc định Thứ 2 -> Chủ nhật của tuần hiện tại)
    if date_from and date_from.strip() and date_to and date_to.strip():
        from_str = date_from.strip()
        to_str = date_to.strip()
    else:
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        from_str = monday.strftime("%Y-%m-%d")
        to_str = sunday.strftime("%Y-%m-%d")

    # 3. Tra cứu vai trò thực tế của người dùng
    roles = authorization_service.get_user_role_codes(user_id) if user_id else []
    is_pure_manager = any(r in roles for r in ["admin", "training_manager"]) and not ("trainee" in roles or "trainer" in roles)
    if is_pure_manager:
        raise ScheduleServiceError("FORBIDDEN", "Tài khoản quản trị không sử dụng lịch cá nhân. Vui lòng truy cập trang Thời khóa biểu.", status_code=403)

    is_trainer = "trainer" in roles
    is_trainee = "trainee" in roles or (not is_trainer)

    available_contexts = []
    if is_trainee:
        available_contexts.append("learning")
    if is_trainer:
        available_contexts.append("teaching")

    # Xác định ngữ cảnh hiển thị
    chosen_context = (context or "").strip().lower()
    if is_trainer and is_trainee:
        active_context = "teaching" if chosen_context == "teaching" else "learning"
    elif is_trainer:
        active_context = "teaching"
    else:
        active_context = "learning"

    # Ngữ cảnh: Giảng viên (Lịch giảng dạy)
    if active_context == "teaching":
        user_record = user_repository.get_user_by_id(user_id)
        instructor_dict = {
            "id": user_record.id if user_record else user_id,
            "full_name": user_record.name if user_record and hasattr(user_record, "name") else (user_record.full_name if user_record and hasattr(user_record, "full_name") else "Giảng viên"),
            "email": user_record.email if user_record else "",
        }
        assigned_classes = class_schedule_repository.get_trainer_assigned_classes(user_id)
        next_session = class_schedule_repository.get_trainer_next_session(user_id, today_str, current_time_str)
        week_sessions = class_schedule_repository.get_trainer_week_sessions(user_id, from_str, to_str)

        if not assigned_classes:
            assignment_status = "not_assigned"
        elif not week_sessions and not next_session:
            assignment_status = "assigned_no_schedule"
        else:
            assignment_status = "has_schedule"

        return {
            "user_type": "trainer",
            "active_context": "teaching",
            "available_contexts": available_contexts,
            "assignment_status": assignment_status,
            "profile_linked": True,
            "student": None,
            "instructor": instructor_dict,
            "assigned_classes": assigned_classes,
            "enrolled_classes": assigned_classes,
            "next_session": next_session,
            "week_sessions": week_sessions,
            "total_week_sessions": len(week_sessions),
            "date_from": from_str,
            "date_to": to_str,
            "period_title": f"Tuần từ {from_str} đến {to_str}",
        }

    # Ngữ cảnh: Học viên (Lịch học)
    student = class_schedule_repository.get_student_by_user_id(user_id)
    if not student:
        return {
            "user_type": "trainee",
            "active_context": "learning",
            "available_contexts": available_contexts,
            "profile_linked": False,
            "student": None,
            "enrolled_classes": [],
            "next_session": None,
            "week_sessions": [],
            "total_week_sessions": 0,
            "date_from": from_str,
            "date_to": to_str,
            "period_title": f"Tuần từ {from_str} đến {to_str}",
        }

    # 4. Tra cứu danh sách lớp đã ghi danh hợp lệ
    enrolled_classes = class_schedule_repository.get_enrolled_classes_for_student(student["id"])
    if not enrolled_classes:
        return {
            "user_type": "trainee",
            "active_context": "learning",
            "available_contexts": available_contexts,
            "profile_linked": True,
            "student": {
                "id": student.get("id"),
                "student_code": student.get("student_code"),
                "full_name": student.get("full_name"),
                "email": student.get("email"),
                "phone": student.get("phone"),
                "program_name": student.get("program_name"),
            },
            "enrolled_classes": [],
            "next_session": None,
            "week_sessions": [],
            "total_week_sessions": 0,
            "date_from": from_str,
            "date_to": to_str,
            "period_title": f"Tuần từ {from_str} đến {to_str}",
        }

    # 5. Lấy danh sách class_id
    class_ids = [c["class_id"] for c in enrolled_classes]

    # 6. Buổi học kế tiếp theo thời gian thực (loại trừ buổi đã hủy)
    next_session = class_schedule_repository.get_student_next_session(
        class_ids=class_ids,
        current_date=today_str,
        current_time=current_time_str,
    )

    # 7. Danh sách các buổi học trong tuần
    week_sessions = class_schedule_repository.get_student_week_sessions(
        class_ids=class_ids,
        date_from=from_str,
        date_to=to_str,
    )

    return {
        "user_type": "trainee",
        "active_context": "learning",
        "available_contexts": available_contexts,
        "profile_linked": True,
        "student": {
            "id": student.get("id"),
            "student_code": student.get("student_code"),
            "full_name": student.get("full_name"),
            "email": student.get("email"),
            "phone": student.get("phone"),
            "program_name": student.get("program_name"),
        },
        "enrolled_classes": enrolled_classes,
        "next_session": next_session,
        "week_sessions": week_sessions,
        "total_week_sessions": len(week_sessions),
        "date_from": from_str,
        "date_to": to_str,
        "period_title": f"Tuần từ {from_str} đến {to_str}",
    }


def get_student_schedule_by_student_id_service(
    student_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    ref_date: str | None = None,
    ref_time: str | None = None,
) -> dict[str, Any]:
    """
    Luồng quản lý xem thời khóa biểu của một học viên bất kỳ (SCRUM-228 Requirement 3).
    Dành riêng cho Quản trị viên và Quản lý đào tạo (yêu cầu quyền quản lý).
    """
    if not student_id or not student_id.strip():
        raise ScheduleServiceError("STUDENT_ID_REQUIRED", "Mã hồ sơ học viên không được để trống.", status_code=400)

    student = class_schedule_repository.get_student_by_student_id(student_id.strip())
    if not student:
        raise ScheduleServiceError("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học viên yêu cầu.", status_code=404)

    # 1. Xác định thời gian mốc
    if ref_date and ref_date.strip():
        try:
            today = datetime.strptime(ref_date.strip(), "%Y-%m-%d").date()
        except Exception:
            today = datetime.now().date()
    else:
        today = datetime.now().date()

    if ref_time and ref_time.strip():
        current_time_str = ref_time.strip()
    else:
        current_time_str = datetime.now().strftime("%H:%M:%S")

    today_str = today.strftime("%Y-%m-%d")

    # 2. Khoảng ngày
    if date_from and date_from.strip() and date_to and date_to.strip():
        from_str = date_from.strip()
        to_str = date_to.strip()
    else:
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        from_str = monday.strftime("%Y-%m-%d")
        to_str = sunday.strftime("%Y-%m-%d")

    enrolled_classes = class_schedule_repository.get_enrolled_classes_for_student(student["id"])
    if not enrolled_classes:
        return {
            "student": {
                "id": student.get("id"),
                "student_code": student.get("student_code"),
                "full_name": student.get("full_name"),
                "email": student.get("email"),
                "phone": student.get("phone"),
                "program_name": student.get("program_name"),
            },
            "enrolled_classes": [],
            "next_session": None,
            "week_sessions": [],
            "total_week_sessions": 0,
            "date_from": from_str,
            "date_to": to_str,
            "period_title": f"Tuần từ {from_str} đến {to_str}",
        }

    class_ids = [c["class_id"] for c in enrolled_classes]
    next_session = class_schedule_repository.get_student_next_session(
        class_ids=class_ids,
        current_date=today_str,
        current_time=current_time_str,
    )
    week_sessions = class_schedule_repository.get_student_week_sessions(
        class_ids=class_ids,
        date_from=from_str,
        date_to=to_str,
    )

    return {
        "student": {
            "id": student.get("id"),
            "student_code": student.get("student_code"),
            "full_name": student.get("full_name"),
            "email": student.get("email"),
            "phone": student.get("phone"),
            "program_name": student.get("program_name"),
        },
        "enrolled_classes": enrolled_classes,
        "next_session": next_session,
        "week_sessions": week_sessions,
        "total_week_sessions": len(week_sessions),
        "date_from": from_str,
        "date_to": to_str,
        "period_title": f"Tuần từ {from_str} đến {to_str}",
    }


def list_my_notifications_service(user_id: str | None) -> list[dict]:
    """Lấy danh sách thông báo của chính người dùng đăng nhập (SCRUM-226 & SCRUM-257)."""
    if not user_id:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, schedule_id, class_id, recipient_type, recipient_id,
                       recipient_name, recipient_email, change_type, title, message, created_at
                FROM (
                    SELECT id, schedule_id, class_id, recipient_type, recipient_id,
                           recipient_name, recipient_email, change_type, title, message, created_at
                    FROM schedule_notifications
                    WHERE recipient_id = %s
                    UNION ALL
                    SELECT id, NULL AS schedule_id, class_id, recipient_role AS recipient_type, recipient_id,
                           '' AS recipient_name, '' AS recipient_email, 'absence_alert' AS change_type, title, message, created_at
                    FROM absence_alert_notifications
                    WHERE recipient_id = %s
                ) notifs
                ORDER BY created_at DESC
                """,
                (user_id, user_id),
            )
            rows = cursor.fetchall() or []
            for r in rows:
                if hasattr(r["created_at"], "isoformat"):
                    r["created_at"] = r["created_at"].isoformat()
            return rows
    finally:
        conn.close()


# Legacy session-level schedule APIs (SCRUM-226)
class ScheduleError(Exception):
    def __init__(self, code, message, status_code=400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _parse_datetime(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ScheduleError("INVALID_DATETIME", f"{field} pháº£i lĂ  thá»i gian ISO-8601 há»£p lá»‡.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ScheduleError("INVALID_DATETIME", f"{field} pháº£i lĂ  thá»i gian ISO-8601 há»£p lá»‡.") from error
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def list_sessions(status=None):
    if status and status not in {"scheduled", "completed", "cancelled"}:
        raise ScheduleError("INVALID_STATUS", "Tráº¡ng thĂ¡i buá»•i há»c khĂ´ng há»£p lá»‡.")
    return schedule_repository.list_sessions(status)


def get_session(session_id):
    session = schedule_repository.get_session(session_id)
    if session is None:
        raise ScheduleError("SESSION_NOT_FOUND", "KhĂ´ng tĂ¬m tháº¥y buá»•i há»c.", 404)
    return session


def get_notification_status(session_id):
    get_session(session_id)
    return schedule_repository.get_notification_status(session_id)


def _request_key(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ScheduleError("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key pháº£i dĂ i tá»« 1 Ä‘áº¿n 128 kĂ½ tá»±.")
    return value.strip()


def _notify(result, action):
    for notification in result["notifications"]:
        try:
            session = result["session"]
            start = session["starts_at"].isoformat(sep=" ")
            end = session["ends_at"].isoformat(sep=" ")
            send_email(
                to_email=notification["recipient_email"],
                subject=f"[Training] Buá»•i há»c {action}: {session['topic']}",
                text_content=(f"Buá»•i há»c {session['topic']} Ä‘Ă£ Ä‘Æ°á»£c {action}. "
                              f"Lá»‹ch hiá»‡n táº¡i: {start} Ä‘áº¿n {end}. Tráº¡ng thĂ¡i: {session['status']}."),
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
            raise ScheduleError("IDEMPOTENCY_CONFLICT", "Request key Ä‘Ă£ Ä‘Æ°á»£c dĂ¹ng cho thao tĂ¡c khĂ¡c.", 409) from error
        raise
    if result is None:
        raise ScheduleError("SESSION_NOT_FOUND", "KhĂ´ng tĂ¬m tháº¥y buá»•i há»c.", 404)
    if "conflict" in result:
        code = result["conflict"]
        if code == "SCHEDULE_CONFLICT":
            raise ScheduleError(code, "Giáº£ng viĂªn hoáº·c phĂ²ng há»c Ä‘Ă£ cĂ³ lá»‹ch trong khoáº£ng thá»i gian nĂ y.", 409)
        if code == "SESSION_NOT_SCHEDULED":
            raise ScheduleError(code, "Chá»‰ cĂ³ thá»ƒ thay Ä‘á»•i buá»•i há»c Ä‘ang Ä‘Æ°á»£c lĂªn lá»‹ch.", 409)
        if code == "IDEMPOTENCY_CONFLICT":
            raise ScheduleError(code, "Idempotency-Key Ä‘Ă£ Ä‘Æ°á»£c dĂ¹ng cho thao tĂ¡c khĂ¡c.", 409)
        if code == "INVALID_CLASSROOM":
            raise ScheduleError(code, "PhĂ²ng há»c khĂ´ng tá»“n táº¡i.", 400)
        raise ScheduleError(code, "Thá»i gian káº¿t thĂºc pháº£i sau thá»i gian báº¯t Ä‘áº§u.")
    if result["notifications"]:
        _notify(result, {"edited": "cáº­p nháº­t", "rescheduled": "dá»i lá»‹ch", "cancelled": "há»§y"}[action])
    statuses = schedule_repository.get_notification_status(session_id)
    return {"session": result["session"], "duplicate": result["duplicate"], "notifications": statuses}


def edit_session(session_id, actor_user_id, data, request_key=None):
    if not isinstance(data, dict) or not data:
        raise ScheduleError("INVALID_BODY", "Request body pháº£i lĂ  JSON object khĂ´ng rá»—ng.")
    allowed = {"topic", "starts_at", "ends_at", "classroom_id"}
    if set(data) - allowed:
        raise ScheduleError("UNKNOWN_FIELDS", "Request chá»©a trÆ°á»ng khĂ´ng Ä‘Æ°á»£c há»— trá»£.")
    changes = {}
    if "topic" in data:
        if not isinstance(data["topic"], str) or not data["topic"].strip() or len(data["topic"].strip()) > 200:
            raise ScheduleError("INVALID_TOPIC", "Chá»§ Ä‘á» pháº£i cĂ³ tá»« 1 Ä‘áº¿n 200 kĂ½ tá»±.")
        changes["topic"] = data["topic"].strip()
    for field in ("starts_at", "ends_at"):
        if field in data:
            changes[field] = _parse_datetime(data[field], field)
    if "classroom_id" in data:
        if data["classroom_id"] is not None and (not isinstance(data["classroom_id"], str) or not data["classroom_id"].strip()):
            raise ScheduleError("INVALID_CLASSROOM", "classroom_id pháº£i lĂ  chuá»—i khĂ´ng rá»—ng hoáº·c null.")
        changes["classroom_id"] = data["classroom_id"].strip() if data["classroom_id"] else None
    return _apply(session_id, actor_user_id, "edited", changes, _request_key(request_key))


def reschedule_session(session_id, actor_user_id, data, request_key=None):
    if not isinstance(data, dict) or set(data) - {"starts_at", "ends_at", "classroom_id"}:
        raise ScheduleError("INVALID_BODY", "Chá»‰ cho phĂ©p starts_at, ends_at vĂ  classroom_id.")
    if "starts_at" not in data or "ends_at" not in data:
        raise ScheduleError("TIME_REQUIRED", "starts_at vĂ  ends_at lĂ  báº¯t buá»™c.")
    changes = {
        "starts_at": _parse_datetime(data["starts_at"], "starts_at"),
        "ends_at": _parse_datetime(data["ends_at"], "ends_at"),
    }
    if changes["ends_at"] <= changes["starts_at"]:
        raise ScheduleError("INVALID_TIME_RANGE", "Thá»i gian káº¿t thĂºc pháº£i sau thá»i gian báº¯t Ä‘áº§u.")
    if "classroom_id" in data:
        room = data["classroom_id"]
        if room is not None and (not isinstance(room, str) or not room.strip()):
            raise ScheduleError("INVALID_CLASSROOM", "classroom_id pháº£i lĂ  chuá»—i khĂ´ng rá»—ng hoáº·c null.")
        changes["classroom_id"] = room.strip() if room else None
    return _apply(session_id, actor_user_id, "rescheduled", changes, _request_key(request_key))


def cancel_session(session_id, actor_user_id, data, request_key=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - {"reason"}:
        raise ScheduleError("INVALID_BODY", "Request chá»‰ cháº¥p nháº­n trÆ°á»ng reason.")
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason.strip()) > 500:
        raise ScheduleError("INVALID_REASON", "LĂ½ do há»§y khĂ´ng Ä‘Æ°á»£c vÆ°á»£t quĂ¡ 500 kĂ½ tá»±.")
    return _apply(session_id, actor_user_id, "cancelled", {
        "cancellation_reason": reason.strip() or None,
    }, _request_key(request_key))
