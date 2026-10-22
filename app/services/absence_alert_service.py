"""
Service đánh giá cảnh báo học viên vắng vượt ngưỡng (SCRUM-257 - AC2).

Quy tắc công thức và nghiệp vụ:
- N = Tổng số buổi học thực tế của lớp đã xếp lịch, không bị hủy, mà học viên thuộc đối tượng phải tham gia (kể cả buổi tương lai).
- A = Số buổi đủ điều kiện đã kết thúc mà học viên được ghi nhận 'excused' (Vắng có phép) hoặc 'unexcused' (Vắng không phép).
- Vượt ngưỡng: (A * 100 > threshold * N). So sánh số học chính xác, không làm tròn tỷ lệ trước khi so sánh.
- N = 0: Không chia cho 0, không bật cờ ("Chưa đủ dữ liệu đánh giá").
- Quản lý vòng đời cờ: Tự động bật khi vượt, tự động tắt khi không còn vượt.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any, Optional
import uuid

from app.database.connection import get_db_connection
from app.repositories import absence_alert_repository, attendance_summary_repository, training_program_repository

logger = logging.getLogger(__name__)

VIETNAM_TZ = timezone(timedelta(hours=7))


def _parse_time_value(val: Any) -> Optional[time]:
    """Chuyển đổi time / timedelta / str từ database sang đối tượng time chuẩn."""
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


def evaluate_class_absence_alerts(class_id: str, persist: bool = True) -> list[dict[str, Any]]:
    """
    Đánh giá trạng thái vắng vượt ngưỡng cho toàn bộ học viên trong lớp theo công thức SCRUM-257.
    - Truy vấn thông tin lớp, chương trình và ngưỡng quy định.
    - Lấy danh sách buổi học thực tế (loại bỏ buổi bị hủy).
    - Tính N (tổng số buổi xếp lịch học viên phải tham dự) và A (số buổi đã kết thúc bị vắng).
    - So sánh: A * 100 > threshold * N.
    - Nếu persist=True: Lưu trạng thái vào bảng student_absence_alerts (AC2).
    - Trả về danh sách kết quả đánh giá của từng học viên.
    """
    class_info = attendance_summary_repository.get_class_details(class_id)
    if not class_info:
        return []

    program_id = class_info.get("program_id")
    threshold = 20.0  # Mặc định 20%
    if program_id:
        program = training_program_repository.get_training_program_by_id(program_id)
        if program and program.absence_alert_threshold is not None:
            threshold = float(program.absence_alert_threshold)

    # Thời gian server theo múi giờ Việt Nam
    now_vn = datetime.now(VIETNAM_TZ)
    today_vn = now_vn.date()
    now_time = now_vn.time()

    # Toàn bộ buổi học thực tế của lớp
    schedules = attendance_summary_repository.get_class_schedules_for_summary(class_id)
    # Loại bỏ buổi bị hủy
    valid_schedules = [s for s in schedules if s.get("status") != "cancelled"]

    # Xác định buổi đã kết thúc (has_ended)
    for s in valid_schedules:
        learning_date = s["learning_date"]
        if isinstance(learning_date, str):
            learning_date = date.fromisoformat(learning_date)

        end_time_val = _parse_time_value(s.get("end_time"))
        is_past = (learning_date < today_vn)
        is_future = (learning_date > today_vn)

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
        s["_learning_date_val"] = learning_date

    # Danh sách học viên và điểm danh
    students = attendance_summary_repository.get_enrolled_and_history_students(class_id)
    all_attendances = attendance_summary_repository.get_class_attendances(class_id)
    att_map = {(r["schedule_id"], r["student_id"]): r for r in all_attendances}

    results: list[dict[str, Any]] = []

    for stud in students:
        s_id = stud["student_id"]
        enrolled_date = stud.get("enrolled_date")
        lifecycle_status = stud.get("lifecycle_status")
        effective_date_val = stud.get("effective_date_val")

        N = 0  # Tổng số buổi học viên phải tham dự
        A = 0  # Số buổi vắng đã kết thúc (có phép + không phép)

        for s in valid_schedules:
            sched_id = s["id"]
            learning_date_val = s["_learning_date_val"]
            has_ended = s["_has_ended"]

            # Kiểm tra học viên có thuộc đối tượng tham gia buổi học không
            is_eligible = True
            if enrolled_date and enrolled_date > learning_date_val:
                is_eligible = False
            elif lifecycle_status in ("reserved", "transferred", "dropped") and effective_date_val:
                if learning_date_val >= effective_date_val:
                    is_eligible = False

            if not is_eligible:
                continue

            # Buổi học viên phải tham gia -> tăng N
            N += 1

            # Nếu buổi đã kết thúc, kiểm tra bản ghi điểm danh
            if has_ended:
                sa = att_map.get((sched_id, s_id))
                if sa:
                    st = sa.get("status")
                    if st in ("excused", "unexcused"):
                        A += 1

        # So sánh vượt ngưỡng
        if N == 0:
            is_flagged = False
            insufficient_data = True
            absence_rate = 0.0
            tooltip = "Chưa đủ dữ liệu đánh giá"
        else:
            insufficient_data = False
            absence_rate = round((A / N) * 100.0, 2)
            # So sánh chính xác không làm tròn: A * 100 > threshold * N
            is_flagged = (A * 100 > threshold * N)

            threshold_display = f"{threshold:.2f}".rstrip("0").rstrip(".")
            rate_display = f"{absence_rate:.2f}".rstrip("0").rstrip(".")
            if is_flagged:
                tooltip = f"Vắng {A}/{N} buổi — {rate_display}%, vượt ngưỡng {threshold_display}%"
            else:
                tooltip = f"Vắng {A}/{N} buổi — {rate_display}%, chưa vượt ngưỡng {threshold_display}%"

        status_str = "active" if is_flagged else "inactive"

        eval_item = {
            "student_id": s_id,
            "student_code": stud.get("student_code"),
            "full_name": stud.get("full_name"),
            "class_id": class_id,
            "program_id": program_id or "",
            "absent_sessions": A,
            "total_sessions": N,
            "absence_rate": absence_rate,
            "threshold": threshold,
            "is_flagged": is_flagged,
            "insufficient_data": insufficient_data,
            "status": status_str,
            "tooltip": tooltip,
            "newly_triggered": False,
            "newly_resolved": False,
        }

        if persist and program_id:
            saved = absence_alert_repository.upsert_student_absence_alert(
                class_id=class_id,
                student_id=s_id,
                program_id=program_id,
                status=status_str,
                absent_sessions=A,
                total_sessions=N,
                absence_rate=absence_rate,
                threshold=threshold,
            )
            eval_item["alert_id"] = saved["id"]
            eval_item["alert_round"] = saved["alert_round"]
            eval_item["first_triggered_at"] = saved["first_triggered_at"]
            eval_item["last_evaluated_at"] = saved["last_evaluated_at"]
            eval_item["newly_triggered"] = saved["newly_triggered"]
            eval_item["newly_resolved"] = saved["newly_resolved"]

            # SCRUM-257 AC3: Khi cờ chuyển sang bật -> tạo thông báo cho Giảng viên & Quản lý đào tạo
            if saved["newly_triggered"]:
                dispatch_absence_alert_notifications(
                    alert_id=saved["id"],
                    alert_round=saved["alert_round"],
                    class_id=class_id,
                    class_code=class_info.get("class_code") or class_id,
                    student_id=s_id,
                    student_code=stud.get("student_code") or "",
                    student_name=stud.get("full_name") or "Học viên",
                    program_id=program_id,
                    program_name=class_info.get("program_name") or "",
                    absent_sessions=A,
                    total_sessions=N,
                    absence_rate=absence_rate,
                    threshold=threshold,
                )

        results.append(eval_item)

    return results


def get_student_profile_absence_alerts_service(
    student_id: str,
    current_user_id: Optional[str] = None,
    current_user_roles: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """
    Lấy danh sách cảnh báo vắng đang bật trên hồ sơ học viên (SCRUM-257 - AC2).
    Phân quyền:
    - Quản lý đào tạo (training_manager) & Giảng viên (trainer)
    - Học viên xem hồ sơ của chính mình
    """
    alerts = absence_alert_repository.get_active_absence_alerts_by_student(student_id)
    formatted = []
    for a in alerts:
        rate = a["absence_rate"]
        thresh = a["threshold"]
        rate_display = f"{rate:.2f}".rstrip("0").rstrip(".")
        thresh_display = f"{thresh:.2f}".rstrip("0").rstrip(".")

        formatted.append({
            "alert_id": a["alert_id"],
            "class_id": a["class_id"],
            "class_code": a.get("class_code"),
            "program_id": a["program_id"],
            "program_code": a.get("program_code"),
            "program_name": a.get("program_name"),
            "absent_sessions": a["absent_sessions"],
            "total_sessions": a["total_sessions"],
            "absence_rate": rate,
            "absence_rate_formatted": f"{rate_display}%",
            "threshold": thresh,
            "threshold_formatted": f"{thresh_display}%",
            "first_triggered_at": a.get("first_triggered_at_str"),
            "last_evaluated_at": a.get("last_evaluated_at_str"),
            "is_flagged": True,
            "tooltip": f"Vắng {a['absent_sessions']}/{a['total_sessions']} buổi — {rate_display}%, vượt ngưỡng {thresh_display}%",
        })
    return formatted


def recalculate_alerts_for_program(program_id: str) -> int:
    """
    Kích hoạt đánh giá lại cảnh báo vắng cho tất cả các lớp thuộc chương trình đào tạo khi ngưỡng thay đổi (AC1, AC2).
    """
    conn = get_db_connection()
    try:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id FROM classes WHERE program_id = %s AND status != 'archived'",
                (program_id,),
            )
            classes = cursor.fetchall() or []
        
        evaluated_count = 0
        for c in classes:
            evaluate_class_absence_alerts(c["id"], persist=True)
            evaluated_count += 1
        return evaluated_count
    finally:
        conn.close()


def dispatch_absence_alert_notifications(
    alert_id: str,
    alert_round: int,
    class_id: str,
    class_code: str,
    student_id: str,
    student_code: str,
    student_name: str,
    program_id: str,
    program_name: str,
    absent_sessions: int,
    total_sessions: int,
    absence_rate: float,
    threshold: float,
) -> int:
    """
    Phát thông báo khi cờ cảnh báo vắng của học viên được bật (SCRUM-257 - AC3).
    - Người nhận: Giảng viên phụ trách lớp và Quản lý đào tạo (được deduplicate).
    - Nội dung: Tỷ lệ vắng, số buổi vắng/tổng số buổi, ngưỡng, link đến bảng chuyên cần lớp.
    - Chống trùng: Dựa trên unique constraint (alert_id, alert_round, recipient_id).
    - Cách ly lỗi: Một người nhận lỗi không ảnh hưởng tới người khác.
    """
    recipients = absence_alert_repository.get_alert_recipients_for_class(class_id, program_id)
    if not recipients:
        logger.info(
            "Không tìm thấy người nhận hợp lệ (giảng viên/quản lý đào tạo) cho cảnh báo lớp %s",
            class_code,
        )
        return 0

    threshold_display = f"{threshold:.2f}".rstrip("0").rstrip(".")
    rate_display = f"{absence_rate:.2f}".rstrip("0").rstrip(".")

    title = f"Cảnh báo vắng vượt ngưỡng: Học viên {student_name} ({class_code})"
    message = (
        f"Học viên {student_name} (Mã: {student_code}) có tỷ lệ vắng {rate_display}% "
        f"({absent_sessions}/{total_sessions} buổi), vượt ngưỡng {threshold_display}% "
        f"của lớp {class_code}."
    )
    if program_name:
        message += f" Chương trình: {program_name}."

    sent_count = 0
    now_str = datetime.now(VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S")

    for r in recipients:
        r_id = r["id"]
        r_role = r.get("recipient_role", "training_manager")
        notif_item = {
            "id": str(uuid.uuid4()),
            "alert_id": alert_id,
            "alert_round": alert_round,
            "recipient_id": r_id,
            "recipient_role": r_role,
            "title": title,
            "message": message,
            "class_id": class_id,
            "student_id": student_id,
            "created_at": now_str,
        }
        try:
            inserted = absence_alert_repository.insert_absence_alert_notification(notif_item)
            if inserted:
                sent_count += 1
                logger.info(
                    "Đã ghi nhận thông báo cảnh báo vắng vượt ngưỡng cho %s (%s) round %d",
                    r_id,
                    r_role,
                    alert_round,
                )
        except Exception as e:
            logger.exception(
                "Lỗi khi gửi thông báo cảnh báo vắng cho người nhận %s: %s",
                r_id,
                e,
            )

    return sent_count


def list_my_absence_alert_notifications_service(
    user_id: str, unread_only: bool = False
) -> list[dict[str, Any]]:
    """
    Lấy danh sách thông báo cảnh báo vắng của chính người dùng đăng nhập (SCRUM-257 AC3).
    """
    if not user_id:
        return []
    return absence_alert_repository.get_absence_alert_notifications_by_recipient(
        recipient_id=user_id, unread_only=unread_only
    )


def mark_absence_alert_notification_read_service(notif_id: str, user_id: str) -> bool:
    """
    Đánh dấu đã đọc thông báo cảnh báo vắng (SCRUM-257 AC3).
    """
    if not notif_id or not user_id:
        return False
    return absence_alert_repository.mark_absence_alert_notification_as_read(
        notif_id=notif_id, user_id=user_id
    )
