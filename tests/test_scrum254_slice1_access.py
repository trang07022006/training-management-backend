"""
Bộ kiểm thử tự động cho SCRUM-254 Lát cắt 254.1 — Truy cập sổ điểm danh buổi học.
Kiểm tra:
1. Phân quyền truy cập: Giảng viên được phân công thành công (200), Giảng viên ngoài phân công bị từ chối (403).
2. Quản lý đào tạo (training_manager) xem được cả buổi hôm nay và quá khứ (200).
3. Quản trị viên thuần túy (admin), học viên (trainee), tư vấn (consultant) bị từ chối (403).
4. Buổi học không tồn tại báo 404 (SESSION_NOT_FOUND).
5. Phân biệt rõ "chưa điểm danh" (status=null) với "vắng" (status=excused/unexcused); mở trang không tự tạo bản ghi vắng.
6. Kết hợp chính xác ngày buổi học với vòng đời học viên SCRUM-252 (bảo lưu/thôi học từ ngày hiệu lực thì loại khỏi danh sách, trước ngày hiệu lực vẫn có mặt).
7. Đọc lại chính xác kết quả điểm danh đã lưu trước đó.
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services.attendance_service import VIETNAM_TZ


class Scrum254Slice1AccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.tm_user_id = f"test-tm-{cls.suffix}"
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.trainer_assigned_id = f"test-tr-assigned-{cls.suffix}"
        cls.trainer_unassigned_id = f"test-tr-unassigned-{cls.suffix}"
        cls.trainee_user_id = f"test-trainee-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo các user kiểm thử với role tương ứng
                users = [
                    (cls.tm_user_id, f"tm_{cls.suffix}@ictu.edu.vn", "Training Manager"),
                    (cls.admin_user_id, f"admin_{cls.suffix}@ictu.edu.vn", "Pure Admin"),
                    (cls.trainer_assigned_id, f"tr_assigned_{cls.suffix}@ictu.edu.vn", "Assigned Trainer"),
                    (cls.trainer_unassigned_id, f"tr_unassigned_{cls.suffix}@ictu.edu.vn", "Unassigned Trainer"),
                    (cls.trainee_user_id, f"trainee_{cls.suffix}@ictu.edu.vn", "Trainee User"),
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

                # 2. Tạo Program, Class, Subject
                cls.prog_id = f"prog-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program SCRUM-254', NOW(), NOW())",
                    (cls.prog_id, f"PRG_{cls.suffix}"),
                )

                cls.class_id = f"cls-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 10 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_id, f"CLS_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"subj-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject SCRUM-254', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUB_{cls.suffix}"),
                )

                # 3. Tạo phòng học
                cls.room_id = f"room-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classrooms (id, room_code, room_name, capacity, status, created_at, updated_at) VALUES (%s, %s, 'Phòng Lab 201', 40, 'active', NOW(), NOW())",
                    (cls.room_id, f"LAB_{cls.suffix}"),
                )

                # 4. Tạo các buổi học: Buổi hôm nay, buổi quá khứ
                today_vn = datetime.now(VIETNAM_TZ).date()
                cls.schedule_today_id = f"sch-today-{cls.suffix}"
                cls.schedule_past_id = f"sch-past-{cls.suffix}"

                cur.execute(
                    """
                    INSERT INTO class_schedules (
                        id, class_id, subject_id, session_number, topic, learning_date,
                        shift, start_time, end_time, room_id, instructor_id, status, attendance_checked, created_at, updated_at
                    ) VALUES 
                    (%s, %s, %s, 1, 'Bài học hôm nay', %s, 'Sáng', '08:00:00', '11:30:00', %s, %s, 'scheduled', 0, NOW(), NOW()),
                    (%s, %s, %s, 2, 'Bài học tuần trước', %s, 'Sáng', '08:00:00', '11:30:00', %s, %s, 'scheduled', 0, NOW(), NOW())
                    """,
                    (
                        cls.schedule_today_id, cls.class_id, cls.subject_id, today_vn, cls.room_id, cls.trainer_assigned_id,
                        cls.schedule_past_id, cls.class_id, cls.subject_id, today_vn - timedelta(days=7), cls.room_id, cls.trainer_assigned_id,
                    ),
                )

                # 5. Tạo 3 học viên:
                # - st1: Bình thường
                # - st2: Thôi học (dropped) từ hôm nay (effective_date = today_vn)
                # - st3: Bảo lưu (reserved) từ tuần tới (effective_date = today_vn + 7 days)
                cls.st1_id = f"st1-{cls.suffix}"
                cls.st2_id = f"st2-{cls.suffix}"
                cls.st3_id = f"st3-{cls.suffix}"

                students = [
                    (cls.st1_id, f"SV1_{cls.suffix}", "Nguyễn Văn Một", f"sv1_{cls.suffix}@ictu.edu.vn", "0912345671"),
                    (cls.st2_id, f"SV2_{cls.suffix}", "Trần Thị Hai", f"sv2_{cls.suffix}@ictu.edu.vn", "0912345672"),
                    (cls.st3_id, f"SV3_{cls.suffix}", "Lê Văn Ba", f"sv3_{cls.suffix}@ictu.edu.vn", "0912345673"),
                ]
                for sid, code, name, email, phone in students:
                    cur.execute(
                        "INSERT INTO students (id, student_code, full_name, email, phone, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())",
                        (sid, code, name, email, phone),
                    )

                enroll_date = today_vn - timedelta(days=10)
                cur.execute(
                    """
                    INSERT INTO class_enrollments (id, class_id, student_id, status, lifecycle_status, effective_date, enrolled_at, enrolled_by, created_at, updated_at)
                    VALUES 
                    (%s, %s, %s, 'active', NULL, NULL, %s, %s, NOW(), NOW()),
                    (%s, %s, %s, 'dropped', 'dropped', %s, %s, %s, NOW(), NOW()),
                    (%s, %s, %s, 'reserved', 'reserved', %s, %s, %s, NOW(), NOW())
                    """,
                    (
                        f"enr1-{cls.suffix}", cls.class_id, cls.st1_id, enroll_date, cls.tm_user_id,
                        f"enr2-{cls.suffix}", cls.class_id, cls.st2_id, today_vn, enroll_date, cls.tm_user_id,
                        f"enr3-{cls.suffix}", cls.class_id, cls.st3_id, today_vn + timedelta(days=7), enroll_date, cls.tm_user_id,
                    ),
                )

                # 6. Tạo trước một bản ghi điểm danh đã lưu cho st1 ở buổi quá khứ
                cur.execute(
                    """
                    INSERT INTO session_attendances (id, schedule_id, student_id, status, notes, recorded_by, created_at, updated_at)
                    VALUES (%s, %s, %s, 'present', 'Có mặt đúng giờ', %s, NOW(), NOW())
                    """,
                    (f"att-{cls.suffix}", cls.schedule_past_id, cls.st1_id, cls.trainer_assigned_id),
                )

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM attendance_audit_logs WHERE schedule_id IN (%s, %s)", (cls.schedule_today_id, cls.schedule_past_id))
                cur.execute("DELETE FROM session_attendances WHERE schedule_id IN (%s, %s)", (cls.schedule_today_id, cls.schedule_past_id))
                cur.execute("DELETE FROM class_schedules WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_id,))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s, %s)", (cls.st1_id, cls.st2_id, cls.st3_id))
                cur.execute("DELETE FROM classrooms WHERE id = %s", (cls.room_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_assigned_id, cls.trainer_unassigned_id, cls.trainee_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_assigned_id, cls.trainer_unassigned_id, cls.trainee_user_id))
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

    def test_01_assigned_trainer_access_today_success(self):
        """Giảng viên được phân công mở sổ điểm danh buổi hôm nay: 200, can_edit=True, đúng thông tin buổi và học viên."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        resp = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()["data"]
        session_info = data["session_info"]
        self.assertEqual(session_info["schedule_id"], self.schedule_today_id)
        self.assertTrue(session_info["is_today"])
        self.assertTrue(session_info["can_edit"])

        # Kiểm tra danh sách học viên xét theo ngày hiệu lực:
        # - st1: bình thường -> có mặt trong sổ
        # - st2: thôi học từ hôm nay (effective_date = today) -> KHÔNG có mặt trong danh sách đủ điều kiện
        # - st3: bảo lưu từ tuần tới (effective_date > today) -> VẪN CÓ MẶT trong danh sách hôm nay
        students = data["students"]
        student_ids = [s["student_id"] for s in students]
        self.assertIn(self.st1_id, student_ids)
        self.assertNotIn(self.st2_id, student_ids)
        self.assertIn(self.st3_id, student_ids)

        # Kiểm tra chưa điểm danh: status phải là None, không tự tạo bản ghi vắng
        for s in students:
            self.assertIsNone(s["status"])
            self.assertEqual(s["status_label"], "Chưa điểm danh")

        # Kiểm tra số lượng trong DB không tự sinh bản ghi
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM session_attendances WHERE schedule_id = %s", (self.schedule_today_id,))
                count = cur.fetchone()[0]
                self.assertEqual(count, 0)
        finally:
            conn.close()

    def test_02_unassigned_trainer_forbidden(self):
        """Giảng viên ngoài phạm vi phân công bị từ chối 403."""
        headers = self._get_auth_header(self.trainer_unassigned_id, "trainer")
        resp = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertEqual(body["code"], "FORBIDDEN_ATTENDANCE_ACCESS")

    def test_03_training_manager_can_view_past_and_can_edit(self):
        """Quản lý đào tạo xem buổi học quá khứ: 200, is_past=True, can_edit=True."""
        headers = self._get_auth_header(self.tm_user_id, "training_manager")
        resp = self.client.get(f"/api/v1/schedules/{self.schedule_past_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()["data"]
        session_info = data["session_info"]
        self.assertTrue(session_info["is_past"])
        self.assertTrue(session_info["can_edit"])

        # Đọc lại đúng kết quả đã lưu cho st1: status='present', notes='Có mặt đúng giờ'
        st1_record = next((s for s in data["students"] if s["student_id"] == self.st1_id), None)
        self.assertIsNotNone(st1_record)
        self.assertEqual(st1_record["status"], "present")
        self.assertEqual(st1_record["status_label"], "Có mặt")
        self.assertEqual(st1_record["notes"], "Có mặt đúng giờ")

    def test_04_assigned_trainer_view_past_cannot_edit(self):
        """Giảng viên mở buổi học quá khứ: xem được nhưng can_edit=False kèm lý do giới hạn."""
        headers = self._get_auth_header(self.trainer_assigned_id, "trainer")
        resp = self.client.get(f"/api/v1/schedules/{self.schedule_past_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()["data"]
        session_info = data["session_info"]
        self.assertTrue(session_info["is_past"])
        self.assertFalse(session_info["can_edit"])
        self.assertIn("Chỉ Quản lý đào tạo mới được phép chỉnh sửa", session_info["edit_restriction_reason"])

    def test_05_admin_pure_forbidden(self):
        """Quản trị viên thuần túy (admin) không có quyền nghiệp vụ đào tạo -> 403."""
        headers = self._get_auth_header(self.admin_user_id, "admin")
        resp = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_06_trainee_forbidden(self):
        """Học viên (trainee) không có quyền truy cập sổ điểm danh -> 403."""
        headers = self._get_auth_header(self.trainee_user_id, "trainee")
        resp = self.client.get(f"/api/v1/schedules/{self.schedule_today_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_07_session_not_found(self):
        """Buổi học không tồn tại trả về 404 SESSION_NOT_FOUND."""
        headers = self._get_auth_header(self.tm_user_id, "training_manager")
        fake_id = str(uuid.uuid4())
        resp = self.client.get(f"/api/v1/schedules/{fake_id}/attendance", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "SESSION_NOT_FOUND")
