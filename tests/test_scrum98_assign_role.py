import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.role import Role
from app.models.user import User
from app.routes.user_role_routes import user_role_bp


class Scrum98AssignRoleTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-98: Phân vai trò cho user (POST /api/users/<user_id>/roles).
    1. assign role thành công -> 201
    2. user not found -> 404 USER_NOT_FOUND
    3. role not found -> 404 ROLE_NOT_FOUND
    4. duplicate mapping -> 409 DUPLICATE_ROLE_ASSIGNMENT
    5. invalid role (thiếu trường hoặc rỗng) -> 400
    6. unauthenticated -> 401
    7. forbidden (không có quyền user.manage) -> 403
    8. SQL injection payload được xử lý an toàn dạng text, không gây lỗi
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum98-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_role_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-user-98"
        self.session_id = "session-98"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-jti-98",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.session_id},
            )
            self.unprivileged_token = create_access_token(
                identity="normal-user-98",
                additional_claims={"sid": "normal-session-98"},
            )

        self.target_user = User(
            id="target-user-98",
            email="trainee@daotao.edu.vn",
            name="Học Viên 98",
            role="user",
            status="active",
        )

        self.trainer_role = Role(
            id="role-trainer-uuid",
            code="trainer",
            name="Giảng viên",
            description="Quản lý đào tạo",
        )

    # 1. assign role thành công -> 201
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id")
    @patch("app.services.user_role_service.user_role_repository.check_user_role_exists", return_value=False)
    @patch("app.services.user_role_service.user_role_repository.assign_role_to_user")
    @patch("app.services.user_role_service.user_role_repository.get_primary_role_code_by_user_id", return_value="trainer")
    @patch("app.services.user_role_service.user_repository.update_user")
    def test_01_assign_role_success(
        self, mock_update, mock_primary, mock_assign, mock_exists, mock_get_role, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_role.return_value = self.trainer_role

        resp = self.client.post(
            "/api/users/target-user-98/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"role_id": "role-trainer-uuid"},
        )
        self.assertEqual(resp.status_code, 201)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertEqual(json_data["data"]["user_id"], "target-user-98")
        self.assertEqual(json_data["data"]["role"]["code"], "trainer")
        mock_assign.assert_called_once_with("target-user-98", "role-trainer-uuid")

    # 2. user not found -> 404
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id", return_value=None)
    def test_02_user_not_found(self, mock_get_user, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session

        resp = self.client.post(
            "/api/users/non-existent-user/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"role_id": "role-trainer-uuid"},
        )
        self.assertEqual(resp.status_code, 404)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "USER_NOT_FOUND")

    # 3. role not found -> 404
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id", return_value=None)
    @patch("app.services.user_role_service.role_repository.get_role_by_code", return_value=None)
    def test_03_role_not_found(
        self, mock_get_code, mock_get_id, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user

        resp = self.client.post(
            "/api/users/target-user-98/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"role_id": "invalid-role-id"},
        )
        self.assertEqual(resp.status_code, 404)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "ROLE_NOT_FOUND")

    # 4. duplicate mapping -> 409 DUPLICATE_ROLE_ASSIGNMENT
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id")
    @patch("app.services.user_role_service.user_role_repository.check_user_role_exists", return_value=True)
    def test_04_duplicate_role_mapping(
        self, mock_exists, mock_get_role, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_role.return_value = self.trainer_role

        resp = self.client.post(
            "/api/users/target-user-98/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"role_id": "role-trainer-uuid"},
        )
        self.assertEqual(resp.status_code, 409)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "DUPLICATE_ROLE_ASSIGNMENT")

    # 5. invalid role input -> 400
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_invalid_role_missing(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session

        resp = self.client.post(
            "/api/users/target-user-98/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={},
        )
        self.assertEqual(resp.status_code, 400)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "ROLE_REQUIRED")

    # 6. unauthenticated -> 401
    def test_06_unauthenticated(self):
        resp = self.client.post(
            "/api/users/target-user-98/roles",
            json={"role_id": "role-trainer-uuid"},
        )
        self.assertEqual(resp.status_code, 401)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "UNAUTHORIZED")

    # 7. forbidden -> 403
    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_forbidden(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = LoginSession(
            session_id="normal-session-98",
            user_id="normal-user-98",
            refresh_jti="ref-98",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        resp = self.client.post(
            "/api/users/target-user-98/roles",
            headers={"Authorization": f"Bearer {self.unprivileged_token}"},
            json={"role_id": "role-trainer-uuid"},
        )
        self.assertEqual(resp.status_code, 403)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "FORBIDDEN")

    # 8. SQL injection payload treated as data
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id", return_value=None)
    @patch("app.services.user_role_service.role_repository.get_role_by_code", return_value=None)
    def test_08_sql_injection_payload_treated_safely(
        self, mock_get_code, mock_get_id, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user

        sqli_payload = "' OR 1=1; DROP TABLE users; --"
        resp = self.client.post(
            "/api/users/target-user-98/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"role_id": sqli_payload},
        )
        self.assertEqual(resp.status_code, 404)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "ROLE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
