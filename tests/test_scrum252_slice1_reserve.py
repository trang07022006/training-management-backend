"""
Bộ kiểm thử tự động cho SCRUM-252 Lát cắt 252.1 — Bảo lưu theo ngày hiệu lực.
Kiểm tra toàn diện:
1. Quyền nghiệp vụ: Training Manager thành công (200), Admin thuần túy/Trainer/Trainee bị từ chối (403).
2. Dữ liệu hợp lệ: Ngày hiệu lực hôm nay, tương lai, quá khứ (không trước khai giảng).
3. Validate: Thiếu lý do, lý do toàn khoảng trắng, thiếu ngày, ngày sai định dạng, ngày trước ngày khai giảng.
4. Chống lặp: Thao tác trùng báo ALREADY_RESERVED.
5. Học viên nhiều lớp: Bảo lưu 1 lớp không ảnh hưởng lớp còn lại.
6. Ranh giới danh sách điểm danh (eligible-students):
   - Trước ngày hiệu lực: học viên CÓ mặt.
   - Từ ngày hiệu lực trở đi: học viên KHÔNG có mặt.
   - Ngày hiệu lực tương lai: không làm mất học viên khỏi danh sách hôm nay.
7. Lịch sử vòng đời: Bản ghi được ghi nhận đúng trong student_lifecycle_history.
"""

from datetime import date, datetime, timedelta
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app
from app.services import authorization_service


class Scrum252Slice1ReserveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        # Tạo định danh test duy nhất
        cls.suffix = uuid.uuid4().hex[:8]
        cls.tm_user_id = f"test-tm-{cls.suffix}"
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.trainer_user_id = f"test-trainer-{cls.suffix}"
        cls.trainee_user_id = f"test-trainee-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo các user kiểm thử với các role khác nhau
                users = [
                    (cls.tm_user_id, f"tm_{cls.suffix}@ictu.edu.vn", "Training Manager User"),
                    (cls.admin_user_id, f"admin_{cls.suffix}@ictu.edu.vn", "Admin User"),
                    (cls.trainer_user_id, f"trainer_{cls.suffix}@ictu.edu.vn", "Trainer User"),
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
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.trainee_user_id,))

                # 2. Tạo Training Program & Classes
                cls.prog_id = f"prog-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program Test', NOW(), NOW())",
                    (cls.prog_id, f"PRG_{cls.suffix}"),
                )

                cls.class_1_id = f"cls1-{cls.suffix}"
                cls.class_2_id = f"cls2-{cls.suffix}"
                cls.start_date = date.today() - timedelta(days=10)
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_1_id, f"C1_{cls.suffix}", cls.prog_id, cls.start_date),
                )
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_2_id, f"C2_{cls.suffix}", cls.prog_id, cls.start_date),
                )

                # 3. Tạo Student tham gia 2 lớp
                cls.student_id = f"st-{cls.suffix}"
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, phone, email, program_id, status, created_at, updated_at) VALUES (%s, %s, 'Student Test', '0912345678', %s, %s, 'enrolled', NOW(), NOW())",
                    (cls.student_id, f"STU_{cls.suffix}", f"stu_{cls.suffix}@ictu.edu.vn", cls.prog_id),
                )

                # 4. Ghi danh vào cả 2 lớp (bắt đầu từ ngày start_date)
                cls.enr_1_id = f"enr1-{cls.suffix}"
                cls.enr_2_id = f"enr2-{cls.suffix}"
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_1_id, cls.class_1_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_2_id, cls.class_2_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )

                # Tạo auth_sessions cho các user
                cls.sess_tm = f"sess_tm_{cls.suffix}"
                cls.sess_admin = f"sess_admin_{cls.suffix}"
                cls.sess_trainer = f"sess_trainer_{cls.suffix}"
                cls.sess_trainee = f"sess_trainee_{cls.suffix}"

                sessions = [
                    (cls.sess_tm, cls.tm_user_id),
                    (cls.sess_admin, cls.admin_user_id),
                    (cls.sess_trainer, cls.trainer_user_id),
                    (cls.sess_trainee, cls.trainee_user_id),
                ]
                for sid, uid in sessions:
                    cur.execute(
                        """
                        INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                        VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                        """,
                        (sid, uid, f"ref_{sid}"),
                    )

                conn.commit()
        finally:
            conn.close()

        # Tạo JWT token có claims và session id
        with cls.app.app_context():
            cls.tm_token = create_access_token(
                identity=cls.tm_user_id,
                additional_claims={"roles": ["training_manager"], "sid": cls.sess_tm},
            )
            cls.admin_token = create_access_token(
                identity=cls.admin_user_id,
                additional_claims={"roles": ["admin"], "sid": cls.sess_admin},
            )
            cls.trainer_token = create_access_token(
                identity=cls.trainer_user_id,
                additional_claims={"roles": ["trainer"], "sid": cls.sess_trainer},
            )
            cls.trainee_token = create_access_token(
                identity=cls.trainee_user_id,
                additional_claims={"roles": ["trainee"], "sid": cls.sess_trainee},
            )

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM student_lifecycle_history WHERE student_id = %s", (cls.student_id,))
                cur.execute("DELETE FROM class_enrollments WHERE student_id = %s", (cls.student_id,))
                cur.execute("DELETE FROM students WHERE id = %s", (cls.student_id,))
                cur.execute("DELETE FROM classes WHERE id IN (%s, %s)", (cls.class_1_id, cls.class_2_id))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM auth_sessions WHERE session_id IN (%s, %s, %s, %s)", (cls.sess_tm, cls.sess_admin, cls.sess_trainer, cls.sess_trainee))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_user_id, cls.trainee_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_user_id, cls.trainee_user_id))
                conn.commit()
        finally:
            conn.close()

    def test_01_rbac_permissions_enforced(self):
        """TC252-01: Chỉ Quản lý đào tạo (training_manager) mới được phép gọi API bảo lưu."""
        payload = {
            "class_id": self.class_1_id,
            "effective_date": (date.today() + timedelta(days=5)).isoformat(),
            "reason": "Lý do cá nhân",
        }

        # 1. Admin thuần túy -> 403 Forbidden
        res_admin = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(res_admin.status_code, 403)

        # 2. Giảng viên -> 403 Forbidden
        res_trainer = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json=payload,
            headers={"Authorization": f"Bearer {self.trainer_token}"},
        )
        self.assertEqual(res_trainer.status_code, 403)

        # 3. Học viên -> 403 Forbidden
        res_trainee = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json=payload,
            headers={"Authorization": f"Bearer {self.trainee_token}"},
        )
        self.assertEqual(res_trainee.status_code, 403)

    def test_02_validation_missing_or_whitespace_reason(self):
        """TC252-02: Bắt buộc phải có lý do và không được chỉ chứa khoảng trắng."""
        # Thiếu reason
        res1 = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={"class_id": self.class_1_id, "effective_date": date.today().isoformat()},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "MISSING_REASON")

        # Reason toàn khoảng trắng
        res2 = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={"class_id": self.class_1_id, "effective_date": date.today().isoformat(), "reason": "   \t \n "},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "MISSING_REASON")

    def test_03_validation_effective_date(self):
        """TC252-03: Kiểm tra định dạng ngày hiệu lực và ngày không được trước khai giảng."""
        # Thiếu ngày hiệu lực
        res1 = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={"class_id": self.class_1_id, "reason": "Bảo lưu nghỉ thai sản"},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "MISSING_EFFECTIVE_DATE")

        # Ngày sai định dạng
        res2 = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={"class_id": self.class_1_id, "effective_date": "19-10-2026", "reason": "Bảo lưu"},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "INVALID_EFFECTIVE_DATE_FORMAT")

        # Ngày trước ngày khai giảng lớp (start_date - 1 day)
        before_start = (self.start_date - timedelta(days=1)).isoformat()
        res3 = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={"class_id": self.class_1_id, "effective_date": before_start, "reason": "Bảo lưu quá sớm"},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "EFFECTIVE_DATE_BEFORE_START")

    def test_04_reserve_future_effective_date_and_attendance_boundary(self):
        """
        TC252-04: Bảo lưu với ngày hiệu lực tương lai.
        - Ngày hiệu lực tương lai: trạng thái pending, không làm mất học viên khỏi danh sách hôm nay.
        - Trước ngày hiệu lực: học viên CÓ trong danh sách điểm danh.
        - Từ ngày hiệu lực: học viên KHÔNG nằm trong danh sách điểm danh.
        - Lớp thứ hai của học viên hoàn toàn KHÔNG bị ảnh hưởng.
        """
        future_effective = date.today() + timedelta(days=5)
        before_effective = future_effective - timedelta(days=1)
        on_effective = future_effective
        after_effective = future_effective + timedelta(days=2)

        res = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={
                "class_id": self.class_1_id,
                "effective_date": future_effective.isoformat(),
                "reason": "Bảo lưu do đi công tác nước ngoài từ tuần sau",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["action_type"], "reserve")
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["enrollment_status"], "enrolled")  # Vẫn enrolled hôm nay

        # 1. Kiểm tra danh sách điểm danh ngày HÔM NAY (< future_effective): VẪN CÓ MẶT
        res_today = self.client.get(
            f"/api/v1/classes/{self.class_1_id}/eligible-students?session_date={date.today().isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_today.status_code, 200)
        st_ids_today = [s["student_id"] for s in res_today.get_json()["data"]["students"]]
        self.assertIn(self.student_id, st_ids_today)

        # 2. Kiểm tra danh sách điểm danh ngày trước ngày hiệu lực: VẪN CÓ MẶT
        res_before = self.client.get(
            f"/api/v1/classes/{self.class_1_id}/eligible-students?session_date={before_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_before.status_code, 200)
        st_ids_before = [s["student_id"] for s in res_before.get_json()["data"]["students"]]
        self.assertIn(self.student_id, st_ids_before)

        # 3. Kiểm tra danh sách điểm danh ĐÚNG NGÀY HIỆU LỰC: KHÔNG CÒN XUẤT HIỆN
        res_on = self.client.get(
            f"/api/v1/classes/{self.class_1_id}/eligible-students?session_date={on_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_on.status_code, 200)
        st_ids_on = [s["student_id"] for s in res_on.get_json()["data"]["students"]]
        self.assertNotIn(self.student_id, st_ids_on)

        # 4. Kiểm tra danh sách điểm danh SAU NGÀY HIỆU LỰC: KHÔNG CÒN XUẤT HIỆN
        res_after = self.client.get(
            f"/api/v1/classes/{self.class_1_id}/eligible-students?session_date={after_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_after.status_code, 200)
        st_ids_after = [s["student_id"] for s in res_after.get_json()["data"]["students"]]
        self.assertNotIn(self.student_id, st_ids_after)

        # 5. Kiểm tra LỚP THỨ HAI (class_2): Học viên VẪN CÓ MẶT cả trước và sau ngày hiệu lực
        res_cls2 = self.client.get(
            f"/api/v1/classes/{self.class_2_id}/eligible-students?session_date={after_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_cls2.status_code, 200)
        st_ids_cls2 = [s["student_id"] for s in res_cls2.get_json()["data"]["students"]]
        self.assertIn(self.student_id, st_ids_cls2)

    def test_05_duplicate_reservation_blocked(self):
        """TC252-05: Không cho phép bảo lưu trùng lặp khi lớp đã được bảo lưu."""
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/reserve",
            json={
                "class_id": self.class_1_id,
                "effective_date": (date.today() + timedelta(days=10)).isoformat(),
                "reason": "Yêu cầu bảo lưu lần 2 trùng lặp",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "ALREADY_RESERVED")

    def test_06_lifecycle_history_audit_trail(self):
        """TC252-06: Xác nhận thao tác bảo lưu đã được ghi lại đầy đủ vào bảng lịch sử."""
        res = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertGreaterEqual(len(items), 1)

        reserve_entry = next((item for item in items if item["action_type"] == "reserve"), None)
        self.assertIsNotNone(reserve_entry)
        self.assertEqual(reserve_entry["source_class_id"], self.class_1_id)
        self.assertEqual(reserve_entry["performed_by"], self.tm_user_id)
        self.assertIn("công tác nước ngoài", reserve_entry["reason"])


if __name__ == "__main__":
    unittest.main()
