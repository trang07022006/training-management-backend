"""
Targeted tests for SCRUM-269 - Acceptance Criteria 3 (AC3):
Lưu và hiển thị số lần yêu cầu làm lại (rework counter & history audit).

Kiểm tra:
- Chuỗi vòng đời đầy đủ: 0 -> 1 -> nộp lại -> 1 -> yêu cầu tiếp -> 2 -> nộp lại -> 2.
- Retry / gửi lặp request không làm tăng sai counter (vẫn giữ nguyên).
- Đối chiếu số liệu: rework_count luôn khớp với số lượng bản ghi trong submission_rework_requests.
- Phân biệt rõ ràng giữa request_number ("Yêu cầu lần 2") và version_number ("Lần nộp thứ 3").
- Học viên sở hữu xem được lịch sử đầy đủ của mình.
- Học viên khác bị chặn xem lịch sử bài nộp của người khác (403 FORBIDDEN).
- Giảng viên ngoài lớp bị chặn xem (403 FORBIDDEN_CLASS).
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
    SUBMISSION_STATUS_NEEDS_REWORK,
    SUBMISSION_STATUS_RESUBMITTED,
    SUBMISSION_STATUS_SUBMITTED,
    REWORK_STATUS_OPEN,
    REWORK_STATUS_FULFILLED,
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


class Scrum269AC3ReworkCounterAndHistoryTests(unittest.TestCase):
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

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", side_effect=side_effect_get_session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        suffix = uuid.uuid4().hex[:6]
        self.assigned_trainer_id = str(uuid.uuid4())
        self.unassigned_trainer_id = str(uuid.uuid4())
        self.student_1_user_id = str(uuid.uuid4())
        self.student_2_user_id = str(uuid.uuid4())
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"

        self._insert_user(self.assigned_trainer_id, f"trainer3_{suffix}@ictu.test", "trainer", "Thầy C")
        self._insert_user(self.unassigned_trainer_id, f"trainer4_{suffix}@ictu.test", "trainer", "Thầy D")
        self._insert_user(self.student_1_user_id, f"student1_ac3_{suffix}@ictu.test", "trainee", "Học Viên AC3")
        self._insert_user(self.student_2_user_id, f"student2_ac3_{suffix}@ictu.test", "trainee", "Học Viên Khác")

        # Học viên 1
        self.student_1_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'Học Viên AC3', '0911223344', %s, 'enrolled', %s, %s)
            """,
            (self.student_1_id, f"HV3_{suffix.upper()}", self.student_1_user_id, f"student1_ac3_{suffix}@ictu.test", self.now, self.now),
        )

        # Học viên 2
        self.student_2_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'Học Viên Khác', '0911223355', %s, 'enrolled', %s, %s)
            """,
            (self.student_2_id, f"HV4_{suffix.upper()}", self.student_2_user_id, f"student2_ac3_{suffix}@ictu.test", self.now, self.now),
        )

        # Program, Subject, Class
        self.program_id = str(uuid.uuid4())
        training_program_repository.insert_training_program(
            TrainingProgram(
                id=self.program_id,
                code=f"PRG3-{suffix}",
                name="Chương trình Test AC3",
                duration_semesters=4,
                status="active",
                standard_tuition_fee=15000000,
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.subject_id = str(uuid.uuid4())
        subject_repository.insert_subject(
            Subject(
                id=self.subject_id,
                code=f"SUB3-{suffix}",
                name="Môn Kiểm thử phần mềm",
                credits=3,
                total_sessions=45,
                status="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.class_id = str(uuid.uuid4())
        self.class_code = f"CLS3-{suffix.upper()}"
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

        for sid in (self.student_1_id, self.student_2_id):
            self.cursor.execute(
                """
                INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
                VALUES (%s, %s, %s, 'enrolled', %s, %s, %s, %s)
                """,
                (str(uuid.uuid4()), self.class_id, sid, self.now, self.admin_user_id, self.now, self.now),
            )

        self.assignment_id = str(uuid.uuid4())
        self.assignment = Assignment(
            id=self.assignment_id,
            class_id=self.class_id,
            title="Bài tập AC3: Kiểm thử tự động",
            description="Nộp unit test và integration test",
            due_date=self.now + timedelta(days=10),
            max_score=10.0,
            status="published",
            created_by=self.assigned_trainer_id,
            created_at=self.now,
            updated_at=self.now,
        )
        assignment_repository.create_assignment(self.assignment, self.conn)

        # Tạo ban đầu submission của học viên 1 với version 1 (rework_count = 0)
        self.submission_id = str(uuid.uuid4())
        self.submission = AssignmentSubmission(
            id=self.submission_id,
            assignment_id=self.assignment_id,
            student_id=self.student_1_id,
            status=SUBMISSION_STATUS_SUBMITTED,
            score=None,
            feedback=None,
            graded_by=None,
            graded_at=None,
            rework_count=0,
            created_at=self.now,
            updated_at=self.now,
        )
        self.version_1 = SubmissionVersion(
            id=str(uuid.uuid4()),
            submission_id=self.submission_id,
            version_number=1,
            submission_type="repo_url",
            content="Lần nộp 1",
            repo_url="https://github.com/student/tests-v1",
            submitted_at=self.now,
        )
        assignment_repository.create_submission(self.submission, self.version_1, self.conn)
        self.conn.commit()

        # Tokens
        self.assigned_trainer_token = self._create_token(self.assigned_trainer_id, ["trainer"])
        self.unassigned_trainer_token = self._create_token(self.unassigned_trainer_id, ["trainer"])
        self.student_1_token = self._create_token(self.student_1_user_id, ["trainee"])
        self.student_2_token = self._create_token(self.student_2_user_id, ["trainee"])

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
            self.cursor.execute("DELETE FROM students WHERE id IN (%s, %s)", (self.student_1_id, self.student_2_id))
            for uid in [self.assigned_trainer_id, self.unassigned_trainer_id, self.student_1_user_id, self.student_2_user_id]:
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
        }
        self.cursor.execute(
            "INSERT IGNORE INTO user_roles (user_id, role_id, created_at) VALUES (%s, %s, NOW())",
            (user_id, role_id_map.get(role, "role-id-user")),
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

    def test_tc269_30_full_rework_counter_cycle(self):
        """
        Chuỗi kiểm thử vòng đời bộ đếm:
        0 -> Giảng viên yêu cầu lần 1 -> 1
          -> Học viên nộp lại -> 1
          -> Giảng viên yêu cầu lần 2 -> 2
          -> Retry gửi lặp yêu cầu 2 -> vẫn 2
          -> Học viên nộp lại lần 2 -> vẫn 2
        """
        # Bước 0: Ban đầu rework_count = 0
        res0 = self.client.get(
            f"/api/v1/submissions/{self.submission_id}",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
        )
        self.assertEqual(res0.status_code, 200)
        data0 = res0.get_json()["data"]
        self.assertEqual(data0["rework_count"], 0)
        self.assertEqual(len(data0["rework_history"]), 0)
        self.assertEqual(len(data0["versions"]), 1)

        # Bước 1: Giảng viên yêu cầu làm lại lần 1 -> rework_count = 1
        deadline_1 = (self.now + timedelta(days=2)).isoformat()
        res1 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Nhận xét lần 1: Thiếu assertions", "new_deadline": deadline_1},
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()["data"]
        self.assertEqual(data1["rework_count"], 1)
        self.assertEqual(len(data1["rework_history"]), 1)
        self.assertEqual(data1["rework_history"][0]["request_number"], 1)
        self.assertEqual(data1["rework_history"][0]["status"], "open")

        # Bước 2: Học viên nộp lại -> rework_count vẫn là 1 (không tăng khi nộp lại)
        res2 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={"content": "Đã bổ sung assertions theo yêu cầu", "submission_type": "text"},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()["data"]
        self.assertEqual(data2["rework_count"], 1)
        self.assertEqual(len(data2["versions"]), 2)
        # Yêu cầu lần 1 đã chuyển thành fulfilled
        self.assertEqual(data2["rework_history"][0]["status"], "fulfilled")
        self.assertEqual(data2["rework_history"][0]["fulfilled_version_number"], 2)

        # Bước 3: Giảng viên xem xét lần nộp 2 và yêu cầu làm lại lần 2 -> rework_count = 2
        deadline_2 = (self.now + timedelta(days=4)).isoformat()
        res3 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Nhận xét lần 2: Cần thêm coverage report", "new_deadline": deadline_2},
        )
        self.assertEqual(res3.status_code, 200)
        data3 = res3.get_json()["data"]
        self.assertEqual(data3["rework_count"], 2)
        self.assertEqual(len(data3["rework_history"]), 2)
        self.assertEqual(data3["rework_history"][1]["request_number"], 2)
        self.assertEqual(data3["rework_history"][1]["status"], "open")

        # Bước 4: Retry gửi lại cùng yêu cầu lần 2 khi chưa nộp lại -> Bị chặn 409, counter không tăng
        res_retry = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Thử gửi lại lần 2", "new_deadline": deadline_2},
        )
        self.assertEqual(res_retry.status_code, 409)

        # Kiểm tra counter vẫn là 2
        res_check = self.client.get(
            f"/api/v1/submissions/{self.submission_id}",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
        )
        self.assertEqual(res_check.get_json()["data"]["rework_count"], 2)

        # Bước 5: Học viên nộp lại lần 2 -> rework_count vẫn là 2
        res4 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={"content": "Đã thêm coverage report 95%", "submission_type": "text"},
        )
        self.assertEqual(res4.status_code, 200)
        data4 = res4.get_json()["data"]
        self.assertEqual(data4["rework_count"], 2)
        self.assertEqual(len(data4["versions"]), 3)
        self.assertEqual(data4["rework_history"][1]["status"], "fulfilled")
        self.assertEqual(data4["rework_history"][1]["fulfilled_version_number"], 3)

    def test_tc269_31_other_student_cannot_view_history(self):
        """Học viên khác không được xem lịch sử bài nộp của học viên này (403 FORBIDDEN)."""
        res = self.client.get(
            f"/api/v1/submissions/{self.submission_id}",
            headers={"Authorization": f"Bearer {self.student_2_token}"},
        )
        self.assertEqual(res.status_code, 403)

    def test_tc269_32_unassigned_trainer_cannot_view_history(self):
        """Giảng viên không phụ trách lớp không được xem chi tiết bài nộp (403 FORBIDDEN_CLASS)."""
        res = self.client.get(
            f"/api/v1/submissions/{self.submission_id}",
            headers={"Authorization": f"Bearer {self.unassigned_trainer_token}"},
        )
        self.assertEqual(res.status_code, 403)

    def test_tc269_33_my_submission_endpoint(self):
        """Học viên xem bài nộp của chính mình qua GET /assignments/<id>/my-submission."""
        res = self.client.get(
            f"/api/v1/assignments/{self.assignment_id}/my-submission",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["id"], self.submission_id)
        self.assertEqual(data["rework_count"], 0)
        self.assertIn("versions", data)
        self.assertIn("rework_history", data)

    def test_tc269_34_list_assignment_submissions_endpoint(self):
        """Giảng viên xem danh sách bài nộp của bài tập qua GET /assignments/<id>/submissions."""
        res = self.client.get(
            f"/api/v1/assignments/{self.assignment_id}/submissions",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        items = data["submissions"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], self.submission_id)
        self.assertEqual(items[0]["student_id"], self.student_1_id)
        self.assertEqual(items[0]["rework_count"], 0)


if __name__ == "__main__":
    unittest.main()
