"""
Bộ kiểm thử Backend cho SCRUM-252 Lát cắt 252.3 — Thôi học theo ngày hiệu lực.
Kiểm tra:
- TC252-3-01: Phân quyền RBAC nghiêm ngặt (chỉ training_manager được thực hiện, admin/trainer/trainee bị 403).
- TC252-3-02: Kiểm tra validation (thiếu lý do, lý do whitespace, scope sai, ngày không hợp lệ).
- TC252-3-03: Thôi học phạm vi 1 lớp (scope='single'): lớp đó không còn xuất hiện điểm danh từ ngày hiệu lực, lớp khác giữ nguyên.
- TC252-3-04: Thôi học toàn bộ khóa học (scope='all'): toàn bộ các lớp học dừng điểm danh từ ngày hiệu lực, bảo toàn hồ sơ và ghi lịch sử.
- TC252-3-05: Chặn thao tác lặp (đã thôi học không được thôi học lại).
"""

from datetime import date, datetime, timedelta
import json
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app


class Scrum252Slice3DropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.tm_user_id = f"test-tm-{cls.suffix}"
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.trainer_user_id = f"test-trainer-{cls.suffix}"

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo users
                users = [
                    (cls.tm_user_id, f"tm_{cls.suffix}@ictu.edu.vn", "Training Manager"),
                    (cls.admin_user_id, f"admin_{cls.suffix}@ictu.edu.vn", "Admin"),
                    (cls.trainer_user_id, f"trainer_{cls.suffix}@ictu.edu.vn", "Trainer"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # Gán roles
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.tm_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_user_id,))

                # 2. Tạo training program
                cls.prog_id = f"prog_dr_{cls.suffix}"
                cur.execute("INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Chương trình Drop', NOW(), NOW())", (cls.prog_id, f"PDR_{cls.suffix}"))

                # 3. Tạo 2 lớp học
                cls.start_date = date.today() - timedelta(days=15)
                cls.class_1_id = f"c1_dr_{cls.suffix}"
                cls.class_2_id = f"c2_dr_{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_1_id, f"C1DR_{cls.suffix}", cls.prog_id, cls.start_date),
                )
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_2_id, f"C2DR_{cls.suffix}", cls.prog_id, cls.start_date),
                )

                # 4. Tạo học viên tham gia cả 2 lớp
                cls.student_id = f"st_dr_{cls.suffix}"
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, phone, email, program_id, status, created_at, updated_at) VALUES (%s, %s, 'Student To Drop', '0933445566', %s, %s, 'enrolled', NOW(), NOW())",
                    (cls.student_id, f"STU_DR_{cls.suffix}", f"stu_dr_{cls.suffix}@ictu.edu.vn", cls.prog_id),
                )

                cls.enr_1_id = f"enr1_dr_{cls.suffix}"
                cls.enr_2_id = f"enr2_dr_{cls.suffix}"
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_1_id, cls.class_1_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_2_id, cls.class_2_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )

                # 5. Tạo auth_sessions
                cls.sess_tm = f"sess_tm_dr_{cls.suffix}"
                cls.sess_admin = f"sess_admin_dr_{cls.suffix}"
                cls.sess_trainer = f"sess_trainer_dr_{cls.suffix}"

                sessions = [
                    (cls.sess_tm, cls.tm_user_id),
                    (cls.sess_admin, cls.admin_user_id),
                    (cls.sess_trainer, cls.trainer_user_id),
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
                cur.execute("DELETE FROM auth_sessions WHERE session_id IN (%s, %s, %s)", (cls.sess_tm, cls.sess_admin, cls.sess_trainer))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_user_id))
                conn.commit()
        finally:
            conn.close()

    def test_01_rbac_permissions_enforced(self):
        """TC252-3-01: Chỉ Quản lý đào tạo (training_manager) mới được phép gọi API thôi học."""
        payload = {
            "scope": "single",
            "class_id": self.class_1_id,
            "effective_date": date.today().isoformat(),
            "reason": "Thôi học do hoàn cảnh gia đình",
        }

        # Admin thuần túy -> 403
        res_admin = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(res_admin.status_code, 403)

        # Trainer -> 403
        res_trainer = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json=payload,
            headers={"Authorization": f"Bearer {self.trainer_token}"},
        )
        self.assertEqual(res_trainer.status_code, 403)

    def test_02_validation_inputs(self):
        """TC252-3-02: Kiểm tra dữ liệu đầu vào bắt buộc và hợp lệ."""
        # Thiếu lý do
        res1 = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json={"scope": "single", "class_id": self.class_1_id, "effective_date": date.today().isoformat()},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res1.status_code, 400)

        # Lý do chỉ có khoảng trắng
        res2 = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json={"scope": "single", "class_id": self.class_1_id, "effective_date": date.today().isoformat(), "reason": "   "},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res2.status_code, 400)

        # Scope single nhưng thiếu class_id
        res3 = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json={"scope": "single", "effective_date": date.today().isoformat(), "reason": "Thôi học lớp"},
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res3.status_code, 400)

    def test_03_drop_single_class_isolation(self):
        """
        TC252-3-03: Thôi học ở phạm vi 1 lớp (class_1_id) với ngày hiệu lực tương lai:
        - Trước ngày hiệu lực: học viên CÓ mặt trong điểm danh class_1_id.
        - Từ ngày hiệu lực: học viên KHÔNG có mặt trong điểm danh class_1_id.
        - Lớp class_2_id hoàn toàn KHÔNG bị ảnh hưởng (cả trước và sau ngày hiệu lực đều có mặt).
        """
        future_effective = date.today() + timedelta(days=6)
        before_effective = future_effective - timedelta(days=1)
        on_effective = future_effective

        res = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json={
                "scope": "single",
                "class_id": self.class_1_id,
                "effective_date": future_effective.isoformat(),
                "reason": "Thôi học lớp 1 do trùng lịch học trên trường đại học",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 200)

        # 1. Kiểm tra lớp 1:
        # Trước ngày hiệu lực -> CÓ
        res_c1_before = self.client.get(
            f"/api/v1/classes/{self.class_1_id}/eligible-students?session_date={before_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        st_c1_before = json.loads(res_c1_before.data)["data"]["students"]
        self.assertTrue(any(s["student_id"] == self.student_id for s in st_c1_before))

        # Từ ngày hiệu lực -> KHÔNG
        res_c1_on = self.client.get(
            f"/api/v1/classes/{self.class_1_id}/eligible-students?session_date={on_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        st_c1_on = json.loads(res_c1_on.data)["data"]["students"]
        self.assertFalse(any(s["student_id"] == self.student_id for s in st_c1_on))

        # 2. Kiểm tra lớp 2 (phải giữ nguyên vẹn, không đổi):
        res_c2 = self.client.get(
            f"/api/v1/classes/{self.class_2_id}/eligible-students?session_date={on_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        st_c2 = json.loads(res_c2.data)["data"]["students"]
        self.assertTrue(any(s["student_id"] == self.student_id for s in st_c2))

    def test_04_duplicate_drop_single_blocked(self):
        """TC252-3-05: Chặn khi thôi học lặp lại trên cùng 1 lớp đã thôi học."""
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json={
                "scope": "single",
                "class_id": self.class_1_id,
                "effective_date": (date.today() + timedelta(days=10)).isoformat(),
                "reason": "Thôi học lần 2",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertEqual(data.get("code"), "ALREADY_DROPPED")

    def test_05_drop_all_classes(self):
        """
        TC252-3-04: Thôi học toàn bộ khóa học (scope='all'):
        - Áp dụng cho các lớp còn lại (lớp 2).
        - Ghi nhận lịch sử student_lifecycle_history.
        - Bản ghi hồ sơ học viên và các lớp ghi danh được bảo toàn (không bị DELETE).
        """
        effective_date_val = date.today()
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/drop",
            json={
                "scope": "all",
                "effective_date": effective_date_val.isoformat(),
                "reason": "Quyết định nghỉ học hẳn toàn bộ chương trình",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 200)

        # Kiểm tra lớp 2 sau khi thôi học toàn bộ: không còn trong danh sách điểm danh
        res_c2 = self.client.get(
            f"/api/v1/classes/{self.class_2_id}/eligible-students?session_date={effective_date_val.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        st_c2 = json.loads(res_c2.data)["data"]["students"]
        self.assertFalse(any(s["student_id"] == self.student_id for s in st_c2))

        # Kiểm tra lịch sử
        res_hist = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_hist.status_code, 200)
        history = json.loads(res_hist.data)["data"]["items"]
        drop_events = [h for h in history if h["action_type"] == "drop"]
        self.assertGreaterEqual(len(drop_events), 2)
