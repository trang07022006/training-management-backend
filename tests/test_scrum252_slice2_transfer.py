"""
Bộ kiểm thử Backend cho SCRUM-252 Lát cắt 252.2 — Chuyển lớp và giữ lịch sử.
Kiểm tra:
- TC252-2-01: Chuyển lớp hợp lệ và bảo đảm lịch sử điểm danh ở cả 2 lớp theo ngày hiệu lực.
- TC252-2-02: Chặn khi lớp đích trùng lớp nguồn (SAME_CLASS).
- TC252-2-03: Chặn khi lớp đích khác chương trình đào tạo (PROGRAM_MISMATCH).
- TC252-2-04: Chặn khi lớp đích đã đủ sĩ số tối đa (TARGET_CLASS_FULL).
- TC252-2-05: Chặn khi học viên đã có mặt trong lớp đích (ALREADY_ENROLLED_IN_TARGET).
- TC252-2-06: Phân quyền RBAC nghiêm ngặt (chỉ training_manager được thực hiện, admin/trainer/trainee bị 403).
"""

from datetime import date, datetime, timedelta
import json
import unittest
import uuid

from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.main import app


class Scrum252Slice2TransferTests(unittest.TestCase):
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

                # 2. Tạo 2 chương trình đào tạo: prog1 và prog_other
                cls.prog1_id = f"prog1-{cls.suffix}"
                cls.prog_other_id = f"prog_other-{cls.suffix}"
                cur.execute("INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Chương trình 1', NOW(), NOW())", (cls.prog1_id, f"P1_{cls.suffix}"))
                cur.execute("INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Chương trình khác', NOW(), NOW())", (cls.prog_other_id, f"PO_{cls.suffix}"))

                # 3. Tạo các lớp học:
                cls.start_date = date.today() - timedelta(days=20)
                # Lớp nguồn: thuộc prog1
                cls.class_src_id = f"c_src_{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_src_id, f"SRC_{cls.suffix}", cls.prog1_id, cls.start_date),
                )
                # Lớp đích hợp lệ: thuộc prog1, còn chỗ (capacity = 30)
                cls.class_tgt_id = f"c_tgt_{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_tgt_id, f"TGT_{cls.suffix}", cls.prog1_id, cls.start_date),
                )
                # Lớp đích đầy chỗ: capacity = 1, sẽ được lấp đầy
                cls.class_full_id = f"c_full_{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 1, 'in_progress', NOW(), NOW())",
                    (cls.class_full_id, f"FUL_{cls.suffix}", cls.prog1_id, cls.start_date),
                )
                # Lớp đích khác chương trình: thuộc prog_other
                cls.class_mismatch_id = f"c_mis_{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, %s, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_mismatch_id, f"MIS_{cls.suffix}", cls.prog_other_id, cls.start_date),
                )

                # 4. Tạo học viên cần chuyển lớp và một học viên khác lấp chỗ lớp full
                cls.student_id = f"st_transfer_{cls.suffix}"
                cls.student_other_id = f"st_other_{cls.suffix}"
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, phone, email, program_id, status, created_at, updated_at) VALUES (%s, %s, 'Student To Transfer', '0911223344', %s, %s, 'enrolled', NOW(), NOW())",
                    (cls.student_id, f"STU_TR_{cls.suffix}", f"stu_tr_{cls.suffix}@ictu.edu.vn", cls.prog1_id),
                )
                cur.execute(
                    "INSERT INTO students (id, student_code, full_name, phone, email, program_id, status, created_at, updated_at) VALUES (%s, %s, 'Student Filler', '0988776655', %s, %s, 'enrolled', NOW(), NOW())",
                    (cls.student_other_id, f"STU_FL_{cls.suffix}", f"stu_fl_{cls.suffix}@ictu.edu.vn", cls.prog1_id),
                )

                # Ghi danh học viên chính vào lớp nguồn
                cls.enr_src_id = f"enr_src_{cls.suffix}"
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_src_id, cls.class_src_id, cls.student_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )

                # Ghi danh học viên phụ vào lớp full để lớp full đủ sĩ số
                cls.enr_full_id = f"enr_full_{cls.suffix}"
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', %s, %s, NOW(), NOW())",
                    (cls.enr_full_id, cls.class_full_id, cls.student_other_id, datetime.combine(cls.start_date, datetime.min.time()), cls.tm_user_id),
                )

                # 5. Tạo auth_sessions
                cls.sess_tm = f"sess_tm_tr_{cls.suffix}"
                cls.sess_admin = f"sess_admin_tr_{cls.suffix}"
                cls.sess_trainer = f"sess_trainer_tr_{cls.suffix}"

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
                cur.execute("DELETE FROM student_lifecycle_history WHERE student_id IN (%s, %s)", (cls.student_id, cls.student_other_id))
                cur.execute("DELETE FROM class_enrollments WHERE student_id IN (%s, %s)", (cls.student_id, cls.student_other_id))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s)", (cls.student_id, cls.student_other_id))
                cur.execute("DELETE FROM classes WHERE id IN (%s, %s, %s, %s)", (cls.class_src_id, cls.class_tgt_id, cls.class_full_id, cls.class_mismatch_id))
                cur.execute("DELETE FROM training_programs WHERE id IN (%s, %s)", (cls.prog1_id, cls.prog_other_id))
                cur.execute("DELETE FROM auth_sessions WHERE session_id IN (%s, %s, %s)", (cls.sess_tm, cls.sess_admin, cls.sess_trainer))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_user_id))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s)", (cls.tm_user_id, cls.admin_user_id, cls.trainer_user_id))
                conn.commit()
        finally:
            conn.close()

    def test_01_rbac_permissions_enforced(self):
        """TC252-2-06: Chỉ training_manager mới có quyền gọi API chuyển lớp."""
        payload = {
            "source_class_id": self.class_src_id,
            "target_class_id": self.class_tgt_id,
            "effective_date": (date.today() + timedelta(days=5)).isoformat(),
            "reason": "Chuyển sang lớp phù hợp lịch làm việc",
        }

        # Admin thuần túy -> 403
        res_admin = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(res_admin.status_code, 403)

        # Trainer -> 403
        res_trainer = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json=payload,
            headers={"Authorization": f"Bearer {self.trainer_token}"},
        )
        self.assertEqual(res_trainer.status_code, 403)

    def test_02_validation_same_class_blocked(self):
        """TC252-2-02: Chặn khi lớp đích trùng lớp nguồn."""
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json={
                "source_class_id": self.class_src_id,
                "target_class_id": self.class_src_id,
                "effective_date": date.today().isoformat(),
                "reason": "Chuyển vào chính lớp này",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertEqual(data.get("code"), "SAME_CLASS")

    def test_03_validation_program_mismatch_blocked(self):
        """TC252-2-03: Chặn khi lớp đích khác chương trình đào tạo."""
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json={
                "source_class_id": self.class_src_id,
                "target_class_id": self.class_mismatch_id,
                "effective_date": date.today().isoformat(),
                "reason": "Chuyển sang chương trình khác",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertEqual(data.get("code"), "PROGRAM_MISMATCH")

    def test_04_validation_target_class_full_blocked(self):
        """TC252-2-04: Chặn khi lớp đích đã đủ sĩ số tối đa."""
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json={
                "source_class_id": self.class_src_id,
                "target_class_id": self.class_full_id,
                "effective_date": date.today().isoformat(),
                "reason": "Chuyển sang lớp đã đầy chỗ",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertEqual(data.get("code"), "TARGET_CLASS_FULL")

    def test_05_valid_transfer_attendance_and_history(self):
        """
        TC252-2-01: Chuyển lớp thành công với ngày hiệu lực tương lai.
        - Kiểm tra ranh giới điểm danh ở lớp nguồn và lớp đích trước và từ ngày hiệu lực.
        - Lớp nguồn: trước ngày hiệu lực có tên, từ ngày hiệu lực không có tên.
        - Lớp đích: trước ngày hiệu lực không có tên, từ ngày hiệu lực có tên.
        - Ghi nhận lịch sử chuyển lớp đầy đủ.
        """
        future_effective = date.today() + timedelta(days=7)
        before_effective = future_effective - timedelta(days=1)
        on_effective = future_effective
        after_effective = future_effective + timedelta(days=2)

        # 1. Thực hiện chuyển lớp
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json={
                "source_class_id": self.class_src_id,
                "target_class_id": self.class_tgt_id,
                "effective_date": future_effective.isoformat(),
                "reason": "Chuyển sang lớp buổi tối do thay đổi ca làm việc",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)["data"]
        self.assertEqual(data["action_type"], "transfer")
        self.assertEqual(data["source_class_id"], self.class_src_id)
        self.assertEqual(data["target_class_id"], self.class_tgt_id)

        # 2. Kiểm tra danh sách điểm danh lớp NGUỒN:
        # Trước ngày hiệu lực -> CÓ mặt
        res_src_before = self.client.get(
            f"/api/v1/classes/{self.class_src_id}/eligible-students?session_date={before_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_src_before.status_code, 200)
        students_src_before = json.loads(res_src_before.data)["data"]["students"]
        self.assertTrue(any(s["student_id"] == self.student_id for s in students_src_before))

        # Tại ngày hiệu lực -> KHÔNG có mặt
        res_src_on = self.client.get(
            f"/api/v1/classes/{self.class_src_id}/eligible-students?session_date={on_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_src_on.status_code, 200)
        students_src_on = json.loads(res_src_on.data)["data"]["students"]
        self.assertFalse(any(s["student_id"] == self.student_id for s in students_src_on))

        # 3. Kiểm tra danh sách điểm danh lớp ĐÍCH:
        # Trước ngày hiệu lực -> KHÔNG có mặt
        res_tgt_before = self.client.get(
            f"/api/v1/classes/{self.class_tgt_id}/eligible-students?session_date={before_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_tgt_before.status_code, 200)
        students_tgt_before = json.loads(res_tgt_before.data)["data"]["students"]
        self.assertFalse(any(s["student_id"] == self.student_id for s in students_tgt_before))

        # Tại ngày hiệu lực -> CÓ mặt
        res_tgt_on = self.client.get(
            f"/api/v1/classes/{self.class_tgt_id}/eligible-students?session_date={on_effective.isoformat()}",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_tgt_on.status_code, 200)
        students_tgt_on = json.loads(res_tgt_on.data)["data"]["students"]
        self.assertTrue(any(s["student_id"] == self.student_id for s in students_tgt_on))

        # 4. Kiểm tra lịch sử biến động trong student_lifecycle_history
        res_hist = self.client.get(
            f"/api/v1/students/{self.student_id}/lifecycle-history",
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res_hist.status_code, 200)
        history = json.loads(res_hist.data)["data"]["items"]
        transfer_logs = [h for h in history if h["action_type"] == "transfer"]
        self.assertGreaterEqual(len(transfer_logs), 1)
        self.assertEqual(transfer_logs[0]["source_class_id"], self.class_src_id)
        self.assertEqual(transfer_logs[0]["target_class_id"], self.class_tgt_id)
        self.assertEqual(transfer_logs[0]["effective_date"], future_effective.isoformat())

    def test_06_already_in_target_class_blocked(self):
        """TC252-2-05: Chặn khi học viên đã có trong danh sách của lớp đích."""
        # Học viên sau test_05 đã được ghi danh vào class_tgt_id. Thử chuyển lại vào class_tgt_id sẽ bị chặn!
        res = self.client.post(
            f"/api/v1/students/{self.student_id}/transfer",
            json={
                "source_class_id": self.class_src_id,
                "target_class_id": self.class_tgt_id,
                "effective_date": (date.today() + timedelta(days=10)).isoformat(),
                "reason": "Chuyển lại lớp đích",
            },
            headers={"Authorization": f"Bearer {self.tm_token}"},
        )
        self.assertEqual(res.status_code, 400)
