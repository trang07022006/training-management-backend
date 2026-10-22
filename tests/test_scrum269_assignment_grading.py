"""
Kiểm thử chức năng Giảng viên Giao bài tập, Xem bài tập và Đánh giá / Xác nhận bài nộp (SCRUM-269).
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.assignment import (
    Assignment,
    AssignmentSubmission,
    SubmissionVersion,
    SUBMISSION_STATUS_SUBMITTED,
)
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.models.subject import Subject
from app.models.class_entity import ClassEntity
from app.repositories import (
    assignment_repository,
    class_repository,
    subject_repository,
    training_program_repository,
)


class Scrum269AssignmentGradingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor(dictionary=True)

        self.sessions = {}

        def side_effect_get_session(sid):
            uid = self.sessions.get(sid)
            if not uid:
                return None
            return LoginSession(
                session_id=sid,
                user_id=uid,
                refresh_jti=f"ref-{sid}",
                created_at=self.now,
                last_activity_at=self.now,
                idle_expires_at=self.now + timedelta(hours=8),
                absolute_expires_at=self.now + timedelta(hours=8),
            )

        self.session_patcher = patch(
            "app.utils.rbac_auth.get_session_by_id",
            side_effect=side_effect_get_session,
        )
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        suffix = uuid.uuid4().hex[:6]
        self.assigned_trainer_id = str(uuid.uuid4())
        self.unassigned_trainer_id = str(uuid.uuid4())
        self.student_user_id = str(uuid.uuid4())
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"

        self._insert_user(self.assigned_trainer_id, f"trainer1_{suffix}@ictu.test", "trainer", "Thầy Phụ Trách")
        self._insert_user(self.unassigned_trainer_id, f"trainer2_{suffix}@ictu.test", "trainer", "Thầy Ngoài Lớp")
        self._insert_user(self.student_user_id, f"student_{suffix}@ictu.test", "trainee", "Học Viên A")

        self.student_id = str(uuid.uuid4())
        self.student_code = f"HV{suffix.upper()}"
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, '0987654321', %s, 'enrolled', %s, %s)
            """,
            (self.student_id, self.student_code, self.student_user_id, "Học Viên A", f"student_{suffix}@ictu.test", self.now, self.now),
        )

        self.program_id = str(uuid.uuid4())
        training_program_repository.insert_training_program(
            TrainingProgram(
                id=self.program_id,
                code=f"PRG-{suffix}",
                name="Chương trình Test SCRUM-269",
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
                code=f"SUB-{suffix}",
                name="Môn học Lập trình Web",
                credits=3,
                total_sessions=45,
                status="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.class_id = str(uuid.uuid4())
        self.class_code = f"CLS-{suffix.upper()}"
        class_repository.create_class(
            ClassEntity(
                id=self.class_id,
                class_code=self.class_code,
                program_id=self.program_id,
                expected_start_date=self.now.date(),
                max_capacity=30,
                learning_mode="offline",
                status="in_progress",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.class_subject_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
            VALUES (%s, %s, %s, 1, 1, 1, %s, %s)
            """,
            (self.class_subject_id, self.class_id, self.subject_id, self.now, self.now),
        )

        self.cursor.execute(
            """
            INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
            VALUES (%s, %s, %s, 'main', %s, %s)
            """,
            (str(uuid.uuid4()), self.class_subject_id, self.assigned_trainer_id, self.now, self.now),
        )

        self.cursor.execute(
            """
            INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
            VALUES (%s, %s, %s, 'enrolled', %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), self.class_id, self.student_id, self.now, self.admin_user_id, self.now, self.now),
        )

        self.assignment_id = str(uuid.uuid4())
        self.assignment = Assignment(
            id=self.assignment_id,
            class_id=self.class_id,
            title="Bài tập 1: Xây dựng REST API",
            description="Nộp mã nguồn hoặc liên kết GitHub",
            due_date=self.now + timedelta(days=7),
            max_score=10.0,
            status="published",
            created_by=self.assigned_trainer_id,
            created_at=self.now,
            updated_at=self.now,
        )
        assignment_repository.create_assignment(self.assignment, self.conn)

        self.submission_id = str(uuid.uuid4())
        self.submission = AssignmentSubmission(
            id=self.submission_id,
            assignment_id=self.assignment_id,
            student_id=self.student_id,
            status=SUBMISSION_STATUS_SUBMITTED,
            score=None,
            feedback=None,
            graded_by=None,
            graded_at=None,
            rework_count=0,
            created_at=self.now,
            updated_at=self.now,
        )
        self.version_id = str(uuid.uuid4())
        self.version_1 = SubmissionVersion(
            id=self.version_id,
            submission_id=self.submission_id,
            version_number=1,
            submission_type="repo_url",
            content="Bài nộp lần đầu",
            file_url=None,
            file_name=None,
            file_size=None,
            repo_url="https://github.com/student/assignment1",
            submitted_at=self.now,
        )
        assignment_repository.create_submission(self.submission, self.version_1, self.conn)
        self.conn.commit()

        self.assigned_trainer_token = self._create_token(self.assigned_trainer_id, ["trainer"])
        self.unassigned_trainer_token = self._create_token(self.unassigned_trainer_id, ["trainer"])
        self.student_token = self._create_token(self.student_user_id, ["trainee"])
        self.admin_token = self._create_token(self.admin_user_id, ["admin", "training_manager"])

    def tearDown(self):
        try:
            self.cursor.execute("DELETE FROM submission_versions WHERE submission_id = %s", (self.submission_id,))
            self.cursor.execute("DELETE FROM submission_rework_requests WHERE submission_id = %s", (self.submission_id,))
            self.cursor.execute("DELETE FROM assignment_submissions WHERE id = %s", (self.submission_id,))
            self.cursor.execute("DELETE FROM assignments WHERE id = %s", (self.assignment_id,))
            self.cursor.execute("DELETE FROM class_enrollments WHERE class_id = %s", (self.class_id,))
            self.cursor.execute("DELETE FROM class_subject_instructors WHERE class_subject_id = %s", (self.class_subject_id,))
            self.cursor.execute("DELETE FROM class_subjects WHERE id = %s", (self.class_subject_id,))
            self.cursor.execute("DELETE FROM classes WHERE id = %s", (self.class_id,))
            self.cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            self.cursor.execute("DELETE FROM training_programs WHERE id = %s", (self.program_id,))
            self.cursor.execute("DELETE FROM students WHERE id = %s", (self.student_id,))
            for uid in [self.assigned_trainer_id, self.unassigned_trainer_id, self.student_user_id]:
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
        role_id_map = {
            "trainer": "role-id-trainer",
            "trainee": "role-id-trainee",
            "admin": "role-id-admin",
            "training_manager": "role-id-training-manager",
        }
        role_id = role_id_map.get(role, "role-id-user")
        self.cursor.execute(
            "INSERT IGNORE INTO user_roles (user_id, role_id, created_at) VALUES (%s, %s, NOW())",
            (user_id, role_id),
        )
        self.conn.commit()

    def _create_token(self, user_id: str, roles: list[str]) -> str:
        sid = f"sid-{uuid.uuid4()}"
        self.sessions[sid] = user_id
        with self.app.app_context():
            return create_access_token(
                identity=user_id,
                additional_claims={"roles": roles, "sid": sid},
            )

    def test_tc269_40_create_assignment_success(self):
        """Giảng viên phụ trách lớp giao bài tập mới thành công."""
        payload = {
            "title": "Bài tập lớn môn Web",
            "description": "Xây dựng backend RESTful API chuẩn",
            "due_date": (self.now + timedelta(days=14)).isoformat(),
            "max_score": 10.0,
        }
        resp = self.client.post(
            f"/api/v1/classes/{self.class_id}/assignments",
            json=payload,
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["data"]
        self.assertEqual(data["title"], "Bài tập lớn môn Web")
        self.assertEqual(data["class_id"], self.class_id)
        self.assertEqual(data["max_score"], 10.0)

    def test_tc269_41_create_assignment_missing_title_rejected(self):
        """Giao bài tập thiếu tiêu đề bị từ chối 400."""
        payload = {
            "title": "",
            "max_score": 10.0,
        }
        resp = self.client.post(
            f"/api/v1/classes/{self.class_id}/assignments",
            json=payload,
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "TITLE_REQUIRED")

    def test_tc269_42_create_assignment_unassigned_instructor_rejected(self):
        """Giảng viên không phụ trách lớp không được phép giao bài tập (403)."""
        payload = {
            "title": "Bài tập của giảng viên ngoài",
            "max_score": 10.0,
        }
        resp = self.client.post(
            f"/api/v1/classes/{self.class_id}/assignments",
            json=payload,
            headers={"Authorization": f"Bearer {self.unassigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN_CLASS")

    def test_tc269_43_list_class_assignments(self):
        """Lấy danh sách các bài tập của một lớp học."""
        resp = self.client.get(
            f"/api/v1/classes/{self.class_id}/assignments",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()["data"]
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0]["id"], self.assignment_id)

    def test_tc269_44_grade_submission_success(self):
        """Giảng viên phụ trách chấm điểm và đánh giá bài nộp thành công."""
        payload = {
            "score": 8.5,
            "feedback": "Code sạch sẽ, đầy đủ unit test.",
        }
        resp = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/grade",
            json=payload,
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["status"], "graded")
        self.assertEqual(data["score"], 8.5)
        self.assertEqual(data["feedback"], "Code sạch sẽ, đầy đủ unit test.")

    def test_tc269_45_grade_submission_invalid_score_rejected(self):
        """Chấm điểm vượt quá max_score bị từ chối 400."""
        payload = {
            "score": 15.0,  # Max score is 10.0
            "feedback": "Điểm vượt ngưỡng",
        }
        resp = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/grade",
            json=payload,
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_SCORE")

    def test_tc269_46_grade_submission_unassigned_instructor_rejected(self):
        """Giảng viên không phụ trách lớp không được chấm điểm (403)."""
        payload = {
            "score": 9.0,
        }
        resp = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/grade",
            json=payload,
            headers={"Authorization": f"Bearer {self.unassigned_trainer_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN_CLASS")


if __name__ == "__main__":
    unittest.main()
