"""
Service quáº£n lĂ½ Thá»i khĂ³a biá»ƒu lá»›p há»c (Schedule Service) - SCRUM-224.
- Sinh thá»i khĂ³a biá»ƒu tá»± Ä‘á»™ng theo máº«u láº·p (thá»© trong tuáº§n, ca há»c, ngĂ y báº¯t Ä‘áº§u, sá»‘ buá»•i).
- Tá»± Ä‘á»™ng bá» qua ngĂ y nghá»‰ lá»… Ä‘Ă£ khai bĂ¡o vĂ  sinh Ä‘á»§ sá»‘ buá»•i yĂªu cáº§u.
- Xem trÆ°á»›c thá»i khĂ³a biá»ƒu (preview) khĂ´ng lÆ°u DB.
- Gáº¯n tá»«ng buá»•i há»c vá»›i bĂ i há»c trong mĂ´n há»c.
- LÆ°u lá»‹ch há»c chĂ­nh thá»©c vá»›i kiá»ƒm tra idempotency / chá»‘ng láº·p.
"""

from datetime import date, datetime, timedelta, time, timezone
import logging
from typing import Any

from mysql.connector.errors import IntegrityError

from app.models.class_schedule import ClassSchedule
from app.repositories import (
    class_repository,
    class_schedule_repository,
    holiday_repository,
    subject_session_repository,
    schedule_repository,
)

from app.services.email_service import send_email

logger = logging.getLogger(__name__)

# Äá»‹nh nghÄ©a cĂ¡c ca há»c tiĂªu chuáº©n
DEFAULT_SHIFTS = {
    "shift_1": {"code": "shift_1", "name": "Ca 1 (07:30 - 09:30)", "start_time": "07:30:00", "end_time": "09:30:00"},
    "shift_2": {"code": "shift_2", "name": "Ca 2 (09:45 - 11:45)", "start_time": "09:45:00", "end_time": "11:45:00"},
    "shift_3": {"code": "shift_3", "name": "Ca 3 (13:30 - 15:30)", "start_time": "13:30:00", "end_time": "15:30:00"},
    "shift_4": {"code": "shift_4", "name": "Ca 4 (15:45 - 17:45)", "start_time": "15:45:00", "end_time": "17:45:00"},
    "shift_5": {"code": "shift_5", "name": "Ca 5 (18:00 - 20:30)", "start_time": "18:00:00", "end_time": "20:30:00"},
}

WEEKDAY_NAMES_VI = {
    0: "Thá»© 2",
    1: "Thá»© 3",
    2: "Thá»© 4",
    3: "Thá»© 5",
    4: "Thá»© 6",
    5: "Thá»© 7",
    6: "Chá»§ nháº­t",
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
    def __init__(self, message: str = "KhĂ´ng tĂ¬m tháº¥y buá»•i há»c."):
        super().__init__("SCHEDULE_NOT_FOUND", message, status_code=404)


class ScheduleAttendanceCheckedError(ScheduleServiceError):
    def __init__(
        self,
        message: str = "Không thể sửa hoặc hủy buổi học đã được điểm danh.",
    ):
        super().__init__(
            "SCHEDULE_ATTENDANCE_ALREADY_CHECKED",
            message,
            status_code=400,
        )
class ScheduleValidationError(ScheduleServiceError):
    def __init__(self, message: str, code: str = "INVALID_SCHEDULE_DATA", status_code: int = 400):
        super().__init__(code, message, status_code=status_code)


def parse_day_of_week(val: Any) -> int | None:
    """
    Chuáº©n hĂ³a thá»© trong tuáº§n sang sá»‘ nguyĂªn 0..6 (theo chuáº©n Python datetime.weekday: 0=Thá»© 2, 6=Chá»§ nháº­t).
    Há»— trá»£ cáº£ format tiáº¿ng Viá»‡t vĂ  ISO:
    - 2, "2", "thu 2", "thá»© 2", "t2", "mon", "monday" -> 0
    - 3, "3", "thu 3", "thá»© 3", "t3", "tue", "tuesday" -> 1
    - 4, "4", "thu 4", "thá»© 4", "t4", "wed", "wednesday" -> 2
    - 5, "5", "thu 5", "thá»© 5", "t5", "thu", "thursday" -> 3
    - 6, "6", "thu 6", "thá»© 6", "t6", "fri", "friday" -> 4
    - 7, "7", "thu 7", "thá»© 7", "t7", "sat", "saturday" -> 5
    - 8, "8", "cn", "chu nhat", "chá»§ nháº­t", "sun", "sunday", 0, "0" -> 6
    """
    if val is None:
        return None
    s = str(val).strip().lower()
    mapping = {
        "2": 0, "thu 2": 0, "thá»© 2": 0, "t2": 0, "mon": 0, "monday": 0,
        "3": 1, "thu 3": 1, "thá»© 3": 1, "t3": 1, "tue": 1, "tuesday": 1,
        "4": 2, "thu 4": 2, "thá»© 4": 2, "t4": 2, "wed": 2, "wednesday": 2,
        "5": 3, "thu 5": 3, "thá»© 5": 3, "t5": 3, "thu": 3, "thursday": 3,
        "6": 4, "thu 6": 4, "thá»© 6": 4, "t6": 4, "fri": 4, "friday": 4,
        "7": 5, "thu 7": 5, "thá»© 7": 5, "t7": 5, "sat": 5, "saturday": 5,
        "8": 6, "cn": 6, "chu nhat": 6, "chá»§ nháº­t": 6, "sun": 6, "sunday": 6,
        "0": 6, # Nhiá»u thÆ° viá»‡n dĂ¹ng 0 lĂ  Sunday
    }
    return mapping.get(s)


def resolve_shift_and_time(payload: dict) -> tuple[str, str, str]:
    """
    XĂ¡c Ä‘á»‹nh tĂªn ca há»c, giá» báº¯t Ä‘áº§u vĂ  giá» káº¿t thĂºc tá»« payload.
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

    # Náº¿u ngÆ°á»i dĂ¹ng truyá»n tĂªn ca tuá»³ Ă½
    shift_name = str(shift_code) if shift_code else "TĂ¹y chá»‰nh"
    if not start_time_in or not end_time_in:
        # Náº¿u chá»‰ cĂ³ shift_name dáº¡ng Ca 1, Ca 2
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
        raise ScheduleServiceError("INVALID_SHIFT_TIME", "Vui lĂ²ng chá»n ca há»c hoáº·c nháº­p giá» báº¯t Ä‘áº§u vĂ  káº¿t thĂºc há»£p lá»‡.")

    return shift_name, str(start_time_in), str(end_time_in)


def _build_schedule_sessions(
    class_id: str,
    payload: dict,
) -> tuple[list[dict], list[dict]]:
    """
    HĂ m lĂµi sinh danh sĂ¡ch cĂ¡c buá»•i há»c theo máº«u láº·p vĂ  bá» qua ngĂ y lá»… (AC 1, 2, 4).
    Tráº£ vá»: (generated_sessions, skipped_holidays)
    """
    # 1. Kiá»ƒm tra lá»›p há»c
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

    # 2. Kiá»ƒm tra cĂ¡c thá»© trong tuáº§n
    raw_days = payload.get("days_of_week")
    if not raw_days or not isinstance(raw_days, (list, tuple)):
        raise ScheduleServiceError("INVALID_DAYS_OF_WEEK", "Vui lĂ²ng chá»n Ă­t nháº¥t má»™t thá»© trong tuáº§n Ä‘á»ƒ sinh lá»‹ch.")

    days_set = set()
    for d in raw_days:
        parsed_day = parse_day_of_week(d)
        if parsed_day is not None:
            days_set.add(parsed_day)

    if not days_set:
        raise ScheduleServiceError("INVALID_DAYS_OF_WEEK", "Danh sĂ¡ch thá»© trong tuáº§n khĂ´ng há»£p lá»‡.")

    # 3. Kiá»ƒm tra ngĂ y báº¯t Ä‘áº§u
    start_date_str = payload.get("start_date")
    if not start_date_str:
        raise ScheduleServiceError("START_DATE_REQUIRED", "NgĂ y báº¯t Ä‘áº§u khĂ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng.")
    try:
        if isinstance(start_date_str, date):
            start_date_val = start_date_str
        else:
            start_date_val = datetime.strptime(str(start_date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ScheduleServiceError("INVALID_START_DATE", "NgĂ y báº¯t Ä‘áº§u pháº£i theo Ä‘á»‹nh dáº¡ng YYYY-MM-DD.")

    # 4. Kiá»ƒm tra sá»‘ buá»•i
    raw_total = payload.get("total_sessions")
    if raw_total is None:
        raise ScheduleServiceError("TOTAL_SESSIONS_REQUIRED", "Sá»‘ buá»•i há»c khĂ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng.")
    try:
        total_sessions = int(raw_total)
    except (ValueError, TypeError):
        raise ScheduleServiceError("INVALID_TOTAL_SESSIONS", "Sá»‘ buá»•i há»c pháº£i lĂ  sá»‘ nguyĂªn dÆ°Æ¡ng.")

    if total_sessions < 1 or total_sessions > 200:
        raise ScheduleServiceError("INVALID_TOTAL_SESSIONS", "Sá»‘ buá»•i há»c pháº£i tá»« 1 Ä‘áº¿n 200 buá»•i.")

    # 5. XĂ¡c Ä‘á»‹nh ca há»c & thá»i gian
    shift_name, start_time, end_time = resolve_shift_and_time(payload)

    # 6. Láº¥y danh sĂ¡ch ngĂ y nghá»‰ lá»… Ä‘Ă£ khai bĂ¡o (AC 2)
    holidays = holiday_repository.list_holidays()
    holiday_map = {}
    for h in holidays:
        h_date_str = h.holiday_date.strftime("%Y-%m-%d") if isinstance(h.holiday_date, (date, datetime)) else str(h.holiday_date)
        holiday_map[h_date_str] = h.name

    # 7. Láº¥y danh sĂ¡ch bĂ i há»c mĂ´n há»c (AC 4)
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

    # ThĂ´ng tin phĂ²ng há»c & giáº£ng viĂªn máº·c Ä‘á»‹nh (náº¿u cĂ³)
    room_id = payload.get("room_id")
    instructor_id = payload.get("instructor_id")

    # 8. VĂ²ng láº·p sinh lá»‹ch Ä‘á»§ sá»‘ buá»•i yĂªu cáº§u, bá» qua ngĂ y lá»…
    generated_sessions = []
    skipped_holidays = []
    curr_date = start_date_val
    generated_count = 0
    max_days_guard = 1500  # NgÄƒn cháº·n infinite loop

    days_checked = 0
    while generated_count < total_sessions and days_checked < max_days_guard:
        days_checked += 1
        curr_weekday = curr_date.weekday()
        curr_date_str = curr_date.strftime("%Y-%m-%d")

        if curr_weekday in days_set:
            if curr_date_str in holiday_map:
                # Bá» qua ngĂ y nghá»‰ lá»… nhÆ°ng khĂ´ng tÄƒng generated_count (AC 2)
                skipped_holidays.append({
                    "date": curr_date_str,
                    "holiday_name": holiday_map[curr_date_str],
                    "day_of_week": WEEKDAY_NAMES_VI.get(curr_weekday, ""),
                    "reason": f"Nghá»‰ lá»…: {holiday_map[curr_date_str]}",
                })
            else:
                generated_count += 1
                # Gáº¯n bĂ i há»c mĂ´n há»c (AC 4)
                topic = f"Buá»•i {generated_count}"
                subject_session_id = None
                if lessons:
                    if generated_count <= len(lessons):
                        matched_lesson = lessons[generated_count - 1]
                        topic = f"Buá»•i {generated_count}: {matched_lesson.topic}"
                        subject_session_id = matched_lesson.id
                    else:
                        topic = f"Buá»•i {generated_count}: Ă”n táº­p / Thá»±c hĂ nh"

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
    Kiá»ƒm tra xung Ä‘á»™t lá»‹ch giáº£ng viĂªn vĂ  phĂ²ng há»c (SCRUM-225 - AC 1, AC 2).
    - Kiá»ƒm tra giao nhau thá»i gian (start_1 < end_2 AND end_1 > start_2).
    - Kiá»ƒm tra xung Ä‘á»™t ná»™i bá»™ giá»¯a cĂ¡c buá»•i trong cĂ¹ng Ä‘á»£t táº¡o.
    - Kiá»ƒm tra xung Ä‘á»™t vá»›i cĂ¡c buá»•i há»c Ä‘Ă£ lÆ°u trong cÆ¡ sá»Ÿ dá»¯ liá»‡u.
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

    # 1. Kiá»ƒm tra xung Ä‘á»™t ná»™i bá»™ giá»¯a cĂ¡c buá»•i trong chĂ­nh Ä‘á»£t táº¡o
    n = len(sessions)
    for i in range(n):
        si = sessions[i]
        for j in range(i + 1, n):
            sj = sessions[j]
            if si["learning_date"] == sj["learning_date"]:
                # Kiá»ƒm tra giao nhau thá»i gian thá»±c táº¿
                if si["start_time"] < sj["end_time"] and si["end_time"] > sj["start_time"]:
                    # Xung Ä‘á»™t giáº£ng viĂªn
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
                            "conflicting_class_code": "Äá»£t táº¡o hiá»‡n táº¡i",
                            "conflicting_start_time": sj["start_time"],
                            "conflicting_end_time": sj["end_time"],
                            "message": (
                                f"Buá»•i #{si['session_number']} vĂ  Buá»•i #{sj['session_number']} "
                                f"bá»‹ trĂ¹ng Giáº£ng viĂªn trong cĂ¹ng khung giá» "
                                f"({si['learning_date']} {si['start_time']} - {si['end_time']})."
                            ),
                        })
                    # Xung Ä‘á»™t phĂ²ng há»c
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
                            "conflicting_class_code": "Äá»£t táº¡o hiá»‡n táº¡i",
                            "conflicting_start_time": sj["start_time"],
                            "conflicting_end_time": sj["end_time"],
                            "message": (
                                f"Buá»•i #{si['session_number']} vĂ  Buá»•i #{sj['session_number']} "
                                f"bá»‹ trĂ¹ng PhĂ²ng há»c ({si['room_id']}) trong cĂ¹ng khung giá» "
                                f"({si['learning_date']} {si['start_time']} - {si['end_time']})."
                            ),
                        })

    # 2. Kiá»ƒm tra xung Ä‘á»™t vá»›i lá»‹ch Ä‘Ă£ lÆ°u trong database
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
                # Xung Ä‘á»™t giáº£ng viĂªn
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
                            f"Buá»•i #{s['session_number']} ({s['learning_date']} {s['start_time']} - {s['end_time']}) "
                            f"bá»‹ trĂ¹ng Giáº£ng viĂªn ({db_c.get('instructor_name') or inst_id}) "
                            f"vá»›i Buá»•i #{db_c['session_number']} cá»§a Lá»›p {db_c['class_code']} "
                            f"({db_c['start_time']} - {db_c['end_time']})."
                        ),
                    })
                # Xung Ä‘á»™t phĂ²ng há»c
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
                            f"Buá»•i #{s['session_number']} ({s['learning_date']} {s['start_time']} - {s['end_time']}) "
                            f"bá»‹ trĂ¹ng PhĂ²ng há»c ({r_id}) "
                            f"vá»›i Buá»•i #{db_c['session_number']} cá»§a Lá»›p {db_c['class_code']} "
                            f"({db_c['start_time']} - {db_c['end_time']})."
                        ),
                    })

    return conflicts


def preview_schedule_service(class_id: str, payload: dict) -> dict:
    """
    API xem trÆ°á»›c danh sĂ¡ch buá»•i há»c trÆ°á»›c khi lÆ°u (SCRUM-224 - AC 3, SCRUM-225 - AC 1, AC 2).
    KhĂ´ng ghi báº¥t ká»³ dá»¯ liá»‡u nĂ o vĂ o cÆ¡ sá»Ÿ dá»¯ liá»‡u.
    Cáº£nh bĂ¡o rĂµ rĂ ng cĂ¡c buá»•i Ä‘ang xung Ä‘á»™t giáº£ng viĂªn hoáº·c phĂ²ng há»c.
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

    sessions, skipped = _build_schedule_sessions(class_id, payload)

    # Kiá»ƒm tra xung Ä‘á»™t (SCRUM-225)
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
    API lÆ°u thá»i khĂ³a biá»ƒu chĂ­nh thá»©c vĂ o cÆ¡ sá»Ÿ dá»¯ liá»‡u (SCRUM-224 & SCRUM-225).
    - SCRUM-224: Kiá»ƒm tra chá»‘ng láº·p / cá» overwrite.
    - SCRUM-225: Kiá»ƒm tra xung Ä‘á»™t lá»‹ch giáº£ng viĂªn / phĂ²ng há»c. TrĂ¹ng lĂ  lá»—i cháº·n,
      khĂ´ng cho lÆ°u, trá»« khi Quáº£n lĂ½ Ä‘Ă o táº¡o xĂ¡c nháº­n ghi Ä‘Ă¨ (allow_conflict_override=True).
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

    # Kiá»ƒm tra lá»‹ch hiá»‡n cĂ³
    existing_count = class_schedule_repository.count_schedules_by_class_id(class_id)
    overwrite = bool(payload.get("overwrite", False))

    if existing_count > 0 and not overwrite:
        raise ScheduleServiceError(
            "SCHEDULE_ALREADY_EXISTS",
            f"Lá»›p há»c Ä‘Ă£ cĂ³ {existing_count} buá»•i há»c trong thá»i khĂ³a biá»ƒu. HĂ£y báº­t tĂ¹y chá»n ghi Ä‘Ă¨ náº¿u muá»‘n táº¡o láº¡i lá»‹ch.",
            status_code=409,
        )

    # Sinh danh sĂ¡ch buá»•i há»c
    session_dicts, skipped = _build_schedule_sessions(class_id, payload)

    # Kiá»ƒm tra xung Ä‘á»™t lá»‹ch táº¡i thá»i Ä‘iá»ƒm lÆ°u (SCRUM-225 - AC 1, AC 2, AC 3)
    conflicts = detect_schedule_conflicts(
        session_dicts,
        exclude_class_id=class_id if overwrite else None,
    )

    allow_conflict_override = bool(payload.get("allow_conflict_override", False))
    if conflicts and not allow_conflict_override:
        # TrĂ¹ng lĂ  lá»—i cháº·n, khĂ´ng cho lÆ°u trá»« khi xĂ¡c nháº­n ghi Ä‘Ă¨ (AC 3)
        conflict_msg = (
            f"PhĂ¡t hiá»‡n {len(conflicts)} xung Ä‘á»™t lá»‹ch vá» giáº£ng viĂªn hoáº·c phĂ²ng há»c. "
            f"Há»‡ thá»‘ng Ä‘Ă£ cháº·n lÆ°u Ä‘á»ƒ trĂ¡nh trĂ¹ng giá» dáº¡y. "
            f"Quáº£n lĂ½ Ä‘Ă o táº¡o cáº§n xĂ¡c nháº­n ghi Ä‘Ă¨ Ä‘á»ƒ lÆ°u lá»‹ch nĂ y."
        )
        raise ScheduleConflictError(conflict_msg, conflicts)

    if conflicts and allow_conflict_override:
        logger.warning(
            "Quáº£n lĂ½ Ä‘Ă o táº¡o Ä‘Ă£ xĂ¡c nháº­n ghi Ä‘Ă¨ %d xung Ä‘á»™t lá»‹ch cho lá»›p %s (%s)",
            len(conflicts),
            class_id,
            class_obj.class_code,
        )

    # Náº¿u overwrite, xoĂ¡ lá»‹ch cÅ©
    if existing_count > 0 and overwrite:
        class_schedule_repository.delete_schedules_by_class_id(class_id)

    # Chuáº©n bá»‹ model ClassSchedule Ä‘á»ƒ lÆ°u batch
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
    """Láº¥y danh sĂ¡ch thá»i khĂ³a biá»ƒu cá»§a má»™t lá»›p há»c."""
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

    schedules = class_schedule_repository.list_schedules_by_class_id(class_id)
    return {
        "class_id": class_id,
        "class_code": class_obj.class_code,
        "total": len(schedules),
        "schedules": [s.to_dict() for s in schedules],
    }


def delete_class_schedules_service(class_id: str) -> dict:
    """XĂ³a toĂ n bá»™ thá»i khĂ³a biá»ƒu cá»§a má»™t lá»›p há»c."""
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

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
    Gá»­i thĂ´ng bĂ¡o thay Ä‘á»•i buá»•i há»c tá»›i giáº£ng viĂªn vĂ  toĂ n bá»™ há»c viĂªn cá»§a lá»›p (SCRUM-226 AC 3).
    LÆ°u báº£n ghi vĂ o schedule_notifications vĂ  ghi log nghiá»‡p vá»¥.
    """
    class_obj = class_repository.get_class_by_id(class_id)
    class_code = class_obj.class_code if class_obj else class_id

    # Äá»‹nh dáº¡ng ngĂ y giá» hiá»ƒn thá»‹
    ld_str = schedule.learning_date.strftime("%d/%m/%Y") if hasattr(schedule.learning_date, "strftime") else str(schedule.learning_date)
    st_str = str(schedule.start_time)[:5]
    et_str = str(schedule.end_time)[:5]

    if change_type == "cancelled":
        title = f"[ICTU] ThĂ´ng bĂ¡o há»§y buá»•i há»c #{schedule.session_number} - Lá»›p {class_code}"
        message = (
            f"Buá»•i há»c #{schedule.session_number} ({schedule.topic}) cá»§a lá»›p {class_code} "
            f"dá»± kiáº¿n ngĂ y {ld_str} ({st_str} - {et_str}) Ä‘Ă£ bá»‹ há»§y.\n"
            f"LĂ½ do: {cancellation_reason or schedule.cancellation_reason or 'KhĂ´ng cĂ³ lĂ½ do cá»¥ thá»ƒ'}."
        )
    elif change_type == "rescheduled":
        title = f"[ICTU] ThĂ´ng bĂ¡o dá»i lá»‹ch buá»•i há»c #{schedule.session_number} - Lá»›p {class_code}"
        message = (
            f"Buá»•i há»c #{schedule.session_number} ({schedule.topic}) cá»§a lá»›p {class_code} "
            f"Ä‘Ă£ Ä‘Æ°á»£c dá»i sang ngĂ y {ld_str}, khung giá» {st_str} - {et_str}"
            f"{f', phĂ²ng {schedule.room_id}' if schedule.room_id else ''}."
        )
    else:
        title = f"[ICTU] ThĂ´ng bĂ¡o cáº­p nháº­t buá»•i há»c #{schedule.session_number} - Lá»›p {class_code}"
        message = (
            f"Buá»•i há»c #{schedule.session_number} ({schedule.topic}) cá»§a lá»›p {class_code} ngĂ y {ld_str} "
            f"Ä‘Ă£ Ä‘Æ°á»£c cáº­p nháº­t thĂ´ng tin giáº£ng viĂªn / phĂ²ng há»c."
        )

    notifications_to_save: list[dict] = []
    seen_recipient_ids = set()

    # 1. Há»c viĂªn ghi danh trong lá»›p
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
                "recipient_name": s.get("full_name") or "Há»c viĂªn",
                "recipient_email": s.get("email"),
                "change_type": change_type,
                "title": title,
                "message": message,
            })

    # 2. Giáº£ng viĂªn phá»¥ trĂ¡ch hiá»‡n táº¡i
    if schedule.instructor_id and schedule.instructor_id not in seen_recipient_ids:
        seen_recipient_ids.add(schedule.instructor_id)
        inst_info = class_schedule_repository.get_user_info_by_id(schedule.instructor_id)
        notifications_to_save.append({
            "schedule_id": schedule.id,
            "class_id": class_id,
            "recipient_type": "instructor",
            "recipient_id": schedule.instructor_id,
            "recipient_name": inst_info.get("name") if inst_info else "Giáº£ng viĂªn",
            "recipient_email": inst_info.get("email") if inst_info else None,
            "change_type": change_type,
            "title": title,
            "message": message,
        })

    # 3. Giáº£ng viĂªn cÅ© (náº¿u thay Ä‘á»•i giáº£ng viĂªn dáº¡y thay)
    if old_instructor_id and old_instructor_id != schedule.instructor_id and old_instructor_id not in seen_recipient_ids:
        seen_recipient_ids.add(old_instructor_id)
        old_inst_info = class_schedule_repository.get_user_info_by_id(old_instructor_id)
        notifications_to_save.append({
            "schedule_id": schedule.id,
            "class_id": class_id,
            "recipient_type": "instructor",
            "recipient_id": old_instructor_id,
            "recipient_name": old_inst_info.get("name") if old_inst_info else "Giáº£ng viĂªn",
            "recipient_email": old_inst_info.get("email") if old_inst_info else None,
            "change_type": change_type,
            "title": title,
            "message": message + " (Báº¡n Ä‘Ă£ Ä‘Æ°á»£c gá»¡ khá»i buá»•i há»c nĂ y do cĂ³ giáº£ng viĂªn dáº¡y thay).",
        })

    if notifications_to_save:
        class_schedule_repository.insert_schedule_notifications_batch(notifications_to_save)
        logger.info(
            "ÄĂ£ phĂ¡t %d thĂ´ng bĂ¡o thay Ä‘á»•i TKB (loáº¡i: %s) cho lá»›p %s buá»•i #%s",
            len(notifications_to_save),
            change_type,
            class_code,
            schedule.session_number,
        )

    return len(notifications_to_save)


def update_single_schedule_service(class_id: str, schedule_id: str, payload: dict) -> dict:
    """
    Sá»­a hoáº·c dá»i má»™t buá»•i há»c Ä‘Æ¡n láº» (SCRUM-226 AC 1, AC 3, AC 4):
    - Äá»•i Ä‘Æ°á»£c ngĂ y, giá», phĂ²ng, giáº£ng viĂªn dáº¡y thay.
    - Cháº·n sá»­a buá»•i há»c Ä‘Ă£ Ä‘iá»ƒm danh (AC 4).
    - TĂ¡i sá»­ dá»¥ng kiá»ƒm tra xung Ä‘á»™t cá»§a SCRUM-225 (loáº¡i trá»« chĂ­nh buá»•i Ä‘ang sá»­a).
    - Gá»­i thĂ´ng bĂ¡o tá»›i há»c viĂªn vĂ  giáº£ng viĂªn cá»§a lá»›p (AC 3).
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

    schedule = class_schedule_repository.get_schedule_by_id(schedule_id)
    if not schedule or str(schedule.class_id) != str(class_id):
        raise ScheduleNotFoundError("Kh?ng t?m th?y bu?i h?c trong l?p n?y.")

    # AC 4: Block edits to schedules with recorded attendance.
    if schedule.attendance_checked:
        raise ScheduleAttendanceCheckedError()

    # Thu tháº­p dá»¯ liá»‡u cáº­p nháº­t
    new_date = payload.get("learning_date") or schedule.learning_date
    if isinstance(new_date, str):
        try:
            datetime.strptime(new_date, "%Y-%m-%d")
        except ValueError:
            raise ScheduleValidationError("Äá»‹nh dáº¡ng ngĂ y há»c khĂ´ng há»£p lá»‡ (cáº§n YYYY-MM-DD).")

    new_shift = payload.get("shift") if "shift" in payload else schedule.shift
    new_start = payload.get("start_time") or schedule.start_time
    new_end = payload.get("end_time") or schedule.end_time

    if new_shift and new_shift in DEFAULT_SHIFTS and ("start_time" not in payload or not payload["start_time"]):
        new_start = DEFAULT_SHIFTS[new_shift]["start_time"]
        new_end = DEFAULT_SHIFTS[new_shift]["end_time"]

    str_start = str(new_start)[:8]
    str_end = str(new_end)[:8]
    if str_start >= str_end:
        raise ScheduleValidationError("Gi? b?t ??u ph?i tr??c gi? k?t th?c bu?i h?c.")

    new_room = payload.get("room_id") if "room_id" in payload else schedule.room_id
    new_instructor = payload.get("instructor_id") if "instructor_id" in payload else schedule.instructor_id
    new_topic = payload.get("topic") if "topic" in payload else schedule.topic
    allow_conflict_override = bool(payload.get("allow_conflict_override", False))

    # TĂ¡i sá»­ dá»¥ng kiá»ƒm tra xung Ä‘á»™t SCRUM-225 (loáº¡i trá»« chĂ­nh buá»•i Ä‘ang sá»­a)
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
            f"PhĂ¡t hiá»‡n xung Ä‘á»™t lá»‹ch cho buá»•i há»c #{schedule.session_number}. Cáº§n Quáº£n lĂ½ Ä‘Ă o táº¡o xĂ¡c nháº­n ghi Ä‘Ă¨.",
            conflicts,
        )

    # XĂ¡c Ä‘á»‹nh tráº¡ng thĂ¡i má»›i: náº¿u ngĂ y hoáº·c giá» thay Ä‘á»•i thĂ¬ lĂ  'rescheduled'
    date_changed = str(new_date) != str(schedule.learning_date)
    time_changed = str(new_start)[:5] != str(schedule.start_time)[:5]
    if date_changed or time_changed:
        change_type = "rescheduled"
    else:
        change_type = "updated"

    old_instructor = schedule.instructor_id

    # Cáº­p nháº­t thĂ´ng tin
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

    # Gá»­i thĂ´ng bĂ¡o tá»›i há»c viĂªn vĂ  giáº£ng viĂªn (AC 3)
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
    Há»§y má»™t buá»•i há»c Ä‘Æ¡n láº» (SCRUM-226 AC 2, AC 3, AC 4):
    - Báº¯t buá»™c nháº­p lĂ½ do há»§y (cancellation_reason) (AC 2).
    - Cháº·n há»§y náº¿u buá»•i há»c Ä‘Ă£ Ä‘iá»ƒm danh (AC 4).
    - Há»c viĂªn vĂ  giáº£ng viĂªn cá»§a lá»›p nháº­n Ä‘Æ°á»£c thĂ´ng bĂ¡o thay Ä‘á»•i (AC 3).
    """
    class_obj = class_repository.get_class_by_id(class_id)
    if not class_obj:
        raise ScheduleServiceError("CLASS_NOT_FOUND", "Kh?ng t?m th?y l?p h?c.", status_code=404)

    schedule = class_schedule_repository.get_schedule_by_id(schedule_id)
    if not schedule or str(schedule.class_id) != str(class_id):
        raise ScheduleNotFoundError("Kh?ng t?m th?y bu?i h?c trong l?p n?y.")

    # AC 4: KhĂ´ng há»§y Ä‘Æ°á»£c buá»•i Ä‘Ă£ Ä‘iá»ƒm danh
    if schedule.attendance_checked:
        raise ScheduleAttendanceCheckedError()

    # AC 2: Báº¯t buá»™c nháº­p lĂ½ do há»§y
    reason = (payload.get("reason") or payload.get("cancellation_reason") or "").strip()
    if not reason:
        raise ScheduleValidationError(
            "Lý do hủy buổi học là bắt buộc.",
            code="MISSING_CANCELLATION_REASON",
            status_code=400,
        )

    schedule.status = "cancelled"
    schedule.cancellation_reason = reason

    updated_schedule = class_schedule_repository.update_schedule_item(schedule)

    # AC 3: Gá»­i thĂ´ng bĂ¡o há»§y tá»›i há»c viĂªn vĂ  giáº£ng viĂªn
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
    """Láº¥y danh sĂ¡ch thĂ´ng bĂ¡o thay Ä‘á»•i lá»‹ch há»c Ä‘Ă£ phĂ¡t (SCRUM-226 AC 3)."""
    return class_schedule_repository.list_schedule_notifications(schedule_id=schedule_id, class_id=class_id)


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
