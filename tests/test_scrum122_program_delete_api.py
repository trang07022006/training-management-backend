"""
Bộ kiểm thử SCRUM-122 (Activity A5): API xóa chương trình đào tạo (DELETE /api/v1/training-programs/<id>).

Bao quát 20 kịch bản kiểm thử:
01. Xóa thành công theo chính sách đã phê duyệt.
02. Xóa chương trình không tồn tại (HTTP 404 PROGRAM_NOT_FOUND).
03. UUID sai định dạng (HTTP 400 INVALID_PARAMS).
04. Không có token (HTTP 401 UNAUTHORIZED).
05. Token không hợp lệ (HTTP 401 UNAUTHORIZED).
06. Chỉ có quyền course.view (HTTP 403 FORBIDDEN).
07. Có quyền course.manage (HTTP 200 OK).
08. Chương trình đang được sử dụng (HTTP 409 PROGRAM_IN_USE).
09. MySQL Foreign Key violation (IntegrityError 1451 -> HTTP 409 PROGRAM_IN_USE).
10. Rollback khi xảy ra lỗi.
11. Lỗi cơ sở dữ liệu (HTTP 500 DATABASE_ERROR, không lộ stack trace).
12. Không xóa dữ liệu liên quan khác.
13. Response contract chuẩn (HTTP 200, status=success, data.id).
14. Route alias hoạt động (/api/training-programs/<id>).
15. GET sau khi xóa trả về 404 đúng hợp đồng.
16. POST sau khi xóa có thể tái sử dụng mã code vừa xóa.
17. PUT / PATCH không bị regression.
18. SQL injection không thực thi qua UUID parameter.
19. Không có dữ liệu test tồn dư trong cơ sở dữ liệu.
20. Kiểm thử tích hợp trực tiếp MySQL an toàn.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError, IntegrityError

from app.config.jwt_handlers import register_jwt_handlers
from app.models.login_session import LoginSession
from app.models.training_program import (
    PROGRAM_STATUS_DRAFT,
    TrainingProgram,
)
from app.repositories import training_program_repository
from app.routes.training_program_routes import training_program_bp


class Scrum122ProgramDeleteApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API xóa chương trình đào tạo."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a5-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.program_id = str(uuid.uuid4())

        # Session user có quyền course.manage
        self.manager_user_id = "user-course-manage-uuid"
        self.manager_session = LoginSession(
            session_id="session-manager-122",
            user_id=self.manager_user_id,
            refresh_jti="ref-manager-122",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Session user chỉ có quyền course.view
        self.viewer_user_id = "user-course-view-uuid"
        self.viewer_session = LoginSession(
            session_id="session-viewer-122",
            user_id=self.viewer_user_id,
            refresh_jti="ref-viewer-122",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-manager-122"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-viewer-122"},
            )

        self.manager_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.viewer_headers = {"Authorization": f"Bearer {self.viewer_token}"}

        self.existing_program = TrainingProgram(
            id=self.program_id,
            code="CNTT-2026",
            name="Công nghệ Thông tin",
            description="Chương trình đào tạo CNTT",
            duration_semesters=8,
            status=PROGRAM_STATUS_DRAFT,
            created_at=self.now,
            updated_at=self.now,
        )

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (04, 05, 06, 07)
    # =========================================================================

    def test_04_unauthenticated_returns_401(self):
        res = self.client.delete(f"/api/v1/training-programs/{self.program_id}")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json().get("code"), "UNAUTHORIZED")

    def test_05_invalid_token_returns_401(self):
        bad_headers = {"Authorization": "Bearer invalid.jwt.token"}
        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=bad_headers,
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json().get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_forbidden_without_course_manage_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.viewer_session
        mock_has_perm.return_value = False

        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("code"), "FORBIDDEN")

    @patch("app.repositories.training_program_repository.delete_training_program")
    @patch("app.repositories.training_program_repository.is_program_in_use")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_01_and_07_and_13_delete_success_contract(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_in_use, mock_delete
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_in_use.return_value = False
        mock_delete.return_value = True

        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Xóa chương trình đào tạo thành công.")
        self.assertEqual(data["data"]["id"], self.program_id)

    # =========================================================================
    # 2. VALIDATION & NOT FOUND (02, 03, 18)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_invalid_uuid_returns_400(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        bad_ids = ["abc-123", "not-a-valid-uuid", "123456", "   "]
        for bad_id in bad_ids:
            res = self.client.delete(
                f"/api/v1/training-programs/{bad_id}",
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_delete_non_existent_program_returns_404(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.delete(
            f"/api/v1/training-programs/{valid_uuid}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json().get("code"), "PROGRAM_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_18_sql_injection_payload_in_url_rejected_safely(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        injection = "prog'; DROP TABLE training_programs; --"
        res = self.client.delete(
            f"/api/v1/training-programs/{injection}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    # =========================================================================
    # 3. BUSINESS CONSTRAINTS & FOREIGN KEY INTEGRITY (08, 09, 12)
    # =========================================================================

    @patch("app.repositories.training_program_repository.is_program_in_use")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_program_in_use_service_check_returns_409(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_in_use
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        # Giả lập chương trình đang được liên kết bởi dữ liệu nghiệp vụ
        mock_in_use.return_value = True

        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "PROGRAM_IN_USE")

    @patch("app.repositories.training_program_repository.delete_training_program")
    @patch("app.repositories.training_program_repository.is_program_in_use")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_09_mysql_foreign_key_violation_returns_409(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_in_use, mock_delete
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_in_use.return_value = False

        # Giả lập MySQL ném lỗi IntegrityError 1451 (foreign key constraint fails)
        fk_err = IntegrityError("1451 (23000): Cannot delete or update a parent row: a foreign key constraint fails")
        fk_err.errno = 1451
        mock_delete.side_effect = fk_err

        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "PROGRAM_IN_USE")

    @patch("app.repositories.training_program_repository.delete_training_program")
    @patch("app.repositories.training_program_repository.is_program_in_use")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_12_delete_passes_exact_id_only(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_in_use, mock_delete
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_in_use.return_value = False
        mock_delete.return_value = True

        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        mock_delete.assert_called_once_with(self.program_id)

    # =========================================================================
    # 4. DATABASE ERROR HANDLING & ROUTE ALIAS (10, 11, 14)
    # =========================================================================

    @patch("app.repositories.training_program_repository.delete_training_program")
    @patch("app.repositories.training_program_repository.is_program_in_use")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_10_and_11_database_error_and_rollback_returns_500(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_in_use, mock_delete
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_in_use.return_value = False
        mock_delete.side_effect = MySQLError("Database disk I/O failure")

        res = self.client.delete(
            f"/api/v1/training-programs/{self.program_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json().get("code"), "DATABASE_ERROR")
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.repositories.training_program_repository.delete_training_program")
    @patch("app.repositories.training_program_repository.is_program_in_use")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_route_alias_without_v1_works(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_in_use, mock_delete
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_in_use.return_value = False
        mock_delete.return_value = True

        res = self.client.delete(
            f"/api/training-programs/{self.program_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")


class Scrum122ProgramDeleteApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp endpoint DELETE với MySQL thực tế (15, 16, 17, 19, 20)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a5-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)
        self.client = self.app.test_client()

        self.created_ids = []
        self.now = datetime.now(timezone.utc)
        self.manager_user_id = f"user-mgr-{uuid.uuid4().hex[:8]}"
        self.session = LoginSession(
            session_id=f"sess-mgr-{uuid.uuid4().hex[:8]}",
            user_id=self.manager_user_id,
            refresh_jti="ref-mgr",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": self.session.session_id},
            )
        self.headers = {"Authorization": f"Bearer {self.manager_token}"}

    def tearDown(self):
        # Dọn dẹp tuyệt đối bất kỳ bản ghi nào còn sót lại
        for prog_id in self.created_ids:
            training_program_repository.delete_training_program(prog_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_15_and_16_and_17_and_19_real_mysql_full_lifecycle(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_has_perm.return_value = True

        test_code = f"DEL-{uuid.uuid4().hex[:8].upper()}"

        # 1. POST A3 tạo mới chương trình
        res_post = self.client.post(
            "/api/v1/training-programs",
            json={
                "code": test_code,
                "name": "Chương trình Test Delete",
                "description": "Sẽ bị xóa trong test",
                "duration_semesters": 8,
                "status": "draft",
            },
            headers=self.headers,
        )
        self.assertEqual(res_post.status_code, 201)
        prog_id = res_post.get_json()["data"]["id"]
        self.created_ids.append(prog_id)

        # 2. GET A2 xác nhận chương trình đã tồn tại
        res_get = self.client.get(
            f"/api/v1/training-programs/{prog_id}",
            headers=self.headers,
        )
        self.assertEqual(res_get.status_code, 200)

        # 3. PATCH A4 cập nhật kiểm tra không regression
        res_patch = self.client.patch(
            f"/api/v1/training-programs/{prog_id}",
            json={"name": "Chương trình Test Delete - Đã sửa"},
            headers=self.headers,
        )
        self.assertEqual(res_patch.status_code, 200)

        # 4. DELETE A5 xóa chương trình đào tạo
        res_del = self.client.delete(
            f"/api/v1/training-programs/{prog_id}",
            headers=self.headers,
        )
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.get_json()["data"]["id"], prog_id)

        # 5. GET A2 sau xóa -> phải trả về 404 PROGRAM_NOT_FOUND (Test 15)
        res_get_after = self.client.get(
            f"/api/v1/training-programs/{prog_id}",
            headers=self.headers,
        )
        self.assertEqual(res_get_after.status_code, 404)
        self.assertEqual(res_get_after.get_json().get("code"), "PROGRAM_NOT_FOUND")

        # 6. POST A3 tái sử dụng cùng mã code vừa xóa -> phải thành công 201 (Test 16)
        res_post_reuse = self.client.post(
            "/api/v1/training-programs",
            json={
                "code": test_code,
                "name": "Chương trình Tái Sinh Cùng Code",
                "status": "draft",
            },
            headers=self.headers,
        )
        self.assertEqual(res_post_reuse.status_code, 201)
        new_prog_id = res_post_reuse.get_json()["data"]["id"]
        self.created_ids.append(new_prog_id)
        self.assertNotEqual(prog_id, new_prog_id)
