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
from app.repositories import (
    class_repository,
    class_schedule_repository,
    holiday_repository,
    subject_session_repository,
)

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
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ScheduleConflictError(ScheduleServiceError):
    def __init__(self, message: str, conflicts: list[dict]):
        super().__init__("SCHEDULE_CONFLICT_DETECTED", message, status_code=409)
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
    Xác định tên ca học, giờ bắt đầu và giờ kết thúc từ payload.
    """
    shift_code = payload.get("shift")
    start_time_in = payload.get("start_time")
    end_time_in = payload.get("end_time")

    if shift_code and str(shift_code).lower() in DEFAULT_SHIFTS:
        shift_data = DEFAULT_SHIFTS[str(shift_code).lower()]
        shift_name = shift_data["name"]
        start_time = start_time_in or shift_data["start_time"]
        end_time = end_time_in or shift_data["end_time"]
        return shift_name, str(start_time), str(end_time)

    # Nếu người dùng truyền tên ca tuỳ ý
    shift_name = str(shift_code) if shift_code else "Tùy chỉnh"
    if not start_time_in or not end_time_in:
        # Nếu chỉ có shift_name dạng Ca 1, Ca 2
        norm = str(shift_code).strip().lower()
        if "ca 1" in norm or norm == "1":
            return DEFAULT_SHIFTS["shift_1"]["name"], DEFAULT_SHIFTS["shift_1"]["start_time"], DEFAULT_SHIFTS["shift_1"]["end_time"]
        elif "ca 2" in norm or norm == "2":
            return DEFAULT_SHIFTS["shift_2"]["name"], DEFAULT_SHIFTS["shift_2"]["start_time"], DEFAULT_SHIFTS["shift_2"]["end_time"]
        elif "ca 3" in norm or norm == "3":
            return DEFAULT_SHIFTS["shift_3"]["name"], DEFAULT_SHIFTS["shift_3"]["start_time"], DEFAULT_SHIFTS["shift_3"]["end_time"]
        elif "ca 4" in norm or norm == "4":
            return DEFAULT_SHIFTS["shift_4"]["name"], DEFAULT_SHIFTS["shift_4"]["start_time"], DEFAULT_SHIFTS["shift_4"]["end_time"]
        elif "ca 5" in norm or norm == "5":
            return DEFAULT_SHIFTS["shift_5"]["name"], DEFAULT_SHIFTS["shift_5"]["start_time"], DEFAULT_SHIFTS["shift_5"]["end_time"]
        raise ScheduleServiceError("INVALID_SHIFT_TIME", "Vui lòng chọn ca học hoặc nhập giờ bắt đầu và kết thúc hợp lệ.")

    return shift_name, str(start_time_in), str(end_time_in)


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
        raise ScheduleServiceError("INVALID_DAYS_OF_WEEK", "Vui lòng chọn ít nhất một thứ trong tuần để sinh lịch.")

    days_set = set()
    for d in raw_days:
        parsed_day = parse_day_of_week(d)
        if parsed_day is not None:
            days_set.add(parsed_day)

    if not days_set:
        raise ScheduleServiceError("INVALID_DAYS_OF_WEEK", "Danh sách thứ trong tuần không hợp lệ.")

    # 3. Kiểm tra ngày bắt đầu
    start_date_str = payload.get("start_date")
    if not start_date_str:
        raise ScheduleServiceError("START_DATE_REQUIRED", "Ngày bắt đầu không được để trống.")
    try:
        if isinstance(start_date_str, date):
            start_date_val = start_date_str
        else:
            start_date_val = datetime.strptime(str(start_date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ScheduleServiceError("INVALID_START_DATE", "Ngày bắt đầu phải theo định dạng YYYY-MM-DD.")

    # 4. Kiểm tra số buổi
    raw_total = payload.get("total_sessions")
    if raw_total is None:
        raise ScheduleServiceError("TOTAL_SESSIONS_REQUIRED", "Số buổi học không được để trống.")
    try:
        total_sessions = int(raw_total)
    except (ValueError, TypeError):
        raise ScheduleServiceError("INVALID_TOTAL_SESSIONS", "Số buổi học phải là số nguyên dương.")

    if total_sessions < 1 or total_sessions > 200:
        raise ScheduleServiceError("INVALID_TOTAL_SESSIONS", "Số buổi học phải từ 1 đến 200 buổi.")

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
    if not subject_id and class_subject_id:
        class_subjects = class_repository.get_class_subjects(class_id)
        for cs in class_subjects:
            if cs.id == class_subject_id:
                subject_id = cs.subject_id
                break

    lessons = []
    if subject_id:
        lessons = subject_session_repository.list_subject_sessions_by_subject(subject_id)

    # Thông tin phòng học & giảng viên mặc định (nếu có)
    room_id = payload.get("room_id")
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


def generate_schedule_service(class_id: str, payload: dict) -> dict:
    """
    API lưu thời khóa biểu chính thức vào cơ sở dữ liệu (SCRUM-224 & SCRUM-225).
    - SCRUM-224: Kiểm tra chống lặp / cờ overwrite.
    - SCRUM-225: Kiểm tra xung đột lịch giảng viên / phòng học. Trùng là lỗi chặn,
      không cho lưu, trừ khi Quản lý đào tạo xác nhận ghi đè (allow_conflict_override=True).
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    # Kiểm tra lịch hiện có
    existing_count = class_schedule_repository.count_schedules_by_class_id(class_id)
    overwrite = bool(payload.get("overwrite", False))

    if existing_count > 0 and not overwrite:
        raise ScheduleServiceError(
            "SCHEDULE_ALREADY_EXISTS",
            f"Lớp học đã có {existing_count} buổi học trong thời khóa biểu. Hãy bật tùy chọn ghi đè nếu muốn tạo lại lịch.",
            status_code=409,
        )

    # Sinh danh sách buổi học
    session_dicts, skipped = _build_schedule_sessions(class_id, payload)

    # Kiểm tra xung đột lịch tại thời điểm lưu (SCRUM-225 - AC 1, AC 2, AC 3)
    conflicts = detect_schedule_conflicts(
        session_dicts,
        exclude_class_id=class_id if overwrite else None,
    )

    allow_conflict_override = bool(payload.get("allow_conflict_override", False))
    if conflicts and not allow_conflict_override:
        # Trùng là lỗi chặn, không cho lưu trừ khi xác nhận ghi đè (AC 3)
        conflict_msg = (
            f"Phát hiện {len(conflicts)} xung đột lịch về giảng viên hoặc phòng học. "
            f"Hệ thống đã chặn lưu để tránh trùng giờ dạy. "
            f"Quản lý đào tạo cần xác nhận ghi đè để lưu lịch này."
        )
        raise ScheduleConflictError(conflict_msg, conflicts)

    if conflicts and allow_conflict_override:
        logger.warning(
            "Quản lý đào tạo đã xác nhận ghi đè %d xung đột lịch cho lớp %s (%s)",
            len(conflicts),
            class_id,
            class_obj.class_code,
        )

    # Nếu overwrite, xoá lịch cũ
    if existing_count > 0 and overwrite:
        class_schedule_repository.delete_schedules_by_class_id(class_id)

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

    saved_models = class_schedule_repository.insert_schedules_batch(schedule_models)

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
    }


def get_class_schedules_service(class_id: str) -> dict:
    """Lấy danh sách thời khóa biểu của một lớp học."""
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
    """Xóa toàn bộ thời khóa biểu của một lớp học."""
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

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
    """
    class_obj = class_repository.get_class_by_id(class_id)
    class_code = class_obj.class_code if class_obj else class_id

    # Định dạng ngày giờ hiển thị
    ld_str = schedule.learning_date.strftime("%d/%m/%Y") if hasattr(schedule.learning_date, "strftime") else str(schedule.learning_date)
    st_str = str(schedule.start_time)[:5]
    et_str = str(schedule.end_time)[:5]

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
            f"{f', phòng {schedule.room_id}' if schedule.room_id else ''}."
        )
    else:
        title = f"[ICTU] Thông báo cập nhật buổi học #{schedule.session_number} - Lớp {class_code}"
        message = (
            f"Buổi học #{schedule.session_number} ({schedule.topic}) của lớp {class_code} ngày {ld_str} "
            f"đã được cập nhật thông tin giảng viên / phòng học."
        )

    notifications_to_save: list[dict] = []
    seen_recipient_ids = set()

    # 1. Học viên ghi danh trong lớp
    students = class_schedule_repository.get_class_enrollment_recipients(class_id)
    for s in students:
        rec_id = s.get("id") or s.get("user_id")
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


def update_single_schedule_service(class_id: str, schedule_id: str, payload: dict) -> dict:
    """
    Sửa hoặc dời một buổi học đơn lẻ (SCRUM-226 AC 1, AC 3, AC 4):
    - Đổi được ngày, giờ, phòng, giảng viên dạy thay.
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

    str_start = str(new_start)[:8]
    str_end = str(new_end)[:8]
    if str_start >= str_end:
        raise ScheduleValidationError("Giờ bắt đầu phải trước giờ kết thúc buổi học.")

    new_room = payload.get("room_id") if "room_id" in payload else schedule.room_id
    new_instructor = payload.get("instructor_id") if "instructor_id" in payload else schedule.instructor_id
    new_topic = payload.get("topic") if "topic" in payload else schedule.topic
    allow_conflict_override = bool(payload.get("allow_conflict_override", False))

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
    time_changed = str(new_start)[:5] != str(schedule.start_time)[:5]
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

