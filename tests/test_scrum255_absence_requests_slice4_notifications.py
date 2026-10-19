"""
Test suite cho SCRUM-255 Lát 4:
Thông báo kết quả xử lý đơn xin phép vắng cho học viên.
- Duyệt đơn (approve) phát thông báo 'absence_approved' kèm chi tiết buổi học và người duyệt.
- Từ chối đơn (reject) phát thông báo 'absence_rejected' kèm lý do từ chối.
- Học viên truy xuất thông báo của chính mình qua list_my_notifications_service.
- Bảo mật: không rò rỉ thông báo của học viên cho tài khoản khác.
- Khả năng chịu lỗi: lỗi phát thông báo sau commit không làm rollback quyết định duyệt đơn.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import uuid
import pytest

from app.database.connection import get_db_connection
from app.models.absence_request import (
    ABSENCE_STATUS_APPROVED,
    ABSENCE_STATUS_PENDING,
    ABSENCE_STATUS_REJECTED,
)
from app.services.absence_request_service import (
    review_absence_request_service,
)
from app.services.schedule_service import list_my_notifications_service


VIETNAM_TZ = timezone(timedelta(hours=7))


@pytest.fixture(autouse=True)
def clean_notifications_table():
    yield
    # Cleanup các notification sinh ra trong test
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM schedule_notifications WHERE change_type IN ('absence_approved', 'absence_rejected')")
            cursor.execute("DELETE FROM absence_request_attachments WHERE file_name LIKE 'test_l4_%'")
            cursor.execute("DELETE FROM attendance_audit_logs WHERE reason LIKE '%SCRUM-255%' OR reason LIKE '%Mã đơn%'")
            cursor.execute("DELETE FROM session_attendances WHERE schedule_id LIKE 'sch-scrum255-l4%'")
            cursor.execute("DELETE FROM absence_requests WHERE id LIKE 'req-scrum255-l4%'")
            cursor.execute("DELETE FROM class_schedules WHERE id LIKE 'sch-scrum255-l4%'")
            cursor.execute("DELETE FROM class_enrollments WHERE class_id LIKE 'cls-scrum255-l4%'")
            cursor.execute("DELETE FROM classes WHERE id LIKE 'cls-scrum255-l4%'")
            cursor.execute("DELETE FROM subjects WHERE id LIKE 'subj-scrum255-l4%'")
            cursor.execute("DELETE FROM students WHERE id LIKE 'stu-scrum255-l4%'")
            cursor.execute("DELETE FROM users WHERE id LIKE 'u-scrum255-l4%'")
        conn.commit()
    finally:
        conn.close()


def _setup_notification_test_context():
    """Tạo dữ liệu thử nghiệm độc lập cho Lát 4."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Tạo Giảng viên và Quản lý đào tạo
            trainer_user_id = "u-scrum255-l4-trainer"
            student_user_id_1 = "u-scrum255-l4-stu1"
            student_user_id_2 = "u-scrum255-l4-stu2"

            cursor.execute(
                """
                INSERT INTO users (id, name, email, password_hash, status)
                VALUES 
                    (%s, 'Giảng viên Lát 4', 'trainer.l4@example.com', 'hash', 'active'),
                    (%s, 'Học viên Một Lát 4', 'student1.l4@example.com', 'hash', 'active'),
                    (%s, 'Học viên Hai Lát 4', 'student2.l4@example.com', 'hash', 'active')
                ON DUPLICATE KEY UPDATE name=VALUES(name)
                """,
                (trainer_user_id, student_user_id_1, student_user_id_2),
            )

            # 2. Tạo hồ sơ học viên
            student_id_1 = "stu-scrum255-l4-1"
            student_id_2 = "stu-scrum255-l4-2"
            cursor.execute(
                """
                INSERT INTO students (id, student_code, user_id, full_name, email, phone, status, created_at, updated_at)
                VALUES 
                    (%s, 'HV-L4-001', %s, 'Học viên Một Lát 4', 'student1.l4@example.com', '0911000001', 'studying', NOW(), NOW()),
                    (%s, 'HV-L4-002', %s, 'Học viên Hai Lát 4', 'student2.l4@example.com', '0911000002', 'studying', NOW(), NOW())
                ON DUPLICATE KEY UPDATE full_name=VALUES(full_name)
                """,
                (student_id_1, student_user_id_1, student_id_2, student_user_id_2),
            )

            # 3. Tạo môn học và lớp
            subj_id = "subj-scrum255-l4"
            cursor.execute(
                """
                INSERT INTO subjects (id, code, name, credits, status, created_at, updated_at)
                VALUES (%s, 'SUBJ-L4', 'Kiểm thử Thông báo Lát 4', 3, 'active', NOW(), NOW())
                ON DUPLICATE KEY UPDATE name=VALUES(name)
                """,
                (subj_id,),
            )

            cls_id = "cls-scrum255-l4"
            cursor.execute(
                """
                INSERT INTO classes (id, class_code, program_id, status, created_at, updated_at)
                VALUES (%s, 'CLS-L4', 'prog-01', 'in_progress', NOW(), NOW())
                ON DUPLICATE KEY UPDATE class_code=VALUES(class_code)
                """,
                (cls_id,),
            )

            # 4. Ghi danh cả 2 học viên vào lớp
            cursor.execute(
                """
                INSERT INTO class_enrollments (id, class_id, student_id, enrolled_at, enrolled_by, status, created_at, updated_at)
                VALUES 
                    ('enr-l4-1', %s, %s, '2026-09-01', %s, 'enrolled', NOW(), NOW()),
                    ('enr-l4-2', %s, %s, '2026-09-01', %s, 'enrolled', NOW(), NOW())
                ON DUPLICATE KEY UPDATE status='enrolled'
                """,
                (cls_id, student_id_1, trainer_user_id, cls_id, student_id_2, trainer_user_id),
            )

            # 5. Tạo 2 buổi học tương lai được phân công cho trainer
            today_vn = datetime.now(VIETNAM_TZ).date()
            future_date = today_vn + timedelta(days=5)

            sch_id_1 = "sch-scrum255-l4-1"
            sch_id_2 = "sch-scrum255-l4-2"
            cursor.execute(
                """
                INSERT INTO class_schedules (
                    id, class_id, subject_id, session_number, topic, learning_date,
                    shift, start_time, end_time, instructor_id, status, attendance_checked,
                    created_at, updated_at
                )
                VALUES 
                    (%s, %s, %s, 1, 'Bài học Lát 4 buổi 1', %s, 'Ca 1', '08:00:00', '10:00:00', %s, 'scheduled', 0, NOW(), NOW()),
                    (%s, %s, %s, 2, 'Bài học Lát 4 buổi 2', %s, 'Ca 2', '13:30:00', '15:30:00', %s, 'scheduled', 0, NOW(), NOW())
                ON DUPLICATE KEY UPDATE topic=VALUES(topic)
                """,
                (sch_id_1, cls_id, subj_id, future_date, trainer_user_id,
                 sch_id_2, cls_id, subj_id, future_date, trainer_user_id),
            )

            # 6. Tạo 2 đơn xin phép vắng đang chờ duyệt (pending) cho học viên 1
            req_id_1 = "req-scrum255-l4-1"
            req_id_2 = "req-scrum255-l4-2"
            cursor.execute(
                """
                INSERT INTO absence_requests (id, schedule_id, student_id, reason, status, created_at, updated_at)
                VALUES 
                    (%s, %s, %s, 'Em xin phép nghỉ buổi 1 để đi khám bệnh.', 'pending', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)),
                    (%s, %s, %s, 'Em xin phép nghỉ buổi 2 vì bận việc gia đình.', 'pending', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE status='pending'
                """,
                (req_id_1, sch_id_1, student_id_1, req_id_2, sch_id_2, student_id_1),
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "trainer_user_id": trainer_user_id,
        "student_user_id_1": student_user_id_1,
        "student_user_id_2": student_user_id_2,
        "student_id_1": student_id_1,
        "student_id_2": student_id_2,
        "sch_id_1": sch_id_1,
        "sch_id_2": sch_id_2,
        "req_id_1": req_id_1,
        "req_id_2": req_id_2,
    }


class TestScrum255Slice4Notifications:
    def test_01_approve_request_generates_absence_approved_notification(self):
        """Khi duyệt đơn, hệ thống tạo thông báo absence_approved cho học viên."""
        ctx = _setup_notification_test_context()

        # Giảng viên duyệt đơn 1
        res = review_absence_request_service(
            request_id=ctx["req_id_1"],
            reviewer_user_id=ctx["trainer_user_id"],
            reviewer_roles=["trainer"],
            payload={"action": "approve"},
        )
        assert res["status"] == ABSENCE_STATUS_APPROVED
        assert res["reviewer_name"] == "Giảng viên Lát 4"

        # Kiểm tra học viên 1 nhận được thông báo
        notifs_stu1 = list_my_notifications_service(ctx["student_user_id_1"])
        assert len(notifs_stu1) >= 1

        matched_notif = next((n for n in notifs_stu1 if n["schedule_id"] == ctx["sch_id_1"]), None)
        assert matched_notif is not None
        assert matched_notif["change_type"] == "absence_approved"
        assert "Đơn xin phép vắng đã được duyệt" in matched_notif["title"]
        assert "chấp thuận" in matched_notif["message"]
        assert "Vắng có phép" in matched_notif["message"]
        assert "Giảng viên Lát 4" in matched_notif["message"]

    def test_02_reject_request_generates_absence_rejected_notification_with_reason(self):
        """Khi từ chối đơn, hệ thống tạo thông báo absence_rejected kèm lý do từ chối."""
        ctx = _setup_notification_test_context()

        # Giảng viên từ chối đơn 2 kèm lý do bắt buộc
        rejection_reason = "Lý do việc gia đình không thuộc diện được xét nghỉ có phép theo quy chế."
        res = review_absence_request_service(
            request_id=ctx["req_id_2"],
            reviewer_user_id=ctx["trainer_user_id"],
            reviewer_roles=["trainer"],
            payload={"action": "reject", "rejection_reason": rejection_reason},
        )
        assert res["status"] == ABSENCE_STATUS_REJECTED
        assert res["rejection_reason"] == rejection_reason

        # Kiểm tra học viên 1 nhận được thông báo từ chối
        notifs_stu1 = list_my_notifications_service(ctx["student_user_id_1"])
        matched_notif = next((n for n in notifs_stu1 if n["schedule_id"] == ctx["sch_id_2"]), None)
        assert matched_notif is not None
        assert matched_notif["change_type"] == "absence_rejected"
        assert "Đơn xin phép vắng đã bị từ chối" in matched_notif["title"]
        assert rejection_reason in matched_notif["message"]

    def test_03_notification_privacy_isolation_between_students(self):
        """Học viên khác không nhìn thấy thông báo kết quả duyệt đơn của người khác."""
        ctx = _setup_notification_test_context()

        # Duyệt đơn 1 cho học viên 1
        review_absence_request_service(
            request_id=ctx["req_id_1"],
            reviewer_user_id=ctx["trainer_user_id"],
            reviewer_roles=["trainer"],
            payload={"action": "approve"},
        )

        # Học viên 2 tra cứu danh sách thông báo của mình -> không có thông báo của học viên 1
        notifs_stu2 = list_my_notifications_service(ctx["student_user_id_2"])
        leaked_notifs = [n for n in notifs_stu2 if n["schedule_id"] == ctx["sch_id_1"]]
        assert len(leaked_notifs) == 0

    def test_04_fault_tolerant_notification_failure_does_not_rollback_review(self):
        """
        Khả năng chịu lỗi: Nếu phát sinh lỗi trong quá trình ghi thông báo sau commit,
        hệ thống không làm rollback quyết định duyệt đơn hoặc ném lỗi 500 ra ngoài.
        """
        ctx = _setup_notification_test_context()

        with patch("app.repositories.class_schedule_repository.insert_schedule_notifications_batch", side_effect=Exception("Database connection timeout")):
            res = review_absence_request_service(
                request_id=ctx["req_id_1"],
                reviewer_user_id=ctx["trainer_user_id"],
                reviewer_roles=["trainer"],
                payload={"action": "approve"},
            )

        # Quyết định duyệt đơn vẫn thành công và được lưu lại
        assert res["status"] == ABSENCE_STATUS_APPROVED

        # Điểm danh buổi học vẫn được cập nhật thành Vắng có phép
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(
                    "SELECT status FROM session_attendances WHERE schedule_id = %s AND student_id = %s",
                    (ctx["sch_id_1"], ctx["student_id_1"]),
                )
                att_row = cursor.fetchone()
                assert att_row is not None
                assert att_row["status"] == "excused"
        finally:
            conn.close()
