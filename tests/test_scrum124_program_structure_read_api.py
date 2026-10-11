"""
Bộ kiểm thử SCRUM-124 (Activity A2): API xem cấu trúc môn học của chương trình đào tạo.

Mục tiêu kiểm thử:
01. Không token -> 401 UNAUTHORIZED.
02. Token không hợp lệ -> 401 UNAUTHORIZED.
03. Không có quyền course.view -> 403 FORBIDDEN.
04. UUID sai định dạng -> 400 INVALID_PARAMS.
05. Chương trình đào tạo không tồn tại -> 404 PROGRAM_NOT_FOUND.
06. Cấu trúc rỗng -> 200 OK (total_subjects=0, total_credits=0, items=[]).
07. Cấu trúc nhiều học kỳ và học kỳ NULL -> 200 OK (đúng thứ tự semester, order_index).
08. Lọc theo semester -> 200 OK.
09. Lọc theo is_mandatory (true/false) -> 200 OK.
10. Tham số lọc sai định dạng -> 400 INVALID_PARAMS.
11. Đầy đủ thông tin môn học và danh sách prerequisites -> 200 OK.
12. Alias route (/api/training-programs/<id>/subjects) hoạt động giống /api/v1/...
13. Lỗi Database -> 500 DATABASE_ERROR không lộ stack trace.
14. MySQL Integration Live Test (prefix STR-A2-): Roundtrip API, sorting, totals, prerequisites, cleanup.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.program_subject import ProgramSubject
from app.models.program_subject_prerequisite import ProgramSubjectPrerequisite
from app.models.subject import SUBJECT_STATUS_ACTIVE, Subject
from app.models.training_program import PROGRAM_STATUS_ACTIVE, TrainingProgram
from app.repositories import (
    program_subject_repository,
    subject_repository,
    training_program_repository,
)
from app.routes.program_subject_routes import program_subject_bp


class Scrum124ProgramStructureReadApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API xem cấu trúc chương trình đào tạo."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a2-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.authorized_user_id = "user-auth-course-view"
        self.authorized_session = LoginSession(
            session_id="session-auth-course-view",
            user_id=self.authorized_user_id,
            refresh_jti="ref-auth-124",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.forbidden_user_id = "user-no-course-view"
        self.forbidden_session = LoginSession(
            session_id="session-forbidden-124",
            user_id=self.forbidden_user_id,
            refresh_jti="ref-forbid-124",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.authorized_token = create_access_token(
                identity=self.authorized_user_id,
                additional_claims={"sid": "session-auth-course-view"},
            )
            self.forbidden_token = create_access_token(
                identity=self.forbidden_user_id,
                additional_claims={"sid": "session-forbidden-124"},
            )

        self.auth_headers = {"Authorization": f"Bearer {self.authorized_token}"}
        self.forbidden_headers = {"Authorization": f"Bearer {self.forbidden_token}"}

    def test_01_unauthenticated_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/training-programs/{valid_uuid}/subjects")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    def test_02_invalid_token_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/training-programs/{valid_uuid}/subjects",
            headers={"Authorization": "Bearer malformed.token.value"},
        )
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_forbidden_without_course_view_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.forbidden_session
        mock_has_perm.return_value = False

        valid_uuid = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/training-programs/{valid_uuid}/subjects",
            headers=self.forbidden_headers,
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_invalid_program_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get(
            "/api/v1/training-programs/invalid-uuid-format/subjects",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("error", {}).get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    def test_05_program_not_found_returns_404(self, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_prog.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/training-programs/{valid_uuid}/subjects",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("error", {}).get("code"), "PROGRAM_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_structure")
    def test_06_empty_structure_returns_200(self, mock_get_struct, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=p_id, code="PROG-101", name="Kỹ thuật phần mềm", status="active", duration_semesters=8
        )
        mock_get_struct.return_value = []

        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["program"]["code"], "PROG-101")
        self.assertEqual(data["total_subjects"], 0)
        self.assertEqual(data["total_credits"], 0)
        self.assertEqual(data["items"], [])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_structure")
    def test_07_structure_with_items_and_totals(self, mock_get_struct, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=p_id, code="PROG-101", name="Kỹ thuật phần mềm", status="active", duration_semesters=8
        )
        mock_get_struct.return_value = [
            ProgramSubject(
                id="ps-1", program_id=p_id, subject_id="s-1", semester=1, is_mandatory=True, order_index=1,
                subject_code="CS101", subject_name="Cơ sở lập trình", subject_credits=3, subject_total_sessions=15, subject_status="active"
            ),
            ProgramSubject(
                id="ps-2", program_id=p_id, subject_id="s-2", semester=2, is_mandatory=False, order_index=1,
                subject_code="CS102", subject_name="Cấu trúc dữ liệu", subject_credits=4, subject_total_sessions=20, subject_status="active"
            ),
        ]

        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total_subjects"], 2)
        self.assertEqual(data["total_credits"], 7)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["subject_code"], "CS101")
        self.assertEqual(data["items"][0]["total_sessions"], 15)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_structure")
    def test_08_filter_by_semester(self, mock_get_struct, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=p_id, code="PROG-101", name="Kỹ thuật phần mềm", status="active", duration_semesters=8
        )
        mock_get_struct.return_value = [
            ProgramSubject(id="ps-1", program_id=p_id, subject_id="s-1", semester=1, order_index=1, subject_credits=3),
            ProgramSubject(id="ps-2", program_id=p_id, subject_id="s-2", semester=2, order_index=1, subject_credits=4),
        ]

        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects?semester=1",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total_subjects"], 1)
        self.assertEqual(data["total_credits"], 3)
        self.assertEqual(data["items"][0]["semester"], 1)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_structure")
    def test_09_filter_by_is_mandatory(self, mock_get_struct, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=p_id, code="PROG-101", name="Kỹ thuật phần mềm", status="active", duration_semesters=8
        )
        mock_get_struct.return_value = [
            ProgramSubject(id="ps-1", program_id=p_id, subject_id="s-1", is_mandatory=True, subject_credits=3),
            ProgramSubject(id="ps-2", program_id=p_id, subject_id="s-2", is_mandatory=False, subject_credits=4),
        ]

        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects?is_mandatory=false",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total_subjects"], 1)
        self.assertEqual(data["total_credits"], 4)
        self.assertFalse(data["items"][0]["is_mandatory"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    def test_10_invalid_filter_param_returns_400(self, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        p_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=p_id, code="PROG-101", name="Kỹ thuật phần mềm", status="active", duration_semesters=8
        )

        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects?semester=-1",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("error", {}).get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_structure")
    def test_11_route_alias_works_identically(self, mock_get_struct, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(
            id=p_id, code="PROG-101", name="Kỹ thuật phần mềm", status="active", duration_semesters=8
        )
        mock_get_struct.return_value = []

        res = self.client.get(
            f"/api/training-programs/{p_id}/subjects",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["program"]["code"], "PROG-101")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    def test_12_database_error_returns_500(self, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_prog.side_effect = MySQLError("Simulated MySQL DB connection failure")

        p_id = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data.get("error", {}).get("code"), "DATABASE_ERROR")


class Scrum124ProgramStructureReadApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp MySQL 8 thực tế cho API xem cấu trúc chương trình đào tạo."""

    PREFIX = "STR-A2-"

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a2-live-integration",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)
        self.client = self.app.test_client()

        with self.app.app_context():
            self.token = create_access_token(
                identity="live-test-user",
                additional_claims={"sid": "live-session-124-a2"},
            )
        self.headers = {"Authorization": f"Bearer {self.token}"}

        now = datetime.now(timezone.utc)
        self.mock_session = LoginSession(
            session_id="live-session-124-a2",
            user_id="live-test-user",
            refresh_jti="ref-live-124",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )

        # Tạo program live
        self.program = training_program_repository.insert_training_program(
            TrainingProgram(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}PROG-{uuid.uuid4().hex[:4].upper()}",
                name="Chương trình kiểm thử live cấu trúc",
                status=PROGRAM_STATUS_ACTIVE,
                duration_semesters=6,
            )
        )
        # Tạo 2 subjects live
        self.sub1 = subject_repository.insert_subject(
            Subject(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}SUB1-{uuid.uuid4().hex[:4].upper()}",
                name="Môn cơ sở live 1",
                credits=3,
                total_sessions=15,
                status=SUBJECT_STATUS_ACTIVE,
            )
        )
        self.sub2 = subject_repository.insert_subject(
            Subject(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}SUB2-{uuid.uuid4().hex[:4].upper()}",
                name="Môn nâng cao live 2",
                credits=4,
                total_sessions=20,
                status=SUBJECT_STATUS_ACTIVE,
            )
        )

        # Gắn vào program: sub1 ở kỳ 1, sub2 ở kỳ 2
        self.ps1 = program_subject_repository.insert_program_subject(
            ProgramSubject(
                id=str(uuid.uuid4()),
                program_id=self.program.id,
                subject_id=self.sub1.id,
                semester=1,
                order_index=1,
                is_mandatory=True,
            )
        )
        self.ps2 = program_subject_repository.insert_program_subject(
            ProgramSubject(
                id=str(uuid.uuid4()),
                program_id=self.program.id,
                subject_id=self.sub2.id,
                semester=2,
                order_index=1,
                is_mandatory=False,
            )
        )

        # Gán ps1 làm tiên quyết của ps2
        self.prereq = program_subject_repository.insert_prerequisite(
            ProgramSubjectPrerequisite(
                id=str(uuid.uuid4()),
                program_id=self.program.id,
                program_subject_id=self.ps2.id,
                prerequisite_program_subject_id=self.ps1.id,
            )
        )

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE psp FROM program_subject_prerequisites psp
                    JOIN training_programs tp ON psp.program_id = tp.id
                    WHERE tp.code LIKE %s
                    """,
                    (f"{self.PREFIX}%",),
                )
                cursor.execute(
                    """
                    DELETE ps FROM program_subjects ps
                    JOIN training_programs tp ON ps.program_id = tp.id
                    WHERE tp.code LIKE %s
                    """,
                    (f"{self.PREFIX}%",),
                )
                cursor.execute("DELETE FROM training_programs WHERE code LIKE %s", (f"{self.PREFIX}%",))
                cursor.execute("DELETE FROM subjects WHERE code LIKE %s", (f"{self.PREFIX}%",))
            conn.commit()
        finally:
            conn.close()

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_live_read_program_structure_roundtrip(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.mock_session
        mock_has_perm.return_value = True

        res = self.client.get(
            f"/api/v1/training-programs/{self.program.id}/subjects",
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertEqual(data["program"]["id"], self.program.id)
        self.assertEqual(data["total_subjects"], 2)
        self.assertEqual(data["total_credits"], 7)

        # Môn 1 ở kỳ 1
        item1 = next(it for it in data["items"] if it["subject_id"] == self.sub1.id)
        self.assertEqual(item1["semester"], 1)
        self.assertTrue(item1["is_mandatory"])
        self.assertEqual(item1["total_sessions"], 15)

        # Môn 2 ở kỳ 2 có prerequisite là ps1
        item2 = next(it for it in data["items"] if it["subject_id"] == self.sub2.id)
        self.assertEqual(item2["semester"], 2)
        self.assertFalse(item2["is_mandatory"])
        self.assertEqual(item2["total_sessions"], 20)
        self.assertEqual(len(item2["prerequisites"]), 1)
        self.assertEqual(item2["prerequisites"][0]["prerequisite_subject_code"], self.sub1.code)


if __name__ == "__main__":
    unittest.main()
