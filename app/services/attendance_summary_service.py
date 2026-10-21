"""
Service xử lý nghiệp vụ Bảng chuyên cần tổng hợp theo lớp học (SCRUM-256).
Hỗ trợ:
- AC1: Ma trận học viên theo buổi, ô màu theo trạng thái.
- AC2: Cột tổng số buổi vắng và tỷ lệ chuyên cần theo phần trăm.
- AC3: Sắp xếp theo tỷ lệ chuyên cần tăng dần (server-side, null đặt cuối, tie-break ổn định).
"""

from datetime import date, datetime, time, timedelta, timezone
import math
from typing import Any, Optional

from app.models.session_attendance import (
    ATTENDANCE_STATUSES,
    ATTENDANCE_STATUS_LABELS,
)
from app.repositories import attendance_summary_repository
from app.services.attendance_service import (
    AttendanceServiceError,
    ForbiddenAttendanceAccessError,
    VIETNAM_TZ,
    get_vietnam_today,
)

CELL_STATUS_CONFIG = {
    "present": {
        "status_label": "Có mặt",
        "symbol": "P",
        "color_token": "green",
    },
    "late": {
        "status_label": "Đi muộn",
        "symbol": "L",
        "color_token": "orange",
    },
    "excused": {
        "status_label": "Vắng có phép",
        "symbol": "E",
        "color_token": "blue",
    },
    "unexcused": {
        "status_label": "Vắng không phép",
        "symbol": "U",
        "color_token": "red",
    },
    "not_recorded": {
        "status_label": "Chưa điểm danh",
        "symbol": "?",
        "color_token": "grey",
    },
    "future": {
        "status_label": "Chưa diễn ra",
        "symbol": "—",
        "color_token": "neutral",
    },
    "not_applicable": {
        "status_label": "Không áp dụng",
        "symbol": "—",
        "color_token": "subtle",
    },
    "cancelled": {
        "status_label": "Buổi học đã hủy",
        "symbol": "✕",
        "color_token": "muted",
    },
}


def _parse_time_value(val: Any) -> Optional[time]:
    """Chuyển đổi linh hoạt time/timedelta/str từ database sang đối tượng time chuẩn."""
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, timedelta):
        total_seconds = int(val.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return time(hours, minutes, seconds)
    if isinstance(val, str):
        parts = val.strip().split(":")
        if len(parts) >= 2:
            try:
                h = int(parts[0])
                m = int(parts[1])
                s = int(parts[2]) if len(parts) > 2 else 0
                return time(h, m, s)
            except ValueError:
                return None
    return None


def get_class_attendance_summary(
    class_id: str,
    current_user_id: str,
    current_user_roles: list[str],
    page: int = 1,
    page_size: int = 20,
    search_query: Optional[str] = None,
    sort_by: str = "student_code",
    sort_order: str = "asc",
    subject_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Truy xuất Bảng chuyên cần tổng hợp của lớp học (SCRUM-256).
    
    1. Kiểm tra lớp học tồn tại (404 nếu không tìm thấy).
    2. Phân quyền (RBAC):
       - Quản lý đào tạo (training_manager): Xem được toàn bộ các lớp.
       - Giảng viên (trainer): Chỉ được xem các lớp mình được phân công giảng dạy (class_subject_instructors hoặc class_schedules).
       - Các vai trò khác (trainee, admin thuần túy, v.v.): 403 Forbidden.
    3. Trả về:
       - Thông tin lớp và môn học.
       - Danh sách buổi học (AC1: ma trận theo buổi, phân biệt buổi cùng ngày bằng schedule_id và giờ học).
       - Danh sách học viên và ma trận trạng thái (AC1).
       - Cột tổng số buổi vắng và tỷ lệ chuyên cần % (AC2).
       - Sắp xếp phía server bao gồm theo tỷ lệ tăng dần (AC3).
       - Phân trang server-side và quy tắc tính toán.
    """
    # 1. Kiểm tra tồn tại lớp học
    class_info = attendance_summary_repository.get_class_details(class_id)
    if not class_info:
        raise AttendanceServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học yêu cầu.", status_code=404)

    # 2. Phân quyền
    normalized_roles = [r.lower().strip() for r in current_user_roles if isinstance(r, str)]
    is_training_manager = "training_manager" in normalized_roles
    is_trainer = "trainer" in normalized_roles

    if not is_training_manager and not is_trainer:
        raise ForbiddenAttendanceAccessError(
            "Tài khoản của bạn không có quyền xem bảng chuyên cần tổng hợp của lớp học."
        )

    if is_trainer and not is_training_manager:
        if not attendance_summary_repository.is_trainer_assigned_to_class(current_user_id, class_id):
            raise ForbiddenAttendanceAccessError(
                "Bạn không được phân công phụ trách lớp học này."
            )

    # 3. Lấy thời gian hiện tại theo múi giờ nghiệp vụ Việt Nam (UTC+7)
    now_vn = datetime.now(VIETNAM_TZ)
    today_vn = now_vn.date()
    now_time = now_vn.time()

    # 4. Lấy danh sách buổi học thực tế của lớp (nguồn cột ma trận)
    schedules = attendance_summary_repository.get_class_schedules_for_summary(class_id, subject_id=subject_id)

    # Xử lý metadata cho từng buổi học
    session_columns: list[dict[str, Any]] = []
    for s in schedules:
        learning_date = s["learning_date"]
        if isinstance(learning_date, str):
            learning_date = date.fromisoformat(learning_date)

        end_time_val = _parse_time_value(s.get("end_time"))
        is_cancelled = (s["status"] == "cancelled")
        is_past = (learning_date < today_vn)
        is_future = (learning_date > today_vn)
        is_today = (learning_date == today_vn)

        if is_past:
            has_ended = True
        elif is_future:
            has_ended = False
        else:
            # is_today
            if s.get("attendance_checked"):
                has_ended = True
            elif end_time_val:
                has_ended = (now_time >= end_time_val)
            else:
                has_ended = False

        s["_has_ended"] = has_ended
        s["_is_future"] = is_future
        s["_is_cancelled"] = is_cancelled
        s["_learning_date_val"] = learning_date

        session_columns.append({
            "schedule_id": s["id"],
            "session_number": s["session_number"],
            "topic": s["topic"],
            "learning_date": s["learning_date_str"],
            "shift": s["shift"],
            "start_time": s["start_time_str"],
            "end_time": s["end_time_str"],
            "subject_id": s["subject_id"],
            "subject_name": s["subject_name"],
            "subject_code": s["subject_code"],
            "room_name": s["room_name"],
            "instructor_name": s["instructor_name"],
            "status": s["status"],
            "attendance_checked": s["attendance_checked"],
            "has_ended": has_ended,
            "is_future": is_future,
            "is_cancelled": is_cancelled,
        })

    # 5. Lấy danh sách học viên và tất cả bản ghi điểm danh của lớp
    students = attendance_summary_repository.get_enrolled_and_history_students(class_id)
    all_attendances = attendance_summary_repository.get_class_attendances(class_id)
    att_map = {(r["schedule_id"], r["student_id"]): r for r in all_attendances}

    # 6. Tính toán ma trận và các cột tổng (AC1, AC2) cho toàn bộ học viên
    student_records: list[dict[str, Any]] = []

    for stud in students:
        s_id = stud["student_id"]
        enrolled_date = stud.get("enrolled_date")
        lifecycle_status = stud.get("lifecycle_status")
        effective_date_val = stud.get("effective_date_val")

        present_count = 0
        late_count = 0
        excused_count = 0
        unexcused_count = 0
        unrecorded_ended_count = 0

        session_statuses: dict[str, dict[str, Any]] = {}

        for s in schedules:
            sched_id = s["id"]
            learning_date_val = s["_learning_date_val"]
            has_ended = s["_has_ended"]
            is_future = s["_is_future"]
            is_cancelled = s["_is_cancelled"]

            # Kiểm tra tính áp dụng của học viên đối với buổi học
            is_eligible = True
            if enrolled_date and enrolled_date > learning_date_val:
                is_eligible = False
            elif lifecycle_status in ("reserved", "transferred", "dropped") and effective_date_val:
                if learning_date_val >= effective_date_val:
                    is_eligible = False

            # Bản ghi điểm danh thực tế nếu có
            sa = att_map.get((sched_id, s_id))

            if is_cancelled:
                cfg = CELL_STATUS_CONFIG["cancelled"]
                session_statuses[sched_id] = {
                    "status": "cancelled",
                    "status_label": cfg["status_label"],
                    "symbol": cfg["symbol"],
                    "color_token": cfg["color_token"],
                    "notes": s.get("cancellation_reason") or "Buổi học đã bị hủy",
                    "is_eligible": is_eligible,
                }
            elif not is_eligible and not sa:
                # Học viên không thuộc đối tượng tham gia buổi đó và chưa từng có điểm danh
                cfg = CELL_STATUS_CONFIG["not_applicable"]
                session_statuses[sched_id] = {
                    "status": "not_applicable",
                    "status_label": cfg["status_label"],
                    "symbol": cfg["symbol"],
                    "color_token": cfg["color_token"],
                    "notes": "Không áp dụng cho học viên này",
                    "is_eligible": False,
                }
            elif sa:
                # Có bản ghi điểm danh
                st = sa["status"]
                cfg = CELL_STATUS_CONFIG.get(st, {
                    "status_label": st,
                    "symbol": st[:1].upper(),
                    "color_token": "grey",
                })

                session_statuses[sched_id] = {
                    "status": st,
                    "status_label": cfg["status_label"],
                    "symbol": cfg["symbol"],
                    "color_token": cfg["color_token"],
                    "notes": sa.get("notes"),
                    "is_eligible": is_eligible,
                }

                # Quy tắc thống kê AC2: Chỉ tính vào mẫu số D và vắng khi buổi ĐÃ KẾT THÚC
                if has_ended:
                    if st == "present":
                        present_count += 1
                    elif st == "late":
                        late_count += 1
                    elif st == "excused":
                        excused_count += 1
                    elif st == "unexcused":
                        unexcused_count += 1
                else:
                    # Buổi chưa kết thúc (tương lai) nhưng có đơn xin nghỉ đã duyệt trước
                    session_statuses[sched_id]["is_pre_approved"] = True
            else:
                # Chưa có bản ghi điểm danh
                if has_ended:
                    cfg = CELL_STATUS_CONFIG["not_recorded"]
                    session_statuses[sched_id] = {
                        "status": "not_recorded",
                        "status_label": cfg["status_label"],
                        "symbol": cfg["symbol"],
                        "color_token": cfg["color_token"],
                        "notes": "Buổi học đã kết thúc nhưng chưa điểm danh",
                        "is_eligible": is_eligible,
                    }
                    unrecorded_ended_count += 1
                else:
                    cfg = CELL_STATUS_CONFIG["future"]
                    session_statuses[sched_id] = {
                        "status": "future",
                        "status_label": cfg["status_label"],
                        "symbol": cfg["symbol"],
                        "color_token": cfg["color_token"],
                        "notes": "Buổi học chưa diễn ra",
                        "is_eligible": is_eligible,
                    }

        # Tính toán công thức AC2
        attended_count = present_count + late_count
        total_absent = excused_count + unexcused_count
        valid_sessions_count = attended_count + total_absent  # D = P + L + E + U

        if valid_sessions_count > 0:
            attendance_rate_raw = (attended_count / valid_sessions_count) * 100.0
            attendance_rate = round(attendance_rate_raw, 2)
            attendance_rate_formatted = f"{attendance_rate:.2f}".rstrip("0").rstrip(".") + "%"
        else:
            attendance_rate_raw = None
            attendance_rate = None
            attendance_rate_formatted = "—"

        student_records.append({
            "student_id": s_id,
            "student_code": stud["student_code"],
            "full_name": stud["full_name"],
            "email": stud.get("email"),
            "phone": stud.get("phone"),
            "enrollment_status": stud.get("enrollment_status"),
            "lifecycle_status": lifecycle_status,
            "summary": {
                "present_count": present_count,
                "late_count": late_count,
                "excused_count": excused_count,
                "unexcused_count": unexcused_count,
                "attended_count": attended_count,
                "valid_sessions_count": valid_sessions_count,
                "total_absent": total_absent,
                "attendance_rate": attendance_rate,
                "attendance_rate_raw": attendance_rate_raw,
                "attendance_rate_formatted": attendance_rate_formatted,
                "unrecorded_ended_count": unrecorded_ended_count,
            },
            "_session_statuses": session_statuses,
        })

    # 7. Bộ lọc tìm kiếm học viên (theo mã, họ tên hoặc ID)
    filtered_students = student_records
    if search_query:
        q = search_query.strip().lower()
        filtered_students = [
            st for st in student_records
            if (st["student_code"] and q in st["student_code"].lower())
            or (st["full_name"] and q in st["full_name"].lower())
            or (st["student_id"] and q in st["student_id"].lower())
        ]

    # 8. Sắp xếp phía Server (AC3)
    sort_by_norm = (sort_by or "student_code").strip().lower()
    sort_order_norm = (sort_order or "asc").strip().lower()
    is_desc = (sort_order_norm == "desc")

    if sort_by_norm == "attendance_rate":
        # Sắp xếp theo tỷ lệ chuyên cần (AC3):
        # - Tăng dần (asc - "Chuyên cần thấp nhất trước"): 0% đứng đầu, các tỷ lệ tăng dần, null đặt CUỐI CÙNG.
        # - Khóa phụ ổn định: student_code ASC, student_id ASC.
        if not is_desc:
            def sort_key(st):
                rate = st["summary"]["attendance_rate_raw"]
                is_null = 1 if rate is None else 0
                val = rate if rate is not None else 0.0
                return (is_null, val, st["student_code"] or "", st["student_id"])
        else:
            def sort_key(st):
                rate = st["summary"]["attendance_rate_raw"]
                is_null = 1 if rate is None else 0
                val = -rate if rate is not None else 0.0
                return (is_null, val, st["student_code"] or "", st["student_id"])
        filtered_students.sort(key=sort_key)
    elif sort_by_norm == "total_absent":
        if is_desc:
            filtered_students.sort(
                key=lambda st: (-st["summary"]["total_absent"], st["student_code"] or "", st["student_id"])
            )
        else:
            filtered_students.sort(
                key=lambda st: (st["summary"]["total_absent"], st["student_code"] or "", st["student_id"])
            )
    elif sort_by_norm == "full_name":
        filtered_students.sort(
            key=lambda st: (st["full_name"] or "", st["student_code"] or "", st["student_id"]),
            reverse=is_desc,
        )
    else:
        # Default: student_code
        filtered_students.sort(
            key=lambda st: (st["student_code"] or "", st["student_id"]),
            reverse=is_desc,
        )

    # 9. Phân trang phía Server
    total_items = len(filtered_students)
    page_num = max(1, int(page or 1))
    page_sz = min(max(1, int(page_size or 20)), 100)
    total_pages = max(1, math.ceil(total_items / page_sz)) if total_items > 0 else 1

    start_idx = (page_num - 1) * page_sz
    end_idx = start_idx + page_sz
    paged_slice = filtered_students[start_idx:end_idx]

    # Chuẩn bị danh sách trả về, chỉ đính kèm session_statuses cho học viên thuộc trang hiện tại
    result_students: list[dict[str, Any]] = []
    for st in paged_slice:
        result_students.append({
            "student_id": st["student_id"],
            "student_code": st["student_code"],
            "full_name": st["full_name"],
            "email": st["email"],
            "phone": st["phone"],
            "enrollment_status": st["enrollment_status"],
            "lifecycle_status": st["lifecycle_status"],
            "summary": {
                "present_count": st["summary"]["present_count"],
                "late_count": st["summary"]["late_count"],
                "excused_count": st["summary"]["excused_count"],
                "unexcused_count": st["summary"]["unexcused_count"],
                "attended_count": st["summary"]["attended_count"],
                "valid_sessions_count": st["summary"]["valid_sessions_count"],
                "total_absent": st["summary"]["total_absent"],
                "attendance_rate": st["summary"]["attendance_rate"],
                "attendance_rate_formatted": st["summary"]["attendance_rate_formatted"],
                "unrecorded_ended_count": st["summary"]["unrecorded_ended_count"],
            },
            "session_statuses": st["_session_statuses"],
        })

    return {
        "class_info": {
            "id": class_info["id"],
            "class_code": class_info["class_code"],
            "program_id": class_info["program_id"],
            "program_code": class_info.get("program_code"),
            "program_name": class_info.get("program_name"),
            "expected_start_date": class_info.get("expected_start_date_str"),
            "learning_mode": class_info.get("learning_mode"),
            "status": class_info.get("status"),
        },
        "sessions": session_columns,
        "students": result_students,
        "pagination": {
            "page": page_num,
            "page_size": page_sz,
            "total_items": total_items,
            "total_pages": total_pages,
        },
        "sort": {
            "sort_by": sort_by_norm,
            "sort_order": "desc" if is_desc else "asc",
        },
        "calculation_rules": {
            "formula": "Tỷ lệ chuyên cần (%) = ((Có mặt + Đi muộn) / Tổng buổi có kết quả điểm danh hợp lệ D) × 100%",
            "denominator_definition": "D = Có mặt (P) + Đi muộn (L) + Vắng có phép (E) + Vắng không phép (U)",
            "total_absent_definition": "Tổng vắng = Vắng có phép (E) + Vắng không phép (U)",
            "eligible_condition": "Chỉ tính trên các buổi học đã kết thúc và có kết quả điểm danh hợp lệ của học viên.",
            "unrecorded_notice": "Buổi học đã kết thúc nhưng chưa điểm danh không tham gia mẫu số D.",
            "future_notice": "Buổi học trong tương lai hoặc buổi bị hủy không làm thay đổi tỷ lệ chuyên cần.",
        },
    }
