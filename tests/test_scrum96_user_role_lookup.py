import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.role import Role
from app.models.user import User
from app.routes.user_role_routes import user_role_bp


class Scrum96UserRoleLookupTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-96: Đọc vai trò của user (GET /api/users/<user_id>/roles).
    1. user có 1 role
    2. user không có role
    3. user nhiều role
    4. user không tồn tại -> 404 USER_NOT_FOUND
    5. unauthenticated -> 401
    6. no permission -> 403
    7. authorized -> success, không leak internal permissions
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum96-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_role_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-user-96"
        self.session_id = "session-96"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-jti-96",
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
                identity="normal-user-96",
                additional_claims={"sid": "normal-session-96"},
            )

        self.target_user = User(
            id="target-user-1",
            email="target@daotao.edu.vn",
            name="Nguyễn Văn Mục Tiêu",
            role="trainer",
            status="active",
        )

    # 1. user có 1 role
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.user_role_repository.get_roles_by_user_id")
    def test_01_user_with_single_role(
        self, mock_get_roles, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_roles.return_value = [
            Role(id="role-trainer-id", code="trainer", name="Giảng viên", description="Mô tả trainer")
        ]

        resp = self.client.get(
            "/api/users/target-user-1/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertEqual(json_data["data"]["user_id"], "target-user-1")
        self.assertEqual(len(json_data["data"]["roles"]), 1)
        self.assertEqual(json_data["data"]["roles"][0]["code"], "trainer")

    # 2. user không có role
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.user_role_repository.get_roles_by_user_id")
    def test_02_user_with_no_roles(
        self, mock_get_roles, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_roles.return_value = []

        resp = self.client.get(
            "/api/users/target-user-1/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertEqual(json_data["data"]["roles"], [])

    # 3. user nhiều role
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.user_role_repository.get_roles_by_user_id")
    def test_03_user_with_multiple_roles(
        self, mock_get_roles, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_roles.return_value = [
            Role(id="r-1", code="trainer", name="Giảng viên"),
            Role(id="r-2", code="trainee", name="Học viên"),
        ]

        resp = self.client.get(
            "/api/users/target-user-1/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(len(json_data["data"]["roles"]), 2)
        codes = [r["code"] for r in json_data["data"]["roles"]]
        self.assertEqual(codes, ["trainer", "trainee"])

    # 4. user không tồn tại -> 404 USER_NOT_FOUND
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id", return_value=None)
    def test_04_user_not_found(self, mock_get_user, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session

        resp = self.client.get(
            "/api/users/non-existent-user/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 404)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "USER_NOT_FOUND")

    # 5. unauthenticated -> 401
    def test_05_unauthenticated(self):
        resp = self.client.get("/api/users/target-user-1/roles")
        self.assertEqual(resp.status_code, 401)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "UNAUTHORIZED")

    # 6. no permission -> 403
    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_no_permission(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = LoginSession(
            session_id="normal-session-96",
            user_id="normal-user-96",
            refresh_jti="ref-96",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        resp = self.client.get(
            "/api/users/target-user-1/roles",
            headers={"Authorization": f"Bearer {self.unprivileged_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "FORBIDDEN")

    # 7. authorized -> success, không leak internal permissions
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.user_role_repository.get_roles_by_user_id")
    def test_07_authorized_success_no_internal_leak(
        self, mock_get_roles, mock_get_user, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.target_user
        mock_get_roles.return_value = [
            Role(id="r-admin", code="admin", name="Quản trị viên", description="Toàn quyền")
        ]

        resp = self.client.get(
            "/api/users/target-user-1/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        raw_text = resp.get_data(as_text=True)
        self.assertNotIn("password_hash", raw_text)
        self.assertNotIn("role_permissions", raw_text)
        self.assertNotIn("perm-id-", raw_text)


if __name__ == "__main__":
    unittest.main()
