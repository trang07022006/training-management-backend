import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.routes.user_routes import user_bp
from app.services.session_service import SessionValidationError


class Scrum73ForbiddenResponsesTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-73: Xử lý truy cập không có quyền (Forbidden Response Handling).
    Nguyên tắc kiểm thử:
    1. Phân biệt rõ 401 (Authentication) và 403 (Authorization).
    2. Không trả về 200 kèm error message.
    3. Không leak role mapping nội bộ, permission list nhạy cảm, SQL details, stack trace.
    4. Thông báo tiếng Việt rõ ràng, chuẩn mực.
    5. DB failure không trở thành allow.
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum73-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)
        self.client = self.app.test_client()

        self.now = datetime.now(timezone.utc)
        self.user_id = "test-user-73"
        self.session_id = "test-session-73"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="test-jti-73",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=None,
        )

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    # 1. unauthenticated -> đúng authentication error (401)
    def test_01_unauthenticated_returns_401_authentication_error(self):
        res = self.client.get("/api/users")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data["code"], "UNAUTHORIZED")
        self.assertIn("đăng nhập", data["message"].lower())

    # 2. authenticated + no permission -> 403
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_authenticated_without_permission_returns_403(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        # User chỉ có role trainee không có quyền user.manage
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post(
            "/api/users",
            json={"email": "victim@daotao.edu.vn"},
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(res.status_code, 403)
        self.assertNotEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")
        self.assertEqual(data["message"], "Bạn không có quyền thực hiện thao tác này.")

    # 3. authenticated + permission -> success (200)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_authenticated_with_permission_returns_success(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-trainer", code="trainer", name="Trainer")]
        mock_rp_codes.return_value = ["user.view"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    # 4. response unauthorized / forbidden không leak role/permission internals, SQL, secrets
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_forbidden_response_does_not_leak_internals(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post("/api/users", json={}, headers={"Authorization": f"Bearer {token}"})

        body = res.get_data(as_text=True)
        # Không lộ câu lệnh SQL
        self.assertNotIn("SELECT", body)
        self.assertNotIn("FROM", body)
        self.assertNotIn("user_roles", body)
        self.assertNotIn("role_permissions", body)
        # Không lộ danh sách quyền nội bộ của role
        self.assertNotIn("course.view", body)
        # Không lộ trace lỗi / stacktrace
        self.assertNotIn("Traceback", body)
        self.assertNotIn("Exception", body)
        # Không lộ secret token
        self.assertNotIn(token, body)

    # 5. unknown permission -> deny an toàn (403)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_05_unknown_permission_denies_safely(self, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = None  # Không có permission

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 6. DB failure không trở thành allow
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    def test_06_db_failure_does_not_become_allow(self, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.side_effect = MySQLError("Database connection down")

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertNotEqual(res.status_code, 200)
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")

    # 7. response tiếng Việt rõ ràng
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_clear_vietnamese_messages(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post("/api/users", json={}, headers={"Authorization": f"Bearer {token}"})

        data = res.get_json()
        self.assertEqual(data["message"], "Bạn không có quyền thực hiện thao tác này.")

    # 8. session validation error -> 401 tiếng Việt
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_session_expired_message(self, mock_get_session):
        mock_get_session.return_value = self.session
        with patch("app.utils.rbac_auth.validate_login_session", side_effect=SessionValidationError("SESSION_EXPIRED")):
            token = self._create_token()
            res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

            self.assertEqual(res.status_code, 401)
            data = res.get_json()
            self.assertEqual(data["code"], "SESSION_EXPIRED")
            self.assertIn("hết hạn", data["message"].lower())


if __name__ == "__main__":
    unittest.main()
