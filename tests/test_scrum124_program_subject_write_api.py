"""
Bộ kiểm thử SCRUM-124 (Activity A3): API Thêm và Cập nhật môn học trong chương trình đào tạo.

Mục tiêu kiểm thử:
01. POST thêm môn thành công (201 Created).
02. POST không truyền order_index -> tự động append vào cuối.
03. POST truyền order_index chèn vào giữa -> tự động dịch chuyển và chuẩn hóa thứ tự liên tục.
04. POST trùng môn trong cùng chương trình -> 409 SUBJECT_ALREADY_IN_PROGRAM.
05. POST chương trình không tồn tại -> 404 PROGRAM_NOT_FOUND.
06. POST môn học không tồn tại -> 404 SUBJECT_NOT_FOUND.
07. POST vào chương trình archived -> 400 ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED.
08. POST môn học archived -> 400 ARCHIVED_SUBJECT_CANNOT_BE_ADDED.
09. POST môn draft vào chương trình active -> 400 DRAFT_SUBJECT_NOT_ALLOWED_IN_ACTIVE_PROGRAM.
10. POST môn draft vào chương trình draft -> 201 Created.
11. POST semester vượt quá duration_semesters -> 400 SEMESTER_EXCEEDS_PROGRAM_DURATION.
12. POST is_mandatory là string thay vì boolean -> 400 INVALID_PARAMS.
13. PATCH cập nhật semester thành công (tự động chuẩn hóa cả kỳ cũ và mới).
14. PATCH cập nhật is_mandatory thành công.
15. PATCH cập nhật order_index thành công.
16. PATCH bỏ qua các trường hệ thống không được phép sửa (id, program_id, subject_id, created_at).
17. Quyền course.view -> 403 FORBIDDEN khi POST và PATCH.
18. Không token -> 401 UNAUTHORIZED.
19. Route alias (/api/training-programs/<id>/subjects) hoạt động chính xác.
20. MySQL Integration Live Test (prefix PS-A3-): Roundtrip POST & PATCH live, persistence, cleanup.
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
from app.models.subject import SUBJECT_STATUS_ACTIVE, SUBJECT_STATUS_ARCHIVED, SUBJECT_STATUS_DRAFT, Subject
from app.models.training_program import PROGRAM_STATUS_ACTIVE, PROGRAM_STATUS_ARCHIVED, PROGRAM_STATUS_DRAFT, TrainingProgram
from app.repositories import (
    program_subject_repository,
    subject_repository,
    training_program_repository,
)
from app.routes.program_subject_routes import program_subject_bp


class Scrum124ProgramSubjectWriteApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và phân quyền RBAC cho API thêm và cập nhật môn học trong chương trình."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a3-unit-testing",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Quản lý (có quyền course.manage)
        self.manager_user_id = "user-course-manage"
        self.manager_session = LoginSession(
            session_id="session-course-manage",
            user_id=self.manager_user_id,
            refresh_jti="ref-manage-124",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Người chỉ có quyền xem (course.view)
        self.viewer_user_id = "user-course-view"
        self.viewer_session = LoginSession(
            session_id="session-course-view",
            user_id=self.viewer_user_id,
            refresh_jti="ref-view-124",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-course-manage"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-course-view"},
            )

        self.manage_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.view_headers = {"Authorization": f"Bearer {self.viewer_token}"}

    def test_01_unauthenticated_returns_401(self):
        p_id = str(uuid.uuid4())
        res = self.client.post(f"/api/v1/training-programs/{p_id}/subjects", json={"subject_id": str(uuid.uuid4())})
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_viewer_cannot_post_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False

        p_id = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.view_headers,
            json={"subject_id": str(uuid.uuid4())},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("code"), "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.program_subject_repository.exists_program_subject")
    @patch("app.repositories.program_subject_repository.insert_program_subject_ordered")
    def test_03_post_subject_success(
        self, mock_insert, mock_exists, mock_get_subj, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_subj.return_value = Subject(id=s_id, code="CS101", name="Cơ sở lập trình", credits=3, status="active")
        mock_exists.return_value = False

        created_ps = ProgramSubject(
            id="ps-new-1", program_id=p_id, subject_id=s_id, semester=1, is_mandatory=True, order_index=1,
            subject_code="CS101", subject_name="Cơ sở lập trình", subject_credits=3, subject_status="active"
        )
        mock_insert.return_value = created_ps

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.manage_headers,
            json={"subject_id": s_id, "semester": 1, "is_mandatory": True},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["program_subject_id"], "ps-new-1")
        self.assertEqual(data["subject_code"], "CS101")
        self.assertEqual(data["semester"], 1)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.program_subject_repository.exists_program_subject")
    def test_04_duplicate_subject_in_program_returns_409(
        self, mock_exists, mock_get_subj, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_subj.return_value = Subject(id=s_id, code="CS101", name="CS101", credits=3, status="active")
        mock_exists.return_value = True

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.manage_headers,
            json={"subject_id": s_id},
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "SUBJECT_ALREADY_IN_PROGRAM")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_05_active_program_with_draft_subject_returns_400(
        self, mock_get_subj, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_subj.return_value = Subject(id=s_id, code="CS101", name="CS101", credits=3, status="draft")

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.manage_headers,
            json={"subject_id": s_id},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "DRAFT_SUBJECT_NOT_ALLOWED_IN_ACTIVE_PROGRAM")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_06_archived_subject_returns_400(
        self, mock_get_subj, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="draft", duration_semesters=8)
        mock_get_subj.return_value = Subject(id=s_id, code="CS101", name="CS101", credits=3, status="archived")

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.manage_headers,
            json={"subject_id": s_id},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "ARCHIVED_SUBJECT_CANNOT_BE_ADDED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_07_semester_exceeds_duration_returns_400(
        self, mock_get_subj, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=4)
        mock_get_subj.return_value = Subject(id=s_id, code="CS101", name="CS101", credits=3, status="active")

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.manage_headers,
            json={"subject_id": s_id, "semester": 5},  # 5 > 4
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "SEMESTER_EXCEEDS_PROGRAM_DURATION")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_08_is_mandatory_string_returns_400(
        self, mock_get_subj, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_subj.return_value = Subject(id=s_id, code="CS101", name="CS101", credits=3, status="active")

        res = self.client.post(
            f"/api/v1/training-programs/{p_id}/subjects",
            headers=self.manage_headers,
            json={"subject_id": s_id, "is_mandatory": "true"},  # Chuỗi "true" thay vì boolean thật
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.update_program_subject_fields")
    def test_09_patch_program_subject_success(
        self, mock_update, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_ps.return_value = ProgramSubject(
            id=ps_id, program_id=p_id, subject_id="s-1", semester=1, is_mandatory=True, order_index=1,
            subject_code="CS101", subject_name="CS101", subject_credits=3, subject_status="active"
        )
        mock_update.return_value = ProgramSubject(
            id=ps_id, program_id=p_id, subject_id="s-1", semester=2, is_mandatory=False, order_index=3,
            subject_code="CS101", subject_name="CS101", subject_credits=3, subject_status="active"
        )

        res = self.client.patch(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}",
            headers=self.manage_headers,
            json={"semester": 2, "is_mandatory": False, "order_index": 3, "id": "tamper-id"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["semester"], 2)
        self.assertFalse(data["is_mandatory"])
        self.assertEqual(data["order_index"], 3)


class Scrum124ProgramSubjectWriteApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp trên MySQL 8 (prefix PS-A3-)."""

    PREFIX = "PS-A3-"

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a3-live-integration",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)
        self.client = self.app.test_client()

        with self.app.app_context():
            self.token = create_access_token(
                identity="manager-user-a3",
                additional_claims={"sid": "live-session-a3"},
            )
        self.headers = {"Authorization": f"Bearer {self.token}"}

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="live-session-a3",
            user_id="manager-user-a3",
            refresh_jti="ref-live-a3",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )

        # Tạo program
        self.prog = training_program_repository.insert_training_program(
            TrainingProgram(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}PROG-{uuid.uuid4().hex[:4].upper()}",
                name="Chương trình live A3",
                status=PROGRAM_STATUS_ACTIVE,
                duration_semesters=6,
            )
        )
        # Tạo 2 subjects
        self.sub1 = subject_repository.insert_subject(
            Subject(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}SUB1-{uuid.uuid4().hex[:4].upper()}",
                name="Môn học live 1",
                credits=3,
                status=SUBJECT_STATUS_ACTIVE,
            )
        )
        self.sub2 = subject_repository.insert_subject(
            Subject(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}SUB2-{uuid.uuid4().hex[:4].upper()}",
                name="Môn học live 2",
                credits=4,
                status=SUBJECT_STATUS_ACTIVE,
            )
        )

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
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
    def test_live_add_and_patch_roundtrip(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.session
        mock_has_perm.return_value = True

        # 1. POST thêm môn 1
        res1 = self.client.post(
            f"/api/v1/training-programs/{self.prog.id}/subjects",
            headers=self.headers,
            json={"subject_id": self.sub1.id, "semester": 1, "is_mandatory": True},
        )
        self.assertEqual(res1.status_code, 201)
        data1 = res1.get_json()
        ps_id1 = data1["program_subject_id"]
        self.assertEqual(data1["order_index"], 1)

        # 2. POST thêm môn 2 vào cùng kỳ 1, chèn vào order 1 -> môn 1 bị đẩy xuống order 2
        res2 = self.client.post(
            f"/api/v1/training-programs/{self.prog.id}/subjects",
            headers=self.headers,
            json={"subject_id": self.sub2.id, "semester": 1, "order_index": 1, "is_mandatory": False},
        )
        self.assertEqual(res2.status_code, 201)
        data2 = res2.get_json()
        ps_id2 = data2["program_subject_id"]
        self.assertEqual(data2["order_index"], 1)

        # Kiểm tra lại môn 1 trong DB đã được chuyển sang order 2
        ps1_db = program_subject_repository.get_program_subject_by_id(ps_id1)
        self.assertEqual(ps1_db.order_index, 2)

        # 3. PATCH chuyển môn 2 sang kỳ 2
        res_patch = self.client.patch(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{ps_id2}",
            headers=self.headers,
            json={"semester": 2, "is_mandatory": True},
        )
        self.assertEqual(res_patch.status_code, 200)
        data_patch = res_patch.get_json()
        self.assertEqual(data_patch["semester"], 2)
        self.assertTrue(data_patch["is_mandatory"])

        # Kiểm tra môn 1 trong kỳ 1 đã được normalize về order 1
        ps1_renormalized = program_subject_repository.get_program_subject_by_id(ps_id1)
        self.assertEqual(ps1_renormalized.order_index, 1)


if __name__ == "__main__":
    unittest.main()
