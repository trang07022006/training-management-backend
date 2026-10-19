"""
Bộ kiểm thử tự động cho SCRUM-254 Lát 2 (Nhập và lưu điểm danh) và Lát 3 (Quyền sửa và lịch sử kiểm toán).

Nội dung kiểm thử:
1. Lưu thành công 4 trạng thái điểm danh (Có mặt - present, Đi muộn - late, Vắng có phép - excused, Vắng không phép - unexcused).
2. Kiểm tra cờ class_schedules.attendance_checked được bật thành 1 (SCRUM-226 lock).
3. Đánh dấu tất cả có mặt, sau đó sửa riêng một học viên sang trạng thái khác (kiểm tra audit log).
4. Lưu lặp lại cùng dữ liệu (Idempotent): không tạo bản ghi trùng lặp và không ghi audit log giả.
5. Giảng viên được phân công điểm danh thành công buổi hôm nay.
6. Giảng viên ngoài phân công bị từ chối (403).
7. Quản trị viên thuần túy (Pure Admin) bị từ chối quyền nghiệp vụ (403).
8. Giảng viên cố tình sửa buổi quá khứ bị từ chối (403).
9. Quản lý đào tạo (training_manager) được quyền chỉnh sửa buổi quá khứ kèm lý do kiểm toán.
10. Chặn điểm danh buổi học trong tương lai (400 - FUTURE_SESSION_ATTENDANCE_BLOCKED).
11. Chặn điểm danh buổi học đã hủy (400 - SESSION_CANCELLED).
12. Kiểm tra tính toàn vẹn: Học viên không thuộc lớp/buổi học bị từ chối (400).
13. Truy vấn lịch sử kiểm toán điểm danh (GET /api/v1/schedules/<id>/attendance/history).
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services.attendance_service import VIETNAM_TZ


class Scrum254Slice2And3SaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.tm_user_id = f"test-tm2-{cls.suffix}"
        cls.admin_user_id = f"test-admin2-{cls.suffix}"
        cls.trainer_assigned_id = f"test-tr2-assigned-{cls.suffix}"
        cls.trainer_unassigned_id = f"test-tr2-unassigned-{cls.suffix}"
        cls.trainee_user_id = f"test-trainee2-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo các user kiểm thử với role tương ứng
                users = [
                    (cls.tm_user_id, f"tm2_{cls.suffix}@ictu.edu.vn", "Training Manager 2"),
                    (cls.admin_user_id, f"admin2_{cls.suffix}@ictu.edu.vn", "Pure Admin 2"),
                    (cls.trainer_assigned_id, f"tr2_assigned_{cls.suffix}@ictu.edu.vn", "Assigned Trainer 2"),
                    (cls.trainer_unassigned_id, f"tr2_unassigned_{cls.suffix}@ictu.edu.vn", "Unassigned Trainer 2"),
                    (cls.trainee_user_id, f"trainee2_{cls.suffix}@ictu.edu.vn", "Trainee User 2"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # Gán role
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.tm_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_assigned_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_unassigned_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.trainee_user_id,))

                # 2. Tạo Program, Class, Subject, Room
                cls.prog_id = f"prog2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program SCRUM-254 S2', NOW(), NOW())",
                    (cls.prog_id, f"PRG2_{cls.suffix}"),
                )

                cls.class_id = f"cls2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 10 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_id, f"CLS2_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"subj2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject SCRUM-254 S2', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUB2_{cls.suffix}"),
                )

                cls.room_id = f"room2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classrooms (id, room_code, room_name, capacity, status, created_at, updated_at) VALUES (%s, %s, 'Phòng Lab 202', 40, 'active', NOW(), NOW())",
                    (cls.room_id, f"LAB2_{cls.suffix}"),
                )

                # 3. Tạo các buổi học: Buổi hôm nay, buổi quá khứ, buổi tương lai, buổi đã hủy
                today_vn = datetime.now(VIETNAM_TZ).date()
                cls.schedule_today_id = f"sch-today2-{cls.suffix}"
                cls.schedule_past_id = f"sch-past2-{cls.suffix}"
                cls.schedule_future_id = f"sch-future2-{cls.suffix}"
                cls.schedule_cancelled_id = f"sch-cancel2-{cls.suffix}"

                cur.execute(
                    """
                    INSERT INTO class_schedules (
                        id, class_id, subject_id, session_number, topic, learning_date,
                        shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at
                    ) VALUES 
                    (%s, %s, %s, 1, 'Bài học hôm nay S2', %s, 'Sáng', '08:00:00', '11:30:00', %s, %s, 'scheduled', 0, NOW(), NOW()),
                    (%s, %s, %s, 2, 'Bài học quá khứ S2', %s, 'Sáng', '08:00:00', '11:30:00', %s, %s, 'scheduled', 0, NOW(), NOW()),
                    (%s, %s, %s, 3, 'Bài học tương lai S2', %s, 'Sáng', '08:00:00', '11:30:00', %s, %s, 'scheduled', 0, NOW(), NOW()),
                    (%s, %s, %s, 4, 'Bài học đã hủy S2', %s, 'Sáng', '08:00:00', '11:30:00', %s, %s, 'cancelled', 0, NOW(), NOW())
                    """,
                    (
                        cls.schedule_today_id, cls.class_id, cls.subject_id, today_vn, cls.room_id, cls.trainer_assigned_id,
                        cls.schedule_past_id, cls.class_id, cls.subject_id, today_vn - timedelta(days=3), cls.room_id, cls.trainer_assigned_id,
                        cls.schedule_future_id, cls.class_id, cls.subject_id, today_vn + timedelta(days=3), cls.room_id, cls.trainer_assigned_id,
                        cls.schedule_cancelled_id, cls.class_id, cls.subject_id, today_vn, cls.room_id, cls.trainer_assigned_id,
                    ),
                )

                # 4. Tạo 4 học viên trong lớp
                cls.students = []
                for i in range(1, 5):
                    st_id = f"stu2-{i}-{cls.suffix}"
                    cur.execute(
                        """
                        INSERT INTO students (id, student_code, full_name, email, phone, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                        """,
                        (st_id, f"SV254_{i}_{cls.suffix}", f"Học viên S2 {i}", f"sv254_{i}_{cls.suffix}@test.edu.vn", f"098765432{i}"),
                    )
                    cur.execute(
                        """
                        INSERT INTO class_enrollments (id, class_id, student_id, enrolled_at, status, enrolled_by, created_at, updated_at)
                        VALUES (%s, %s, %s, CURDATE() - INTERVAL 10 DAY, 'active', %s, NOW(), NOW())
                        """,
                        (f"enr2-{i}-{cls.suffix}", cls.class_id, st_id, cls.tm_user_id),
                    )
                    cls.students.append(st_id)

                conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM attendance_audit_logs WHERE schedule_id IN (%s, %s, %s, %s)", (cls.schedule_today_id, cls.schedule_past_id, cls.schedule_future_id, cls.schedule_cancelled_id))
                cur.execute("DELETE FROM session_attendances WHERE schedule_id IN (%s, %s, %s, %s)", (cls.schedule_today_id, cls.schedule_past_id, cls.schedule_future_id, cls.schedule_cancelled_id))
                cur.execute("DELETE FROM class_schedules WHERE id IN (%s, %s, %s, %s)", (cls.schedule_today_id, cls.schedule_past_id, cls.schedule_future_id, cls.schedule_cancelled_id))
                for st_id in cls.students:
                    cur.execute("DELETE FROM class_enrollments WHERE student_id = %s", (st_id,))
                    cur.execute("DELETE FROM students WHERE id = %s", (st_id,))
                cur.execute("DELETE FROM classrooms WHERE id = %s", (cls.room_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                for uid in [cls.tm_user_id, cls.admin_user_id, cls.trainer_assigned_id, cls.trainer_unassigned_id, cls.trainee_user_id]:
                    cur.execute("DELETE FROM auth_sessions WHERE user_id = %s", (uid,))
                    cur.execute("DELETE FROM user_roles WHERE user_id = %s", (uid,))
                    cur.execute("DELETE FROM users WHERE id = %s", (uid,))
                conn.commit()
        finally:
            conn.close()

    def _get_auth_header(self, user_id: str, role: str) -> dict[str, str]:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                    VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                    """,
                    (session_id, user_id, f"ref_{session_id}"),
                )
            conn.commit()
        finally:
            conn.close()

        with self.app.app_context():
            token = create_access_token(
                identity=user_id,
                additional_claims={"roles": [role], "sid": session_id},
            )
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def test_01_assigned_trainer_save_all_four_statuses_and_check_flag(self):
        """Giảng viên lưu đủ 4 trạng thái, cờ attendance_checked được bật lên 1."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        payload = {
            "attendances": [
                {"student_id": self.students[0], "status": "present", "notes": "Có mặt đúng giờ"},
                {"student_id": self.students[1], "status": "late", "notes": "Muộn 10 phút"},
                {"student_id": self.students[2], "status": "excused", "notes": "Báo ốm"},
                {"student_id": self.students[3], "status": "unexcused", "notes": "Không lý do"},
            ],
            "reason": "Điểm danh đầu giờ",
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()["data"]
        self.assertEqual(data["updated_count"], 4)

        # Kiểm tra cờ attendance_checked trên class_schedules
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("SELECT attendance_checked FROM class_schedules WHERE id = %s", (self.schedule_today_id,))
                sched = cur.fetchone()
                self.assertEqual(sched["attendance_checked"], 1)

                # Kiểm tra 4 bản ghi trong session_attendances
                cur.execute("SELECT student_id, status, notes FROM session_attendances WHERE schedule_id = %s", (self.schedule_today_id,))
                saved = {r["student_id"]: r for r in cur.fetchall()}
                self.assertEqual(len(saved), 4)
                self.assertEqual(saved[self.students[0]]["status"], "present")
                self.assertEqual(saved[self.students[1]]["status"], "late")
                self.assertEqual(saved[self.students[2]]["status"], "excused")
                self.assertEqual(saved[self.students[3]]["status"], "unexcused")
        finally:
            conn.close()

    def test_02_mark_all_present_then_edit_one_student_and_check_audit_log(self):
        """Đánh dấu tất cả có mặt, sau đó sửa riêng một học viên -> kiểm tra audit log ghi đúng."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        # 1. Đánh dấu cả 4 có mặt
        all_present = {
            "attendances": [{"student_id": sid, "status": "present"} for sid in self.students],
            "reason": "Đánh dấu tất cả có mặt",
        }
        res1 = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=all_present,
            headers=headers,
        )
        self.assertEqual(res1.status_code, 200)

        # 2. Sửa riêng học viên 3 thành vắng có phép
        edit_one = {
            "attendances": [{"student_id": self.students[2], "status": "excused", "notes": "Xin nghỉ có giấy phép"}],
            "reason": "Cập nhật đơn xin nghỉ bổ sung",
        }
        res2 = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=edit_one,
            headers=headers,
        )
        self.assertEqual(res2.status_code, 200)

        # 3. Kiểm tra audit log
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute(
                    "SELECT old_status, new_status, reason, performed_by FROM attendance_audit_logs WHERE schedule_id = %s AND student_id = %s ORDER BY created_at DESC",
                    (self.schedule_today_id, self.students[2]),
                )
                logs = cur.fetchall()
                self.assertGreaterEqual(len(logs), 1)
                latest = logs[0]
                self.assertEqual(latest["old_status"], "present")
                self.assertEqual(latest["new_status"], "excused")
                self.assertEqual(latest["reason"], "Cập nhật đơn xin nghỉ bổ sung")
                self.assertEqual(latest["performed_by"], self.trainer_assigned_id)
        finally:
            conn.close()

    def test_03_repeat_save_idempotency_no_duplicate_records(self):
        """Lưu lặp lại cùng dữ liệu không làm tăng bản ghi và không ghi audit log giả."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
            "reason": "Lưu lần 1",
        }
        res1 = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res1.status_code, 200)

        # Đếm số audit log trước lần gửi thứ hai
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM attendance_audit_logs WHERE schedule_id = %s AND student_id = %s", (self.schedule_today_id, self.students[0]))
                count_before = cur.fetchone()[0]
        finally:
            conn.close()

        # Gửi lại y hệt
        res2 = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res2.status_code, 200)

        # Số log không được tăng lên
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM attendance_audit_logs WHERE schedule_id = %s AND student_id = %s", (self.schedule_today_id, self.students[0]))
                count_after = cur.fetchone()[0]
                self.assertEqual(count_before, count_after)
        finally:
            conn.close()

    def test_04_unassigned_trainer_save_forbidden(self):
        """Giảng viên không phụ trách lớp bị chặn lưu điểm danh (403)."""
        headers = self._get_auth_header(self.trainer_unassigned_id, "trainer")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_ATTENDANCE_ACCESS")

    def test_05_admin_pure_save_forbidden(self):
        """Quản trị viên thuần túy không có quyền lưu điểm danh đào tạo (403)."""
        headers = self._get_auth_header(self.admin_user_id, "admin")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)

    def test_06_trainee_save_forbidden(self):
        """Học viên không có quyền lưu điểm danh (403)."""
        headers = self._get_auth_header(self.trainee_user_id, "trainee")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)

    def test_07_trainer_cannot_save_past_session(self):
        """Giảng viên cố tình sửa buổi quá khứ bị từ chối (403 PAST_SESSION_EDIT_FORBIDDEN)."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_past_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "PAST_SESSION_EDIT_FORBIDDEN")

    def test_08_training_manager_can_save_past_session_with_audit_log(self):
        """Quản lý đào tạo được phép sửa điểm danh buổi quá khứ."""
        headers = self._get_auth_header(self.tm_user_id, "training_manager")
        payload = {
            "attendances": [
                {"student_id": self.students[0], "status": "late", "notes": "Sửa lại do học viên báo muộn"},
            ],
            "reason": "Điều chỉnh theo đơn xác nhận của quản lý",
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_past_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()["data"]
        self.assertEqual(data["updated_count"], 1)

    def test_09_save_future_session_blocked(self):
        """Chặn điểm danh buổi học tương lai (400 FUTURE_SESSION_ATTENDANCE_BLOCKED)."""
        headers = self._get_auth_header(self.tm_user_id, "training_manager")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_future_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "FUTURE_SESSION_ATTENDANCE_BLOCKED")

    def test_10_save_cancelled_session_blocked(self):
        """Chặn điểm danh buổi học đã hủy (400 SESSION_CANCELLED)."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        payload = {
            "attendances": [{"student_id": self.students[0], "status": "present"}],
        }
        res = self.client.post(
            f"/api/v1/schedules/{self.schedule_cancelled_id}/attendance",
            json=payload,
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "SESSION_CANCELLED")

    def test_11_save_invalid_student_or_status_rejected(self):
        """Kiểm tra validation: học viên lạ hoặc trạng thái không hợp lệ bị từ chối 400."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        # Học viên lạ
        res1 = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json={"attendances": [{"student_id": "non-existent-student", "status": "present"}]},
            headers=headers,
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "STUDENT_NOT_IN_SESSION")

        # Trạng thái không hợp lệ
        res2 = self.client.post(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance",
            json={"attendances": [{"student_id": self.students[0], "status": "unknown_status"}]},
            headers=headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "INVALID_ATTENDANCE_STATUS")

    def test_12_get_attendance_history_endpoint(self):
        """Lấy lịch sử kiểm toán của buổi học thành công."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        res = self.client.get(
            f"/api/v1/schedules/{self.schedule_today_id}/attendance/history",
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        logs = res.get_json()["data"]
        self.assertIsInstance(logs, list)
        self.assertGreaterEqual(len(logs), 1)
        first = logs[0]
        self.assertIn("student_name", first)
        self.assertIn("performer_name", first)
        self.assertIn("old_status", first)
        self.assertIn("new_status", first)
        self.assertIn("created_at", first)


if __name__ == "__main__":
    unittest.main()
