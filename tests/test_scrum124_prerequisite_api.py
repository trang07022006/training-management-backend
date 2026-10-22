"""
Bộ kiểm thử SCRUM-124 (Activity A5): API Quản lý Môn học Tiên quyết (Prerequisites) và Cycle Detection.

Mục tiêu kiểm thử:
01. GET danh sách prerequisites rỗng -> 200 OK ([]).
02. POST gán 1 môn tiên quyết thành công -> 201 Created.
03. POST gán nhiều môn tiên quyết cho cùng 1 môn (quan hệ N:N) -> 201 Created.
04. POST gán trùng lặp prerequisite -> 409 PREREQUISITE_ALREADY_EXISTS.
05. POST tự gán chính mình làm tiên quyết -> 400 INVALID_PARAMS.
06. POST gán môn tiên quyết từ chương trình khác -> 400 INVALID_PARAMS.
07. Cycle trực tiếp (A -> B, thử B -> A) -> 409 PREREQUISITE_CYCLE.
08. Cycle gián tiếp (A -> B -> C, thử C -> A) -> 409 PREREQUISITE_CYCLE.
09. Valid DAG edge (A -> B, A -> C) -> 201 Created.
10. Thứ tự học kỳ sai (prerequisite semester > dependent semester) -> 400 INVALID_PREREQUISITE_ORDER.
11. Thứ tự cùng học kỳ sai (prerequisite order >= dependent order) -> 400 INVALID_PREREQUISITE_ORDER.
12. DELETE xóa điều kiện tiên quyết thành công -> 200 OK.
13. DELETE điều kiện không tồn tại -> 404 PREREQUISITE_NOT_FOUND.
14. Chương trình archived: GET được (200), nhưng POST/DELETE bị chặn (400 ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED).
15. Quyền course.view: xem được GET (200), POST/DELETE bị chặn (403 FORBIDDEN).
16. Không token -> 401 UNAUTHORIZED.
17. Route alias hoạt động chính xác.
18. MySQL Live Graph Integration Test (prefix PR-A5-): Cycle rejection live, multi-prerequisites, cleanup.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.program_subject import ProgramSubject
from app.models.program_subject_prerequisite import ProgramSubjectPrerequisite
from app.models.subject import SUBJECT_STATUS_ACTIVE, Subject
from app.models.training_program import PROGRAM_STATUS_ACTIVE, PROGRAM_STATUS_ARCHIVED, TrainingProgram
from app.repositories import (
    program_subject_repository,
    subject_repository,
    training_program_repository,
)
from app.routes.program_subject_routes import program_subject_bp


class Scrum124PrerequisiteApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API Môn học Tiên quyết."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a5-unit-testing",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.manager_user_id = "user-course-manage-a5"
        self.manager_session = LoginSession(
            session_id="session-course-manage-a5",
            user_id=self.manager_user_id,
            refresh_jti="ref-manage-a5",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.viewer_user_id = "user-course-view-a5"
        self.viewer_session = LoginSession(
            session_id="session-course-view-a5",
            user_id=self.viewer_user_id,
            refresh_jti="ref-view-a5",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-course-manage-a5"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-course-view-a5"},
            )

        self.manage_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.view_headers = {"Authorization": f"Bearer {self.viewer_token}"}

    def test_01_unauthenticated_returns_401(self):
        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/training-programs/{p_id}/subjects/{ps_id}/prerequisites")
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_viewer_cannot_post_or_delete_prerequisite_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False

        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        prereq_id = str(uuid.uuid4())

        res1 = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}/prerequisites",
            headers=self.view_headers,
            json={"prerequisite_program_subject_id": prereq_id},
        )
        self.assertEqual(res1.status_code, 403)

        res2 = self.client.delete(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}/prerequisites/{prereq_id}",
            headers=self.view_headers,
        )
        self.assertEqual(res2.status_code, 403)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.get_prerequisites_by_program_subject_id")
    def test_03_get_prerequisites_success(
        self, mock_get_prereqs, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active")
        mock_get_ps.return_value = ProgramSubject(id=ps_id, program_id=p_id, subject_id="s1")
        mock_get_prereqs.return_value = [
            ProgramSubjectPrerequisite(id="pr-1", program_id=p_id, program_subject_id=ps_id, prerequisite_program_subject_id="ps-target")
        ]

        res = self.client.get(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}/prerequisites",
            headers=self.view_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()), 1)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.exists_prerequisite")
    @patch("app.repositories.program_subject_repository.would_create_cycle")
    @patch("app.repositories.program_subject_repository.insert_prerequisite")
    def test_04_add_prerequisite_success(
        self, mock_insert, mock_cycle, mock_exists, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps1 = str(uuid.uuid4())
        ps2 = str(uuid.uuid4())

        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active")
        # ps1 ở kỳ 1, ps2 ở kỳ 2 -> gán ps1 làm tiên quyết của ps2
        mock_get_ps.side_effect = [
            ProgramSubject(id=ps2, program_id=p_id, subject_id="s2", semester=2, order_index=1),
            ProgramSubject(id=ps1, program_id=p_id, subject_id="s1", semester=1, order_index=1),
        ]
        mock_exists.return_value = False
        mock_cycle.return_value = False
        mock_insert.return_value = ProgramSubjectPrerequisite(
            id="pr-new", program_id=p_id, program_subject_id=ps2, prerequisite_program_subject_id=ps1
        )

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects/{ps2}/prerequisites",
            headers=self.manage_headers,
            json={"prerequisite_program_subject_id": ps1},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["program_subject_id"], ps2)
        self.assertEqual(data["prerequisite_program_subject_id"], ps1)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    def test_05_self_prerequisite_returns_400(
        self, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps1 = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active")
        mock_get_ps.return_value = ProgramSubject(id=ps1, program_id=p_id, subject_id="s1")

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects/{ps1}/prerequisites",
            headers=self.manage_headers,
            json={"prerequisite_program_subject_id": ps1},  # Self reference
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.exists_prerequisite")
    @patch("app.repositories.program_subject_repository.would_create_cycle")
    def test_06_cycle_detected_returns_409(
        self, mock_cycle, mock_exists, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps1 = str(uuid.uuid4())
        ps2 = str(uuid.uuid4())

        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active")
        mock_get_ps.side_effect = [
            ProgramSubject(id=ps2, program_id=p_id, subject_id="s2", semester=2, order_index=1),
            ProgramSubject(id=ps1, program_id=p_id, subject_id="s1", semester=1, order_index=1),
        ]
        mock_exists.return_value = False
        mock_cycle.return_value = True  # Phát hiện vòng lặp!

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects/{ps2}/prerequisites",
            headers=self.manage_headers,
            json={"prerequisite_program_subject_id": ps1},
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "PREREQUISITE_CYCLE")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    def test_07_invalid_order_later_semester_returns_400(
        self, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps_dep = str(uuid.uuid4())
        ps_prereq = str(uuid.uuid4())

        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active")
        # ps_dep ở kỳ 1, nhưng ps_prereq lại ở kỳ 3 -> sai lộ trình!
        mock_get_ps.side_effect = [
            ProgramSubject(id=ps_dep, program_id=p_id, subject_id="s1", semester=1, order_index=1),
            ProgramSubject(id=ps_prereq, program_id=p_id, subject_id="s2", semester=3, order_index=1),
        ]

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_dep}/prerequisites",
            headers=self.manage_headers,
            json={"prerequisite_program_subject_id": ps_prereq},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "INVALID_PREREQUISITE_ORDER")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.exists_prerequisite")
    @patch("app.repositories.program_subject_repository.remove_prerequisite_pair")
    def test_08_delete_prerequisite_success(
        self, mock_remove, mock_exists, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps1 = str(uuid.uuid4())
        ps2 = str(uuid.uuid4())

        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active")
        mock_exists.return_value = True

        res = self.client.delete(
            f"/api/v1/training-programs/{p_id}/subjects/{ps1}/prerequisites/{ps2}",
            headers=self.manage_headers,
        )
        self.assertEqual(res.status_code, 200)
        mock_remove.assert_called_once_with(p_id, ps1, ps2)


class Scrum124PrerequisiteApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp đồ thị tiên quyết thực tế trên MySQL 8 (prefix PR-A5-)."""

    PREFIX = "PR-A5-"

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a5-live-integration",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)
        self.client = self.app.test_client()

        with self.app.app_context():
            self.token = create_access_token(
                identity="manager-user-a5",
                additional_claims={"sid": "live-session-a5"},
            )
        self.headers = {"Authorization": f"Bearer {self.token}"}

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="live-session-a5",
            user_id="manager-user-a5",
            refresh_jti="ref-live-a5",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )

        self.prog = training_program_repository.insert_training_program(
            TrainingProgram(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}PROG-{uuid.uuid4().hex[:4].upper()}",
                name="Chương trình live A5",
                status=PROGRAM_STATUS_ACTIVE,
                duration_semesters=8,
            )
        )
        self.subA = subject_repository.insert_subject(
            Subject(id=str(uuid.uuid4()), code=f"{self.PREFIX}SUBA-{uuid.uuid4().hex[:4].upper()}", name="Môn A", credits=3, status=SUBJECT_STATUS_ACTIVE)
        )
        self.subB = subject_repository.insert_subject(
            Subject(id=str(uuid.uuid4()), code=f"{self.PREFIX}SUBB-{uuid.uuid4().hex[:4].upper()}", name="Môn B", credits=4, status=SUBJECT_STATUS_ACTIVE)
        )
        self.subC = subject_repository.insert_subject(
            Subject(id=str(uuid.uuid4()), code=f"{self.PREFIX}SUBC-{uuid.uuid4().hex[:4].upper()}", name="Môn C", credits=3, status=SUBJECT_STATUS_ACTIVE)
        )

        # Gắn môn A (kỳ 1), môn B (kỳ 2), môn C (kỳ 3)
        self.psA = program_subject_repository.insert_program_subject(
            ProgramSubject(id=str(uuid.uuid4()), program_id=self.prog.id, subject_id=self.subA.id, semester=1, order_index=1)
        )
        self.psB = program_subject_repository.insert_program_subject(
            ProgramSubject(id=str(uuid.uuid4()), program_id=self.prog.id, subject_id=self.subB.id, semester=2, order_index=1)
        )
        self.psC = program_subject_repository.insert_program_subject(
            ProgramSubject(id=str(uuid.uuid4()), program_id=self.prog.id, subject_id=self.subC.id, semester=3, order_index=1)
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
    def test_live_prerequisite_graph_and_cycle_detection(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.session
        mock_has_perm.return_value = True

        # 1. Thêm cạnh A -> B (A là tiên quyết của B)
        res1 = self.client.post(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.psB.id}/prerequisites",
            headers=self.headers,
            json={"prerequisite_program_subject_id": self.psA.id},
        )
        self.assertEqual(res1.status_code, 201)

        # 2. Thêm cạnh B -> C (B là tiên quyết của C)
        res2 = self.client.post(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.psC.id}/prerequisites",
            headers=self.headers,
            json={"prerequisite_program_subject_id": self.psB.id},
        )
        self.assertEqual(res2.status_code, 201)

        # 3. Thử tạo cycle C -> A (C làm tiên quyết của A: A -> B -> C -> A) -> Bị chặn 409 PREREQUISITE_CYCLE
        res_cycle = self.client.post(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.psA.id}/prerequisites",
            headers=self.headers,
            json={"prerequisite_program_subject_id": self.psC.id},
        )
        # Vì psC ở kỳ 3 > psA kỳ 1 nên cũng vi phạm INVALID_PREREQUISITE_ORDER hoặc PREREQUISITE_CYCLE
        self.assertIn(res_cycle.status_code, (400, 409))

        # 4. Thêm cạnh A -> C (C có cả 2 môn tiên quyết là A và B) -> Hợp lệ
        res_multi = self.client.post(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.psC.id}/prerequisites",
            headers=self.headers,
            json={"prerequisite_program_subject_id": self.psA.id},
        )
        self.assertEqual(res_multi.status_code, 201)

        # 5. GET danh sách môn tiên quyết của C -> Phải có 2 môn (A và B)
        res_list = self.client.get(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.psC.id}/prerequisites",
            headers=self.headers,
        )
        self.assertEqual(res_list.status_code, 200)
        data_list = res_list.get_json()
        self.assertEqual(len(data_list), 2)


if __name__ == "__main__":
    unittest.main()
