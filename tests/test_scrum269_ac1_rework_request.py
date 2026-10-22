"""
Targeted tests for SCRUM-269 - Acceptance Criteria 1 (AC1):
Yêu cầu học viên làm lại bài tập kèm nhận xét bắt buộc, chuyển trạng thái Cần làm lại (needs_rework).

Kiểm tra:
- Giảng viên đúng lớp yêu cầu làm lại thành công (200, status = 'needs_rework', rework_count = 1, bản ghi request được tạo).
- Nhận xét rỗng, None, chỉ khoảng trắng hoặc dài quá 2000 ký tự bị chặn (400).
- Deadline thiếu, sai định dạng hoặc ở quá khứ bị chặn (400).
- Giảng viên ngoài lớp bị từ chối (403 FORBIDDEN_CLASS).
- Học viên giả mạo quyền giảng viên bị từ chối (403 FORBIDDEN).
- Yêu cầu không có token bị từ chối (401 UNAUTHORIZED).
- Bài chưa có lần nộp nào (empty) bị từ chối (400).
- Bài nộp không tồn tại bị trả về 404 (SUBMISSION_NOT_FOUND).
- Bài nộp đang có yêu cầu làm lại mở không được tạo thêm yêu cầu trùng (409 REWORK_ALREADY_OPEN).
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
    SUBMISSION_STATUS_SUBMITTED,
    REWORK_STATUS_OPEN,
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


class Scrum269AC1ReworkRequestTests(unittest.TestCase):
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
        # Tạo users
        self.assigned_trainer_id = str(uuid.uuid4())
        self.unassigned_trainer_id = str(uuid.uuid4())
        self.student_user_id = str(uuid.uuid4())
        self.admin_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"

        self._insert_user(self.assigned_trainer_id, f"trainer1_{suffix}@ictu.test", "trainer", "Thầy Phụ Trách")
        self._insert_user(self.unassigned_trainer_id, f"trainer2_{suffix}@ictu.test", "trainer", "Thầy Ngoài Lớp")
        self._insert_user(self.student_user_id, f"student_{suffix}@ictu.test", "trainee", "Học Viên A")

        # Tạo student record
        self.student_id = str(uuid.uuid4())
        self.student_code = f"HV{suffix.upper()}"
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, '0987654321', %s, 'enrolled', %s, %s)
            """,
            (self.student_id, self.student_code, self.student_user_id, "Học Viên A", f"student_{suffix}@ictu.test", self.now, self.now),
        )

        # Tạo training program & subject & class
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

        # Class subject
        self.class_subject_id = str(uuid.uuid4())
        self.cursor.execute(
            """
            INSERT INTO class_subjects (id, class_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at)
            VALUES (%s, %s, %s, 1, 1, 1, %s, %s)
            """,
            (self.class_subject_id, self.class_id, self.subject_id, self.now, self.now),
        )

        # Phân công assigned_trainer vào lớp
        self.cursor.execute(
            """
            INSERT INTO class_subject_instructors (id, class_subject_id, instructor_id, role_type, created_at, updated_at)
            VALUES (%s, %s, %s, 'main', %s, %s)
            """,
            (str(uuid.uuid4()), self.class_subject_id, self.assigned_trainer_id, self.now, self.now),
        )

        # Ghi danh học viên vào lớp
        self.cursor.execute(
            """
            INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
            VALUES (%s, %s, %s, 'enrolled', %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), self.class_id, self.student_id, self.now, self.admin_user_id, self.now, self.now),
        )

        # Tạo bài tập
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

        # Tạo bài nộp có 1 version
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

        # Tokens
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
        # Gán role id tương ứng trong user_roles
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

    def test_tc269_01_assigned_instructor_request_rework_success(self):
        """Giảng viên đúng lớp yêu cầu làm lại thành công kèm nhận xét và hạn mới."""
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={
                "comment": "Code chưa xử lý exception khi kết nối database, yêu cầu bổ sung try-catch và unit test.",
                "new_deadline": future_deadline,
            },
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        data = body["data"]
        self.assertEqual(data["id"], self.submission_id)
        self.assertEqual(data["status"], SUBMISSION_STATUS_NEEDS_REWORK)
        self.assertEqual(data["rework_count"], 1)

        # Kiểm tra bản ghi yêu cầu làm lại
        current_req = data["current_rework_request"]
        self.assertIsNotNone(current_req)
        self.assertEqual(current_req["request_number"], 1)
        self.assertEqual(current_req["status"], REWORK_STATUS_OPEN)
        self.assertIn("try-catch", current_req["comment"])
        self.assertEqual(current_req["requested_by"], self.assigned_trainer_id)

        # Kiểm tra database trực tiếp
        sub_db = assignment_repository.get_submission_by_id(self.submission_id)
        self.assertIsNotNone(sub_db)
        self.assertEqual(sub_db.status, SUBMISSION_STATUS_NEEDS_REWORK)
        self.assertEqual(sub_db.rework_count, 1)

    def test_tc269_02_empty_or_whitespace_comment_rejected(self):
        """Nhận xét rỗng hoặc chỉ khoảng trắng bị từ chối với lỗi 400 COMMENT_REQUIRED."""
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

        # Comment rỗng
        res1 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "", "new_deadline": future_deadline},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "COMMENT_REQUIRED")

        # Comment chỉ khoảng trắng
        res2 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "   \n\t  ", "new_deadline": future_deadline},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "COMMENT_REQUIRED")

        # Comment None
        res3 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": None, "new_deadline": future_deadline},
        )
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "COMMENT_REQUIRED")

    def test_tc269_03_comment_too_long_rejected(self):
        """Nhận xét vượt quá 2000 ký tự bị từ chối với lỗi 400 COMMENT_TOO_LONG."""
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        long_comment = "A" * 2001
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": long_comment, "new_deadline": future_deadline},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "COMMENT_TOO_LONG")

    def test_tc269_04_invalid_deadline_rejected(self):
        """Hạn nộp thiếu, sai định dạng hoặc ở quá khứ bị từ chối với mã lỗi rõ ràng."""
        # Thiếu deadline
        res1 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Cần sửa bài"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "DEADLINE_REQUIRED")

        # Định dạng sai
        res2 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Cần sửa bài", "new_deadline": "ngay-mai-2026"},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "INVALID_DEADLINE_FORMAT")

        # Hạn ở quá khứ
        past_deadline = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        res3 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Cần sửa bài", "new_deadline": past_deadline},
        )
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "DEADLINE_MUST_BE_FUTURE")

    def test_tc269_05_unassigned_instructor_rejected(self):
        """Giảng viên không phụ trách lớp bị chặn với lỗi 403 FORBIDDEN_CLASS."""
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.unassigned_trainer_token}"},
            json={"comment": "Giảng viên ngoài lớp cố ý yêu cầu làm lại", "new_deadline": future_deadline},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_CLASS")

    def test_tc269_06_student_cannot_request_rework(self):
        """Học viên không có quyền yêu cầu làm lại bài tập (403 FORBIDDEN)."""
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.student_token}"},
            json={"comment": "Học viên tự yêu cầu làm lại", "new_deadline": future_deadline},
        )
        self.assertEqual(res.status_code, 403)

    def test_tc269_07_unauthenticated_request_rejected(self):
        """Request không có JWT token bị từ chối 401 UNAUTHORIZED."""
        res = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            json={"comment": "Không có token", "new_deadline": "2026-10-30T10:00:00Z"},
        )
        self.assertEqual(res.status_code, 401)

    def test_tc269_08_duplicate_open_request_blocked(self):
        """Không cho phép tạo thêm yêu cầu khi đang có một yêu cầu làm lại mở (409 REWORK_ALREADY_OPEN)."""
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()

        # Yêu cầu lần 1: thành công
        res1 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Lần yêu cầu đầu tiên", "new_deadline": future_deadline},
        )
        self.assertEqual(res1.status_code, 200)

        # Yêu cầu lần 2 khi chưa nộp lại: bị từ chối 409
        res2 = self.client.post(
            f"/api/v1/submissions/{self.submission_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Lần yêu cầu thứ hai trùng lặp", "new_deadline": future_deadline},
        )
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.get_json()["code"], "REWORK_ALREADY_OPEN")

        # Kiểm tra rework_count không bị tăng khống
        sub_db = assignment_repository.get_submission_by_id(self.submission_id)
        self.assertEqual(sub_db.rework_count, 1)

    def test_tc269_09_submission_not_found(self):
        """Gửi yêu cầu tới bài nộp không tồn tại trả về 404 SUBMISSION_NOT_FOUND."""
        non_existent_id = str(uuid.uuid4())
        future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        res = self.client.post(
            f"/api/v1/submissions/{non_existent_id}/request-rework",
            headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
            json={"comment": "Bài không tồn tại", "new_deadline": future_deadline},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "SUBMISSION_NOT_FOUND")

    def test_tc269_10_empty_submission_cannot_be_reworked(self):
        """Bài nộp trống (chưa có lần nộp nào) không thể yêu cầu làm lại."""
        other_student_id = str(uuid.uuid4())
        other_user_id = str(uuid.uuid4())
        suffix = uuid.uuid4().hex[:6]
        self._insert_user(other_user_id, f"student2_{suffix}@ictu.test", "trainee", "Học Viên B")
        self.cursor.execute(
            """
            INSERT INTO students (id, student_code, user_id, full_name, phone, email, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'Học Viên B', '0987654322', %s, 'enrolled', %s, %s)
            """,
            (other_student_id, f"HV2{suffix.upper()}", other_user_id, f"student2_{suffix}@ictu.test", self.now, self.now),
        )
        self.cursor.execute(
            """
            INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at)
            VALUES (%s, %s, %s, 'enrolled', %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), self.class_id, other_student_id, self.now, self.admin_user_id, self.now, self.now),
        )

        empty_sub_id = str(uuid.uuid4())
        # Chỉ tạo submission row, không tạo version nào
        self.cursor.execute(
            """
            INSERT INTO assignment_submissions (id, assignment_id, student_id, status, rework_count, created_at, updated_at)
            VALUES (%s, %s, %s, 'submitted', 0, %s, %s)
            """,
            (empty_sub_id, self.assignment_id, other_student_id, self.now, self.now),
        )
        self.conn.commit()

        try:
            future_deadline = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
            res = self.client.post(
                f"/api/v1/submissions/{empty_sub_id}/request-rework",
                headers={"Authorization": f"Bearer {self.assigned_trainer_token}"},
                json={"comment": "Yêu cầu bài chưa nộp", "new_deadline": future_deadline},
            )
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "CANNOT_REWORK_EMPTY_SUBMISSION")
        finally:
            self.cursor.execute("DELETE FROM assignment_submissions WHERE id = %s", (empty_sub_id,))
            self.cursor.execute("DELETE FROM class_enrollments WHERE student_id = %s", (other_student_id,))
            self.cursor.execute("DELETE FROM students WHERE id = %s", (other_student_id,))
            self.cursor.execute("DELETE FROM users WHERE id = %s", (other_user_id,))
            self.conn.commit()


if __name__ == "__main__":
    unittest.main()
