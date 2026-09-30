import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.role import Role
from app.routes.user_role_routes import user_role_bp


class Scrum97AvailableRolesApiTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-97: Danh sách role hợp lệ (GET /api/roles).
    1. list roles thành công
    2. empty list an toàn
    3. unauthenticated -> 401
    4. no permission -> 403
    5. response không leak internals
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum97-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_role_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-user-97"
        self.session_id = "session-97"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-jti-97",
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
                identity="normal-user-97",
                additional_claims={"sid": "normal-session-97"},
            )

        self.mock_roles = [
            Role(id="role-id-admin", code="admin", name="Quản trị viên", description="Toàn quyền hệ thống"),
            Role(id="role-id-trainer", code="trainer", name="Giảng viên", description="Quản lý đào tạo"),
            Role(id="role-id-trainee", code="trainee", name="Học viên", description="Tham gia đào tạo"),
            Role(id="role-id-user", code="user", name="Người dùng", description="Người dùng thường"),
        ]

    # 1. list roles thành công
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.role_repository.get_all_roles")
    def test_01_list_roles_success(self, mock_get_all, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session
        mock_get_all.return_value = self.mock_roles

        resp = self.client.get(
            "/api/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertIn("items", json_data["data"])
        items = json_data["data"]["items"]
        self.assertEqual(len(items), 4)
        codes = [item["code"] for item in items]
        self.assertEqual(codes, ["admin", "trainer", "trainee", "user"])

    # 2. empty list an toàn
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.role_repository.get_all_roles")
    def test_02_empty_roles_list_safe(self, mock_get_all, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session
        mock_get_all.return_value = []

        resp = self.client.get(
            "/api/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertEqual(json_data["status"], "success")
        self.assertEqual(json_data["data"]["items"], [])

    # 3. unauthenticated -> 401
    def test_03_unauthenticated(self):
        resp = self.client.get("/api/roles")
        self.assertEqual(resp.status_code, 401)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "UNAUTHORIZED")

    # 4. no permission -> 403
    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_no_permission(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = LoginSession(
            session_id="normal-session-97",
            user_id="normal-user-97",
            refresh_jti="ref-97",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        resp = self.client.get(
            "/api/roles",
            headers={"Authorization": f"Bearer {self.unprivileged_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "FORBIDDEN")

    # 5. response không leak internals
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.role_repository.get_all_roles")
    def test_05_no_internal_leak(self, mock_get_all, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.session
        mock_get_all.return_value = self.mock_roles

        resp = self.client.get(
            "/api/roles",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        raw_text = resp.get_data(as_text=True)
        self.assertNotIn("password_hash", raw_text)
        self.assertNotIn("role_permissions", raw_text)
        self.assertNotIn("perm-id-", raw_text)


if __name__ == "__main__":
    unittest.main()
