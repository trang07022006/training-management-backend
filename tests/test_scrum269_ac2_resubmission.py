"""
Targeted tests for SCRUM-269 - Acceptance Criteria 2 (AC2):
Học viên nộp lại được và có hạn nộp mới (resubmit assignment with new deadline).

Kiểm tra:
- Học viên nộp lại đúng hạn thành công (200, status = 'resubmitted', tạo version mới, giữ nguyên version cũ).
- Yêu cầu làm lại được cập nhật trạng thái 'fulfilled' và liên kết version mới.
- Quá hạn nộp lại bị từ chối (400 REWORK_SUBMISSION_OVERDUE).
- Học viên khác không được nộp thay (403 FORBIDDEN_STUDENT_OWNERSHIP).
- Nộp lại khi nội dung rỗng bị từ chối (400 EMPTY_SUBMISSION_CONTENT).
- Nộp lại khi bài không ở trạng thái needs_rework bị từ chối (400 INVALID_SUBMISSION_STATUS).
- Hạn nộp gốc của bài tập và của học viên khác không bị thay đổi.
- Nội dung, tệp và liên kết của lần nộp cũ được bảo toàn nguyên vẹn.
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
    SubmissionReworkRequest,
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


class Scrum269AC2ResubmissionTests(unittest.TestCase):
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
        self.trainer_id = str(uuid.uuid4())
        self.student_1_user_id = str(uuid.uuid4())
        self.student_2_user_id = str(uuid.uuid4())
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"

        self._insert_user(self.trainer_id, f"trainer_ac2_{suffix}@ictu.test", "trainer", "Giảng Viên Hướng Dẫn")
        self._insert_user(self.student_1_user_id, f"student1_ac2_{suffix}@ictu.test", "trainee", "Học Viên Một")
        self._insert_user(self.student_2_user_id, f"student2_ac2_{suffix}@ictu.test", "trainee", "Học Viên Hai")

        # Học viên 1
        self.student_1_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'Học Viên Một', '0912345678', %s, 'enrolled', %s, %s)
            """,
            (self.student_1_id, f"HV1_{suffix.upper()}", self.student_1_user_id, f"student1_ac2_{suffix}@ictu.test", self.now, self.now),
        )

        # Học viên 2
        self.student_2_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'Học Viên Hai', '0912345679', %s, 'enrolled', %s, %s)
            """,
            (self.student_2_id, f"HV2_{suffix.upper()}", self.student_2_user_id, f"student2_ac2_{suffix}@ictu.test", self.now, self.now),
        )

        # Program, Subject, Class
        self.program_id = str(uuid.uuid4())
        training_program_repository.insert_training_program(
            TrainingProgram(
                id=self.program_id,
                code=f"PRG2-{suffix}",
                name="Chương trình Test AC2",
                duration_semesters=4,
                status="active",
                standard_tuition_fee=12000000,
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.subject_id = str(uuid.uuid4())
        subject_repository.insert_subject(
            Subject(
                id=self.subject_id,
                code=f"SUB2-{suffix}",
                name="Môn Thiết kế CSDL",
                credits=3,
                total_sessions=45,
                status="active",
                created_at=self.now,
                updated_at=self.now,
            )
        )

        self.class_id = str(uuid.uuid4())
        self.class_code = f"CLS2-{suffix.upper()}"
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
            (str(uuid.uuid4()), self.class_subject_id, self.trainer_id, self.now, self.now),
        )

        # Ghi danh cả 2 học viên
        for sid in (self.student_1_id, self.student_2_id):
            self.cursor.execute(
                """
                INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
                VALUES (%s, %s, %s, 'enrolled', %s, %s, %s, %s)
                """,
                (str(uuid.uuid4()), self.class_id, sid, self.now, self.admin_user_id, self.now, self.now),
            )

        # Tạo bài tập với original due_date
        self.original_due_date = self.now + timedelta(days=5)
        self.assignment_id = str(uuid.uuid4())
        self.assignment = Assignment(
            id=self.assignment_id,
            class_id=self.class_id,
            title="Bài tập AC2: Chuẩn hóa CSDL",
            description="Nộp file diagram và SQL script",
            due_date=self.original_due_date,
            max_score=10.0,
            status="published",
            created_by=self.trainer_id,
            created_at=self.now,
            updated_at=self.now,
        )
        assignment_repository.create_assignment(self.assignment, self.conn)

        # Tạo bài nộp của học viên 1 với version 1
        self.submission_1_id = str(uuid.uuid4())
        self.submission_1 = AssignmentSubmission(
            id=self.submission_1_id,
            assignment_id=self.assignment_id,
            student_id=self.student_1_id,
            status=SUBMISSION_STATUS_NEEDS_REWORK,
            score=5.0,
            feedback="Điểm lần đầu: 5/10. Cần chuẩn hóa về 3NF.",
            graded_by=self.trainer_id,
            graded_at=self.now,
            rework_count=1,
            created_at=self.now,
            updated_at=self.now,
        )
        self.version_1_id = str(uuid.uuid4())
        self.version_1 = SubmissionVersion(
            id=self.version_1_id,
            submission_id=self.submission_1_id,
            version_number=1,
            submission_type="file",
            content="Bản nộp đầu tiên",
            file_url="/uploads/assignments/v1_database.sql",
            file_name="v1_database.sql",
            file_size=1024,
            repo_url=None,
            submitted_at=self.now - timedelta(days=1),
        )
        assignment_repository.create_submission(self.submission_1, self.version_1, self.conn)

        # Tạo yêu cầu làm lại đang mở với deadline tương lai 3 ngày
        self.rework_request_id = str(uuid.uuid4())
        self.future_deadline = self.now + timedelta(days=3)
        self.rework_req = SubmissionReworkRequest(
            id=self.rework_request_id,
            submission_id=self.submission_1_id,
            submission_version_id=self.version_1_id,
            request_number=1,
            comment="Bổ sung khóa ngoại và lược đồ quan hệ chuẩn 3NF.",
            new_deadline=self.future_deadline,
            requested_by=self.trainer_id,
            status=REWORK_STATUS_OPEN,
            created_at=self.now,
        )
        assignment_repository.insert_rework_request(self.rework_req, self.conn)
        self.conn.commit()

        # Tokens
        self.trainer_token = self._create_token(self.trainer_id, ["trainer"])
        self.student_1_token = self._create_token(self.student_1_user_id, ["trainee"])
        self.student_2_token = self._create_token(self.student_2_user_id, ["trainee"])

    def tearDown(self):
        try:
            self.cursor.execute("DELETE FROM submission_versions WHERE submission_id = %s", (self.submission_1_id,))
            self.cursor.execute("DELETE FROM submission_rework_requests WHERE submission_id = %s", (self.submission_1_id,))
            self.cursor.execute("DELETE FROM assignment_submissions WHERE id = %s", (self.submission_1_id,))
            self.cursor.execute("DELETE FROM assignments WHERE id = %s", (self.assignment_id,))
            self.cursor.execute("DELETE FROM class_enrollments WHERE class_id = %s", (self.class_id,))
            self.cursor.execute("DELETE FROM class_subject_instructors WHERE class_subject_id = %s", (self.class_subject_id,))
            self.cursor.execute("DELETE FROM class_subjects WHERE id = %s", (self.class_subject_id,))
            self.cursor.execute("DELETE FROM classes WHERE id = %s", (self.class_id,))
            self.cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            self.cursor.execute("DELETE FROM training_programs WHERE id = %s", (self.program_id,))
            self.cursor.execute("DELETE FROM students WHERE id IN (%s, %s)", (self.student_1_id, self.student_2_id))
            for uid in [self.trainer_id, self.student_1_user_id, self.student_2_user_id]:
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

    def test_tc269_20_resubmit_success_before_deadline(self):
        """Học viên nộp lại đúng hạn thành công, chuyển sang resubmitted và lưu version mới."""
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_1_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={
                "submission_type": "both",
                "content": "Em đã sửa lại các bảng theo chuẩn 3NF và bổ sung quan hệ 1-N.",
                "file_url": "/uploads/assignments/v2_database_3nf.sql",
                "file_name": "v2_database_3nf.sql",
                "file_size": 2048,
                "repo_url": "https://github.com/student/db-3nf",
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        data = body["data"]

        # Trạng thái chuyển sang resubmitted
        self.assertEqual(data["status"], SUBMISSION_STATUS_RESUBMITTED)
        # Rework count vẫn giữ nguyên là 1 (không tăng khi nộp lại)
        self.assertEqual(data["rework_count"], 1)

        # Kiểm tra danh sách versions: có 2 versions
        versions = data["versions"]
        self.assertEqual(len(versions), 2)
        # Version 1 cũ còn nguyên vẹn
        self.assertEqual(versions[0]["version_number"], 1)
        self.assertEqual(versions[0]["file_name"], "v1_database.sql")
        # Version 2 mới được tạo
        self.assertEqual(versions[1]["version_number"], 2)
        self.assertEqual(versions[1]["file_name"], "v2_database_3nf.sql")
        self.assertEqual(versions[1]["repo_url"], "https://github.com/student/db-3nf")
        self.assertEqual(versions[1]["rework_request_id"], self.rework_request_id)

        # Kiểm tra yêu cầu làm lại đã chuyển sang fulfilled
        req_db = assignment_repository.list_rework_requests(self.submission_1_id, self.conn)
        self.assertEqual(len(req_db), 1)
        self.assertEqual(req_db[0].status, REWORK_STATUS_FULFILLED)
        self.assertIsNotNone(req_db[0].fulfilled_at)
        self.assertEqual(req_db[0].fulfilled_version_id, versions[1]["id"])

        # Điểm và nhận xét cũ vẫn được lưu trong bài nộp để tra cứu
        self.assertEqual(data["score"], 5.0)
        self.assertIn("5/10", data["feedback"])

    def test_tc269_21_resubmit_after_deadline_rejected(self):
        """Học viên nộp lại sau hạn mới bị từ chối với lỗi 400 REWORK_SUBMISSION_OVERDUE."""
        # Cập nhật new_deadline về quá khứ (hết hạn)
        past_deadline = self.now - timedelta(hours=2)
        self.cursor.execute(
            "UPDATE submission_rework_requests SET new_deadline = %s WHERE id = %s",
            (past_deadline, self.rework_request_id),
        )
        self.conn.commit()

        res = self.client.post(
            f"/api/v1/submissions/{self.submission_1_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={
                "submission_type": "text",
                "content": "Nộp muộn sau hạn quy định",
            },
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertEqual(body["code"], "REWORK_SUBMISSION_OVERDUE")
        self.assertIn("quá hạn", body["message"])

        # Kiểm tra trạng thái bài nộp không bị đổi
        sub_db = assignment_repository.get_submission_by_id(self.submission_1_id)
        self.assertEqual(sub_db.status, SUBMISSION_STATUS_NEEDS_REWORK)
        # Không tạo thêm version mới
        self.assertEqual(len(sub_db.versions), 1)

    def test_tc269_22_other_student_cannot_resubmit(self):
        """Học viên khác không thể nộp bài cho học viên này (403 FORBIDDEN_STUDENT_OWNERSHIP)."""
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_1_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_2_token}"},
            json={
                "submission_type": "text",
                "content": "Học viên 2 cố nộp thay bài của học viên 1",
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_STUDENT_OWNERSHIP")

    def test_tc269_23_empty_content_rejected(self):
        """Nộp lại nhưng không có nội dung/tệp/link bị từ chối 400 EMPTY_SUBMISSION_CONTENT."""
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_1_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={
                "submission_type": "text",
                "content": "   ",
                "file_url": "",
                "repo_url": "",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "EMPTY_SUBMISSION_CONTENT")

    def test_tc269_24_cannot_resubmit_when_not_needs_rework(self):
        """Không thể nộp lại khi bài nộp đang ở trạng thái khác (submitted/resubmitted)."""
        # Đổi trạng thái bài sang submitted
        self.cursor.execute(
            "UPDATE assignment_submissions SET status = 'submitted' WHERE id = %s",
            (self.submission_1_id,),
        )
        self.conn.commit()

        res = self.client.post(
            f"/api/v1/submissions/{self.submission_1_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={"content": "Cố nộp lại khi trạng thái là submitted"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_SUBMISSION_STATUS")

    def test_tc269_25_original_assignment_deadline_remains_unchanged(self):
        """Hạn nộp mới của yêu cầu làm lại không làm thay đổi hạn nộp gốc của bài tập."""
        assign_before = assignment_repository.get_assignment_by_id(self.assignment_id)

        # Học viên nộp lại
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_1_id}/resubmit",
            headers={"Authorization": f"Bearer {self.student_1_token}"},
            json={"content": "Nộp bài theo hạn mới"},
        )
        self.assertEqual(res.status_code, 200)

        assign_after = assignment_repository.get_assignment_by_id(self.assignment_id)
        # Hạn nộp gốc vẫn được bảo toàn
        self.assertEqual(assign_before.due_date, assign_after.due_date)


if __name__ == "__main__":
    unittest.main()
