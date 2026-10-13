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


def preview_schedule_service(class_id: str, payload: dict) -> dict:
    """
    API xem trước danh sách buổi học trước khi lưu (SCRUM-224 - AC 3).
    Không ghi bất kỳ dữ liệu nào vào cơ sở dữ liệu.
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", status_code=404)

    sessions, skipped = _build_schedule_sessions(class_id, payload)
    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "total_requested": payload.get("total_sessions"),
        "total_generated": len(sessions),
        "start_date": sessions[0]["learning_date"] if sessions else None,
        "end_date": sessions[-1]["learning_date"] if sessions else None,
        "schedules": sessions,
        "skipped_holidays": skipped,
    }


def generate_schedule_service(class_id: str, payload: dict) -> dict:
    """
    API lưu thời khóa biểu chính thức vào cơ sở dữ liệu (SCRUM-224 - AC 1, 2, 3, 4).
    Kiểm tra idempotency / chống lặp: nếu lớp đã có lịch mà không có flag overwrite=True thì chặn.
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
