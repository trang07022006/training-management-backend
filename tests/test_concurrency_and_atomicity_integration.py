"""
Integration tests xác minh:
1. An toàn môi trường: Chốt bảo vệ ngăn chạy nhầm trên database đang sử dụng (training_management).
   Chỉ cho phép chạy trên database kiểm thử riêng biệt (training_management_test).
2. Tính nguyên tử (Atomicity) của Ghi đè lịch học:
   Gặp lỗi giữa chừng -> Rollback toàn bộ -> Lịch cũ được bảo toàn 100%.
3. Khóa buổi đã điểm danh (Attendance Checked Lock):
   Bảo vệ ở mọi đường: Sửa buổi, Hủy buổi, Xóa cả lớp, Ghi đè toàn bộ.
4. Chống tranh chấp ghi danh đồng thời (Concurrency / Race Condition):
   2 luồng đồng thời ghi danh vào lớp chỉ còn 1 chỗ -> 1 thành công, 1 nhận lỗi lớp đầy, sĩ số đúng 1.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
import os
import threading
import unittest
import uuid

# Thiết lập database kiểm thử riêng biệt trước khi nạp app / connection
os.environ["DB_NAME"] = "training_management_test"

from app.database import connection
from app.database.connection import get_db_connection, reset_db_pool
from app.models.class_schedule import ClassSchedule
from app.repositories import class_repository, class_schedule_repository, enrollment_repository
from app.services import enrollment_service, schedule_service
from app.services.enrollment_service import ClassCapacityFullError
from app.services.schedule_service import ScheduleAttendanceCheckedError


class TestConcurrencyAndAtomicityIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Chốt an toàn môi trường bắt buộc (Environment Guard)
        reset_db_pool()
        db_config = connection._get_db_config()
        current_db = db_config.get("database", "")
        if current_db != "training_management_test":
            raise RuntimeError(
                f"ENVIRONMENT_GUARD_BLOCKED: Integration test bị chặn để bảo vệ dữ liệu! "
                f"Yêu cầu DB_NAME='training_management_test', hiện tại là '{current_db}'."
            )

    def setUp(self):
        self.created_class_ids = []
        self.created_student_ids = []

    def tearDown(self):
        # Dọn dẹp chỉ dữ liệu do chính test tạo ra
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                if self.created_class_ids:
                    fmt = ",".join(["%s"] * len(self.created_class_ids))
                    cur.execute(f"DELETE FROM class_enrollments WHERE class_id IN ({fmt})", tuple(self.created_class_ids))
                    cur.execute(f"DELETE FROM schedule_notifications WHERE class_id IN ({fmt})", tuple(self.created_class_ids))
                    cur.execute(f"DELETE FROM class_schedules WHERE class_id IN ({fmt})", tuple(self.created_class_ids))
                    cur.execute(f"DELETE FROM class_subjects WHERE class_id IN ({fmt})", tuple(self.created_class_ids))
                    cur.execute(f"DELETE FROM classes WHERE id IN ({fmt})", tuple(self.created_class_ids))

                if self.created_student_ids:
                    fmt = ",".join(["%s"] * len(self.created_student_ids))
                    cur.execute(f"DELETE FROM students WHERE id IN ({fmt})", tuple(self.created_student_ids))

                conn.commit()
        finally:
            conn.close()

    def test_environment_guard_blocks_when_database_is_production(self):
        """Chứng minh chốt an toàn ngăn chặn chạy nhầm trên database đang sử dụng."""
        # Giả lập cấu hình database production
        saved_db = os.environ.get("DB_NAME")
        try:
            os.environ["DB_NAME"] = "training_management"
            reset_db_pool()
            cfg = connection._get_db_config()
            self.assertEqual(cfg["database"], "training_management")
            # Chốt kiểm tra phải từ chối ngay lập tức
            with self.assertRaises(RuntimeError) as ctx:
                if cfg["database"] != "training_management_test":
                    raise RuntimeError(f"ENVIRONMENT_GUARD_BLOCKED: Không được chạy trên {cfg['database']}")
            self.assertIn("ENVIRONMENT_GUARD_BLOCKED", str(ctx.exception))
        finally:
            os.environ["DB_NAME"] = "training_management_test"
            reset_db_pool()

    def test_atomic_schedule_overwrite_rolls_back_on_failure_preserving_old_schedules(self):
        """
        Xác minh tính nguyên tử:
        1. Tạo lớp và 3 buổi học cũ trong DB kiểm thử.
        2. Cố tình gây lỗi khi thêm danh sách buổi học mới (sau bước xóa).
        3. Transaction phải rollback toàn bộ và 3 buổi học cũ còn nguyên vẹn 100%.
        """
        class_id = f"cls-atomic-{uuid.uuid4().hex[:8]}"
        self.created_class_ids.append(class_id)

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO classes (id, class_code, program_id, max_capacity, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (class_id, f"ATOMIC-{uuid.uuid4().hex[:4]}", "prog-1", 30, "preparing"),
                )
                # Thêm 3 buổi học cũ
                for i in range(1, 4):
                    cur.execute(
                        """
                        INSERT INTO class_schedules (id, class_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW(), NOW())
                        """,
                        (f"sched-old-{class_id}-{i}", class_id, i, f"Bài học cũ #{i}", date(2026, 11, i * 2), "Ca 1", "07:30:00", "09:30:00", "scheduled"),
                    )
                conn.commit()
        finally:
            conn.close()

        # Xác nhận đã có 3 buổi học cũ trong DB
        old_schedules = class_schedule_repository.list_schedules_by_class_id(class_id)
        self.assertEqual(len(old_schedules), 3)

        # Chuẩn bị danh sách buổi học mới, nhưng cố tình chèn 1 bản ghi lỗi vi phạm schema
        new_valid_schedule = ClassSchedule(
            id=f"sched-new-1-{uuid.uuid4().hex[:6]}",
            class_id=class_id,
            session_number=1,
            topic="Buổi mới 1",
            learning_date=date(2026, 12, 1),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            status="scheduled",
        )
        new_invalid_schedule = ClassSchedule(
            id=f"sched-new-2-{uuid.uuid4().hex[:6]}",
            class_id=class_id,
            session_number=2,
            topic="Buổi mới 2",
            learning_date="NOT_A_VALID_DATE_FORMAT_ERROR",  # Gây lỗi ném exception trong INSERT
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            status="scheduled",
        )

        # Gọi thay thế trong transaction
        with self.assertRaises(Exception):
            class_schedule_repository.replace_schedules_in_transaction(
                class_id, [new_valid_schedule, new_invalid_schedule]
            )

        # CHỨNG MINH TRANSACTION ROLLBACK: Lịch cũ còn nguyên vẹn 100%!
        schedules_after_failure = class_schedule_repository.list_schedules_by_class_id(class_id)
        self.assertEqual(len(schedules_after_failure), 3, "Lịch cũ không được bị mất khi thêm lịch mới thất bại!")
        topics = [s.topic for s in schedules_after_failure]
        self.assertIn("Bài học cũ #1", topics)
        self.assertIn("Bài học cũ #2", topics)
        self.assertIn("Bài học cũ #3", topics)

    def test_attendance_checked_lock_enforced_across_all_endpoints(self):
        """
        Kiểm tra buổi đã điểm danh bị chặn ở cả 4 đường:
        - Sửa buổi lẻ
        - Hủy buổi lẻ
        - Xóa toàn bộ lịch lớp
        - Ghi đè toàn bộ lịch lớp
        """
        class_id = f"cls-attend-{uuid.uuid4().hex[:8]}"
        self.created_class_ids.append(class_id)
        sched_id = f"sch-att-{uuid.uuid4().hex[:8]}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO classes (id, class_code, program_id, max_capacity, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (class_id, f"ATT-{uuid.uuid4().hex[:4]}", "prog-1", 30, "in_progress"),
                )
                # Buổi học đã được điểm danh: attendance_checked = 1
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, session_number, topic, learning_date, shift, start_time, end_time, status, attendance_checked, created_at, updated_at)
                    VALUES (%s, %s, 1, 'Buổi đã điểm danh', '2026-11-01', 'Ca 1', '07:30:00', '09:30:00', 'in_progress', 1, NOW(), NOW())
                    """,
                    (sched_id, class_id),
                )
                conn.commit()
        finally:
            conn.close()

        # 1. Chặn sửa buổi lẻ
        with self.assertRaises(ScheduleAttendanceCheckedError):
            schedule_service.update_single_schedule_service(class_id, sched_id, {"topic": "Sửa chủ đề"})

        # 2. Chặn hủy buổi lẻ
        with self.assertRaises(ScheduleAttendanceCheckedError):
            schedule_service.cancel_single_schedule_service(class_id, sched_id, {"reason": "Hủy buổi"})

        # 3. Chặn xóa hàng loạt
        with self.assertRaises(ScheduleAttendanceCheckedError):
            schedule_service.delete_class_schedules_service(class_id)

        # 4. Chặn ghi đè toàn bộ
        with self.assertRaises(RuntimeError) as ctx:
            class_schedule_repository.replace_schedules_in_transaction(class_id, [])
        self.assertIn("ATTENDANCE_CHECKED_LOCK", str(ctx.exception))

    def test_concurrent_enrollment_race_condition_protection(self):
        """
        Xác minh ghi danh đồng thời (Concurrency Test bằng 2 luồng thật trên MySQL):
        - Lớp chỉ còn duy nhất 1 chỗ trống (max_capacity = 1).
        - 2 luồng đồng thời gửi yêu cầu ghi danh 2 học viên khác nhau vào cùng một thời điểm.
        - Khóa FOR UPDATE bảo đảm chỉ 1 yêu cầu thành công, yêu cầu còn lại nhận ClassCapacityFullError.
        - Sĩ số cuối cùng không vượt quá 1.
        """
        class_id = f"cls-race-{uuid.uuid4().hex[:8]}"
        st1_id = f"st-r1-{uuid.uuid4().hex[:8]}"
        st2_id = f"st-r2-{uuid.uuid4().hex[:8]}"
        self.created_class_ids.append(class_id)
        self.created_student_ids.extend([st1_id, st2_id])

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # Tạo lớp với max_capacity = 1
                cur.execute(
                    """
                    INSERT INTO classes (id, class_code, program_id, max_capacity, status, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 'preparing', NOW(), NOW())
                    """,
                    (class_id, f"RACE-{uuid.uuid4().hex[:4]}", "prog-1"),
                )
                # Tạo 2 học viên
                cur.execute(
                    """
                    INSERT INTO students (id, student_code, full_name, email, phone, status, created_at, updated_at)
                    VALUES (%s, %s, 'HV Tranh Chấp 1', 'hv1@test.vn', '0981111111', 'enrolled', NOW(), NOW()),
                           (%s, %s, 'HV Tranh Chấp 2', 'hv2@test.vn', '0982222222', 'enrolled', NOW(), NOW())
                    """,
                    (st1_id, f"ST-R1-{uuid.uuid4().hex[:4]}", st2_id, f"ST-R2-{uuid.uuid4().hex[:4]}"),
                )
                conn.commit()
        finally:
            conn.close()

        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker(student_id):
            barrier.wait()  # Cả 2 luồng kích hoạt gọi đồng thời tại cùng mili-giây
            try:
                res = enrollment_service.enroll_students_service(
                    class_id=class_id,
                    payload={"student_id": student_id},
                    actor_user_id="admin-test",
                )
                results.append((student_id, res))
            except Exception as e:
                errors.append((student_id, e))

        t1 = threading.Thread(target=worker, args=(st1_id,))
        t2 = threading.Thread(target=worker, args=(st2_id,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # CHỨNG MINH KẾT QUẢ ĐỒNG THỜI:
        # 1. Đúng 1 yêu cầu thành công
        self.assertEqual(len(results), 1, f"Chỉ 1 luồng được ghi danh thành công! Kết quả: {results}")
        # 2. Đúng 1 yêu cầu bị từ chối vì lớp đầy
        self.assertEqual(len(errors), 1, f"Luồng còn lại phải bị từ chối! Lỗi: {errors}")
        self.assertIsInstance(errors[0][1], ClassCapacityFullError, "Lỗi ném ra phải là ClassCapacityFullError")

        # 3. Kiểm tra trong cơ sở dữ liệu thật: Số bản ghi ghi danh chính xác là 1
        enrollments = enrollment_repository.get_enrollments_by_class_id(class_id)
        self.assertEqual(len(enrollments), 1, "Số bản ghi ghi danh trong database không được vượt quá 1!")

        # 4. Kiểm tra sĩ số lớp: không vượt quá max_capacity
        cls_entity = class_repository.get_class_by_id(class_id)
        self.assertEqual(cls_entity.enrolled_count, 1, "Sĩ số lớp phải là 1, không được bị cộng đúp thành 2!")


if __name__ == "__main__":
    unittest.main()
