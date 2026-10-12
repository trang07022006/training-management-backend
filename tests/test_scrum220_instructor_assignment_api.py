"""
Test suite cho SCRUM-220: Phân công giảng viên và trợ giảng (TC220-01 -> TC220-10).
- Sub-task 220-01: Phân công theo từng môn (1 giảng viên chính, nhiều trợ giảng).
- Sub-task 220-02: Lọc tài khoản theo vai trò & backend validation.
- Sub-task 220-03: Giảng viên thấy lớp của mình & tích hợp bộ lọc SCRUM-219.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.models.subject import Subject
from app.repositories import (
    class_repository,
    program_subject_repository,
    subject_repository,
    training_program_repository,
)


class Scrum220InstructorAssignmentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"
        self.now = datetime.now(timezone.utc)

        # Mock session cho Admin / Training Manager và Trainers
        self.session_id = f"test-session-{uuid.uuid4()}"
        self.sessions = {self.session_id: self.admin_user_id}

        def side_effect_get_session(sid):
            uid = self.sessions.get(sid, self.admin_user_id)
            return LoginSession(
                session_id=sid,
                user_id=uid,
                refresh_jti=f"ref-{sid}",
                created_at=self.now,
                last_activity_at=self.now,
                idle_expires_at=self.now + timedelta(hours=8),
                absolute_expires_at=self.now + timedelta(hours=8),
            )

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", side_effect=side_effect_get_session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={
                    "roles": ["admin", "training_manager"],
                    "sid": self.session_id,
                },
            )

        # Tạo trainer accounts và non-trainer account cho test
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor(dictionary=True)

        self.trainer_a_id = str(uuid.uuid4())
        self.trainer_b_id = str(uuid.uuid4())
        self.assistant_1_id = str(uuid.uuid4())
        self.assistant_2_id = str(uuid.uuid4())
        self.trainee_user_id = str(uuid.uuid4())

        suffix = uuid.uuid4().hex[:6]
        self._insert_user(self.trainer_a_id, f"trainer_a_220_{suffix}@test.edu.vn", "trainer", "Thầy A")
        self._insert_user(self.trainer_b_id, f"trainer_b_220_{suffix}@test.edu.vn", "trainer", "Thầy B")
        self._insert_user(self.assistant_1_id, f"assistant_1_220_{suffix}@test.edu.vn", "trainer", "Trợ giảng 1")
        self._insert_user(self.assistant_2_id, f"assistant_2_220_{suffix}@test.edu.vn", "trainer", "Trợ giảng 2")
        self._insert_user(self.trainee_user_id, f"trainee_220_{suffix}@test.edu.vn", "trainee", "Học viên C")

        # Tạo program, subject, class và class_subject
        self.program_id = str(uuid.uuid4())
        training_program_repository.insert_training_program(
            TrainingProgram(
                id=self.program_id,
                code=f"PRG-{uuid.uuid4().hex[:6]}",
                name="Chương trình Test 220",
                duration_semesters=4,
                status="active",
                standard_tuition_fee=10000000,
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.subject_id = str(uuid.uuid4())
        subject_repository.insert_subject(
            Subject(
                id=self.subject_id,
                code=f"SUB-{uuid.uuid4().hex[:6]}",
                name="Môn học Test 220",
                credits=3,
                total_sessions=45,
                status="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.cursor.execute(
            """
            INSERT INTO program_subjects (id, program_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
            VALUES (%s, %s, %s, 1, 1, 1, %s, %s)
            """,
            (str(uuid.uuid4()), self.program_id, self.subject_id, self.now, self.now),
        )
        self.conn.commit()

        # Mở lớp
        self.class_code = f"CLS-220-{uuid.uuid4().hex[:6].upper()}"
        res = self.client.post(
            "/api/v1/classes",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "class_code": self.class_code,
                "program_id": self.program_id,
                "max_capacity": 30,
                "learning_mode": "offline",
            },
        )
        self.assertEqual(res.status_code, 201)
        self.class_id = res.get_json()["data"]["id"]

        # Lấy class_subject_id
        subjects_res = self.client.get(
            f"/api/v1/classes/{self.class_id}/subjects",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(subjects_res.status_code, 200)
        self.class_subjects = subjects_res.get_json()["data"]
        self.assertTrue(len(self.class_subjects) > 0)
        self.class_subject_id = self.class_subjects[0]["id"]

    def tearDown(self):
        try:
            self.cursor.execute("DELETE FROM class_subject_instructors WHERE class_subject_id = %s", (self.class_subject_id,))
            self.cursor.execute("DELETE FROM class_subjects WHERE class_id = %s", (self.class_id,))
            self.cursor.execute("DELETE FROM classes WHERE id = %s", (self.class_id,))
            self.cursor.execute("DELETE FROM program_subjects WHERE program_id = %s", (self.program_id,))
            self.cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            self.cursor.execute("DELETE FROM training_programs WHERE id = %s", (self.program_id,))

            for uid in [
                self.trainer_a_id,
                self.trainer_b_id,
                self.assistant_1_id,
                self.assistant_2_id,
                self.trainee_user_id,
            ]:
                self.cursor.execute("DELETE FROM users WHERE id = %s", (uid,))
            self.conn.commit()
        except Exception:
            pass
        finally:
            self.cursor.close()
            self.conn.close()

    def _insert_user(self, user_id: str, email: str, role: str, name: str):
        self.cursor.execute(
            """
            INSERT INTO users (id, email, password_hash, role, status, name, failed_login_attempts, created_at, updated_at)
            VALUES (%s, %s, 'hash', %s, 'active', %s, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE role = VALUES(role), name = VALUES(name)
            """,
            (user_id, email, role, name),
        )
        self.conn.commit()

    def _get_trainer_token(self, trainer_id: str):
        trainer_sid = f"trainer-session-{uuid.uuid4()}"
        self.sessions[trainer_sid] = trainer_id
        with self.app.app_context():
            return create_access_token(
                identity=trainer_id,
                additional_claims={
                    "roles": ["trainer"],
                    "sid": trainer_sid,
                },
            )

    # =========================================================================
    # 220-01: PHÂN CÔNG THEO TỪNG MÔN (TC220-01 -> TC220-04)
    # =========================================================================
    def test_tc220_01_assign_single_main_instructor(self):
        """TC220-01: Chọn một môn -> gán được 1 giảng viên chính."""
        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsNotNone(data["main_instructor"])
        self.assertEqual(data["main_instructor"]["id"], self.trainer_a_id)
        self.assertEqual(data["assistants"], [])

    def test_tc220_02_assign_multiple_teaching_assistants(self):
        """TC220-02: Gán nhiều trợ giảng cho 1 môn -> lưu được nhiều người."""
        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [self.assistant_1_id, self.assistant_2_id],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["main_instructor"]["id"], self.trainer_a_id)
        self.assertEqual(len(data["assistants"]), 2)
        asst_ids = [a["id"] for a in data["assistants"]]
        self.assertIn(self.assistant_1_id, asst_ids)
        self.assertIn(self.assistant_2_id, asst_ids)

    def test_tc220_03_assignment_persists_on_get(self):
        """TC220-03: Reload/GET lại -> thông tin phân công persist đúng."""
        self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [self.assistant_1_id],
            },
        )

        res = self.client.get(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["main_instructor"]["id"], self.trainer_a_id)
        self.assertEqual(len(data["assistants"]), 1)
        self.assertEqual(data["assistants"][0]["id"], self.assistant_1_id)

    def test_tc220_04_change_main_instructor_retains_single_main(self):
        """TC220-04: Đổi giảng viên chính -> môn chỉ còn đúng 1 main instructor mới."""
        # Gán lần 1: Trainer A
        self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [self.assistant_1_id],
            },
        )

        # Đổi sang Trainer B
        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_b_id,
                "assistant_ids": [self.assistant_1_id],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["main_instructor"]["id"], self.trainer_b_id)
        self.assertNotEqual(data["main_instructor"]["id"], self.trainer_a_id)

    # 220-02 & 220-03 tests will be activated in respective sub-tasks
    pass


if __name__ == "__main__":
    unittest.main()
