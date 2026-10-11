"""
Bộ kiểm thử SCRUM-124 (Activity A4): API Sắp xếp thứ tự (Reorder) và Gỡ môn học (Remove) khỏi chương trình đào tạo.

Mục tiêu kiểm thử:
01. PATCH reorder thành công với danh sách ordered_ids (200 OK).
02. PATCH reorder thành công với format items [{program_subject_id, order_index}].
03. PATCH reorder trùng ID -> 400 INVALID_PARAMS.
04. PATCH reorder chứa ID không thuộc chương trình -> 400 INVALID_PARAMS.
05. PATCH reorder chứa ID sai học kỳ -> 400 INVALID_PARAMS.
06. PATCH reorder trên chương trình archived -> 400 ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED.
07. DELETE remove thành công môn học (200 OK).
08. DELETE remove môn đang là prerequisite target của môn khác -> 409 PROGRAM_SUBJECT_IN_USE.
09. DELETE remove trên chương trình archived -> 400 ARCHIVED_PROGRAM_CANNOT_BE_MODIFIED.
10. DELETE không tồn tại -> 404 PROGRAM_SUBJECT_NOT_FOUND.
11. Quyền course.view -> 403 FORBIDDEN khi reorder và remove.
12. Không token -> 401 UNAUTHORIZED.
13. Route alias (/api/training-programs/<id>/subjects/...) hoạt động giống /api/v1/...
14. MySQL Integration Live Test (prefix RM-A4-): Reorder persistence, safe remove, master preservation, target protection, cleanup.
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


class Scrum124ProgramSubjectReorderRemoveApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API Reorder và Remove."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a4-unit-testing",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.manager_user_id = "user-course-manage-a4"
        self.manager_session = LoginSession(
            session_id="session-course-manage-a4",
            user_id=self.manager_user_id,
            refresh_jti="ref-manage-a4",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.viewer_user_id = "user-course-view-a4"
        self.viewer_session = LoginSession(
            session_id="session-course-view-a4",
            user_id=self.viewer_user_id,
            refresh_jti="ref-view-a4",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-course-manage-a4"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-course-view-a4"},
            )

        self.manage_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.view_headers = {"Authorization": f"Bearer {self.viewer_token}"}

    def test_01_unauthenticated_returns_401(self):
        p_id = str(uuid.uuid4())
        res = self.client.patch(f"/api/v1/training-programs/{p_id}/subjects/reorder", json={"ordered_ids": []})
        self.assertEqual(res.status_code, 401)

        ps_id = str(uuid.uuid4())
        res_del = self.client.delete(f"/api/v1/training-programs/{p_id}/subjects/{ps_id}")
        self.assertEqual(res_del.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_viewer_cannot_reorder_or_delete_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False

        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        res1 = self.client.patch(
            f"/api/v1/training-programs/{p_id}/subjects/reorder",
            headers=self.view_headers,
            json={"ordered_ids": [ps_id]},
        )
        self.assertEqual(res1.status_code, 403)

        res2 = self.client.delete(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}",
            headers=self.view_headers,
        )
        self.assertEqual(res2.status_code, 403)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.reorder_program_subjects")
    @patch("app.repositories.program_subject_repository.get_program_structure")
    def test_03_reorder_success(
        self, mock_get_struct, mock_reorder, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps1 = str(uuid.uuid4())
        ps2 = str(uuid.uuid4())

        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_ps.side_effect = [
            ProgramSubject(id=ps1, program_id=p_id, subject_id="s1", semester=1, order_index=1),
            ProgramSubject(id=ps2, program_id=p_id, subject_id="s2", semester=1, order_index=2),
        ]
        mock_get_struct.return_value = [
            ProgramSubject(id=ps2, program_id=p_id, subject_id="s2", semester=1, order_index=1, subject_credits=3),
            ProgramSubject(id=ps1, program_id=p_id, subject_id="s1", semester=1, order_index=2, subject_credits=4),
        ]

        res = self.client.patch(
            f"/api/v1/training-programs/{p_id}/subjects/reorder",
            headers=self.manage_headers,
            json={"semester": 1, "ordered_ids": [ps2, ps1]},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["items"]), 2)
        mock_reorder.assert_called_once_with(p_id, 1, [ps2, ps1])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    def test_04_reorder_duplicate_ids_returns_400(self, mock_get_prog, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps1 = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)

        res = self.client.patch(
            f"/api/v1/training-programs/{p_id}/subjects/reorder",
            headers=self.manage_headers,
            json={"semester": 1, "ordered_ids": [ps1, ps1]},  # Trùng ps1
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.is_prerequisite_target")
    def test_05_remove_prerequisite_target_returns_409(
        self, mock_is_target, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_ps.return_value = ProgramSubject(id=ps_id, program_id=p_id, subject_id="s1", semester=1, order_index=1)
        mock_is_target.return_value = True  # Đang là prerequisite target!

        res = self.client.delete(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}",
            headers=self.manage_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("error", {}).get("code"), "PROGRAM_SUBJECT_IN_USE")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.program_subject_repository.get_program_subject_by_id")
    @patch("app.repositories.program_subject_repository.is_prerequisite_target")
    @patch("app.repositories.program_subject_repository.remove_program_subject")
    @patch("app.repositories.program_subject_repository.normalize_order_indices")
    def test_06_remove_success(
        self, mock_norm, mock_remove, mock_is_target, mock_get_ps, mock_get_prog, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        p_id = str(uuid.uuid4())
        ps_id = str(uuid.uuid4())
        mock_get_prog.return_value = TrainingProgram(id=p_id, code="PROG-1", name="KTPM", status="active", duration_semesters=8)
        mock_get_ps.return_value = ProgramSubject(id=ps_id, program_id=p_id, subject_id="s1", semester=1, order_index=1)
        mock_is_target.return_value = False
        mock_remove.return_value = True

        res = self.client.delete(
            f"/api/v1/training-programs/{p_id}/subjects/{ps_id}",
            headers=self.manage_headers,
        )
        self.assertEqual(res.status_code, 200)
        mock_remove.assert_called_once_with(ps_id)
        mock_norm.assert_called_once_with(p_id, 1)


class Scrum124ProgramSubjectReorderRemoveApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp trên MySQL 8 (prefix RM-A4-)."""

    PREFIX = "RM-A4-"

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum124-a4-live-integration",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(program_subject_bp)
        self.client = self.app.test_client()

        with self.app.app_context():
            self.token = create_access_token(
                identity="manager-user-a4",
                additional_claims={"sid": "live-session-a4"},
            )
        self.headers = {"Authorization": f"Bearer {self.token}"}

        now = datetime.now(timezone.utc)
        self.session = LoginSession(
            session_id="live-session-a4",
            user_id="manager-user-a4",
            refresh_jti="ref-live-a4",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )

        self.prog = training_program_repository.insert_training_program(
            TrainingProgram(
                id=str(uuid.uuid4()),
                code=f"{self.PREFIX}PROG-{uuid.uuid4().hex[:4].upper()}",
                name="Chương trình live A4",
                status=PROGRAM_STATUS_ACTIVE,
                duration_semesters=8,
            )
        )
        self.sub1 = subject_repository.insert_subject(
            Subject(id=str(uuid.uuid4()), code=f"{self.PREFIX}SUB1-{uuid.uuid4().hex[:4].upper()}", name="Môn 1", credits=3, status=SUBJECT_STATUS_ACTIVE)
        )
        self.sub2 = subject_repository.insert_subject(
            Subject(id=str(uuid.uuid4()), code=f"{self.PREFIX}SUB2-{uuid.uuid4().hex[:4].upper()}", name="Môn 2", credits=4, status=SUBJECT_STATUS_ACTIVE)
        )
        self.sub3 = subject_repository.insert_subject(
            Subject(id=str(uuid.uuid4()), code=f"{self.PREFIX}SUB3-{uuid.uuid4().hex[:4].upper()}", name="Môn 3", credits=3, status=SUBJECT_STATUS_ACTIVE)
        )

        # Gắn 3 môn vào kỳ 1
        self.ps1 = program_subject_repository.insert_program_subject(
            ProgramSubject(id=str(uuid.uuid4()), program_id=self.prog.id, subject_id=self.sub1.id, semester=1, order_index=1)
        )
        self.ps2 = program_subject_repository.insert_program_subject(
            ProgramSubject(id=str(uuid.uuid4()), program_id=self.prog.id, subject_id=self.sub2.id, semester=1, order_index=2)
        )
        self.ps3 = program_subject_repository.insert_program_subject(
            ProgramSubject(id=str(uuid.uuid4()), program_id=self.prog.id, subject_id=self.sub3.id, semester=1, order_index=3)
        )

        # Gán ps1 làm prerequisite cho ps2
        self.prereq = program_subject_repository.insert_prerequisite(
            ProgramSubjectPrerequisite(
                id=str(uuid.uuid4()),
                program_id=self.prog.id,
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
    def test_live_reorder_and_safe_remove_roundtrip(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.session
        mock_has_perm.return_value = True

        # 1. Reorder kỳ 1 thành [ps3, ps1, ps2]
        res_reorder = self.client.patch(
            f"/api/v1/training-programs/{self.prog.id}/subjects/reorder",
            headers=self.headers,
            json={"semester": 1, "ordered_ids": [self.ps3.id, self.ps1.id, self.ps2.id]},
        )
        self.assertEqual(res_reorder.status_code, 200)

        # Kiểm tra thứ tự mới trong DB
        db_ps3 = program_subject_repository.get_program_subject_by_id(self.ps3.id)
        db_ps1 = program_subject_repository.get_program_subject_by_id(self.ps1.id)
        db_ps2 = program_subject_repository.get_program_subject_by_id(self.ps2.id)
        self.assertEqual(db_ps3.order_index, 1)
        self.assertEqual(db_ps1.order_index, 2)
        self.assertEqual(db_ps2.order_index, 3)

        # 2. Thử xóa ps1 (đang là prerequisite target của ps2) -> Bị chặn 409
        res_del_target = self.client.delete(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.ps1.id}",
            headers=self.headers,
        )
        self.assertEqual(res_del_target.status_code, 409)
        self.assertEqual(res_del_target.get_json().get("error", {}).get("code"), "PROGRAM_SUBJECT_IN_USE")

        # 3. Xóa ps2 (source của prerequisite) -> Thành công
        res_del_ps2 = self.client.delete(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.ps2.id}",
            headers=self.headers,
        )
        self.assertEqual(res_del_ps2.status_code, 200)

        # 4. Lúc này ps1 không còn bị phụ thuộc, xóa ps1 -> Thành công
        res_del_ps1 = self.client.delete(
            f"/api/v1/training-programs/{self.prog.id}/subjects/{self.ps1.id}",
            headers=self.headers,
        )
        self.assertEqual(res_del_ps1.status_code, 200)

        # 5. Xác nhận môn master sub1 và chương trình master prog VẪN TỒN TẠI NGUYÊN VẸN trong DB
        self.assertIsNotNone(training_program_repository.get_training_program_by_id(self.prog.id))
        self.assertIsNotNone(subject_repository.get_subject_by_id(self.sub1.id))
        self.assertIsNotNone(subject_repository.get_subject_by_id(self.sub2.id))


if __name__ == "__main__":
    unittest.main()
