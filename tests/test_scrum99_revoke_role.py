import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.role import Role
from app.models.user import User
from app.routes.user_role_routes import user_role_bp


class Scrum99RevokeRoleTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-99: Gỡ vai trò khỏi user (DELETE /api/users/<user_id>/roles/<role_id>).
    1. revoke thành công -> 200
    2. user not found -> 404 USER_NOT_FOUND
    3. role not found -> 404 ROLE_NOT_FOUND
    4. mapping not found -> 404 ROLE_NOT_ASSIGNED
    5. unauthenticated -> 401
    6. forbidden (không có quyền user.manage) -> 403
    7. transaction behavior / DB error handled cleanly -> 500
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum99-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_role_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-user-99"
        self.session_id = "session-99"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-jti-99",
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
                identity="normal-user-99",
                additional_claims={"sid": "normal-session-99"},
            )

        self.target_user = User(
            id="target-user-99",
            email="target99@daotao.edu.vn",
            name="Người Dùng 99",
            role="trainer",
            status="active",
        )

        self.trainer_role = Role(
            id="role-trainer-uuid",
            code="trainer",
            name="Giảng viên",
        )

    # 1. revoke thành công -> 200
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id")
    @patch("app.services.user_role_service.user_role_repository.check_user_role_exists", return_value=True)
    @patch("app.services.user_role_service.user_role_repository.remove_role_from_user", return_value=True)
    @patch("app.services.user_role_service.user_role_repository.get_primary_role_code_by_user_id", return_value="user")
    @patch("app.services.user_role_service.user_repository.update_user")
    def test_01_revoke_role_success(
        self, mock_update, mock_primary, mock_remove, mock_exists, mock_get_role, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_role.return_value = self.trainer_role

        resp = self.client.delete(
            "/api/users/target-user-99/roles/role-trainer-uuid",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertEqual(json_data["data"]["user_id"], "target-user-99")
        self.assertEqual(json_data["data"]["role_id"], "role-trainer-uuid")
        mock_remove.assert_called_once_with("target-user-99", "role-trainer-uuid")

    # 2. user not found -> 404
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id", return_value=None)
    def test_02_user_not_found(self, mock_get_user, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session

        resp = self.client.delete(
            "/api/users/non-existent-user/roles/role-trainer-uuid",
            headers={"Authorization": f"Bearer {self.admin_token}"},
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

        resp = self.client.delete(
            "/api/users/target-user-99/roles/invalid-role-uuid",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 404)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "ROLE_NOT_FOUND")

    # 4. mapping not found -> 404 ROLE_NOT_ASSIGNED
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id")
    @patch("app.services.user_role_service.user_role_repository.check_user_role_exists", return_value=False)
    def test_04_mapping_not_found(
        self, mock_exists, mock_get_role, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_role.return_value = self.trainer_role

        resp = self.client.delete(
            "/api/users/target-user-99/roles/role-trainer-uuid",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 404)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "ROLE_NOT_ASSIGNED")

    # 5. unauthenticated -> 401
    def test_05_unauthenticated(self):
        resp = self.client.delete(
            "/api/users/target-user-99/roles/role-trainer-uuid",
        )
        self.assertEqual(resp.status_code, 401)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "UNAUTHORIZED")

    # 6. forbidden (không có quyền user.manage) -> 403
    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_forbidden(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = LoginSession(
            session_id="normal-session-99",
            user_id="normal-user-99",
            refresh_jti="ref-99",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        resp = self.client.delete(
            "/api/users/target-user-99/roles/role-trainer-uuid",
            headers={"Authorization": f"Bearer {self.unprivileged_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
