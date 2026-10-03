"""
Bộ kiểm thử hồi quy SCRUM-26: Phân quyền đa vai trò (Multi-Role RBAC Authorization).
Kiểm tra:
- One role vs Multiple roles (Effective permissions = UNION quyền)
- Login API trả đầy đủ roles array và union permissions
- Session API (/api/auth/session) trả roles và permissions
- Backend protected API (@permission_required) với multi-role
- Gán vai trò rồi login lại -> nhận đầy đủ quyền mới
- Gỡ vai trò rồi login lại -> mất quyền đã gỡ (403 Forbidden)
- Bảo vệ API Admin vẫn chặn người dùng trainee + trainer
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager

from app.models.role import Role
from app.models.user import User
from app.models.login_session import LoginSession
from app.routes.auth_routes import auth_bp
from app.routes.session_routes import session_bp
from app.routes.user_routes import user_bp
from app.services.authorization_service import get_user_permissions, has_permission
from app.services.token_service import create_login_tokens


class Scrum26MultiRoleAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-key-for-scrum26-multi-role-testing",
        )
        JWTManager(self.app)
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(session_bp)
        self.app.register_blueprint(user_bp)
        self.client = self.app.test_client()

        self.role_trainee = Role(
            id="role-id-trainee",
            code="trainee",
            name="Học viên",
        )
        self.role_trainer = Role(
            id="role-id-trainer",
            code="trainer",
            name="Giảng viên",
        )
        self.role_admin = Role(
            id="role-id-admin",
            code="admin",
            name="Quản trị viên",
        )

        self.trainee_permissions = ["course.view", "session.view"]
        self.trainer_permissions = ["course.manage", "course.view", "session.view"]
        self.admin_permissions = [
            "user.view",
            "user.manage",
            "course.view",
            "course.manage",
            "session.view",
            "session.revoke",
        ]

    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    def test_single_role_permissions(self, mock_get_roles, mock_get_perms):
        """1 vai trò (trainee) chỉ có quyền của vai trò đó."""
        mock_get_roles.return_value = [self.role_trainee]
        mock_get_perms.side_effect = lambda role_id: (
            self.trainee_permissions if role_id == "role-id-trainee" else []
        )

        perms = get_user_permissions("user-1")
        self.assertEqual(sorted(perms), ["course.view", "session.view"])
        self.assertIn("course.view", perms)
        self.assertNotIn("course.manage", perms)
        self.assertNotIn("user.manage", perms)

    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    def test_multiple_roles_union_permissions(self, mock_get_roles, mock_get_perms):
        """Nhiều vai trò (trainee + trainer): effective permissions là UNION của cả hai vai trò."""
        mock_get_roles.return_value = [self.role_trainee, self.role_trainer]
        mock_get_perms.side_effect = lambda role_id: (
            self.trainee_permissions if role_id == "role-id-trainee"
            else self.trainer_permissions if role_id == "role-id-trainer"
            else []
        )

        perms = get_user_permissions("user-multi")
        # Union của trainee và trainer: course.manage, course.view, session.view
        self.assertEqual(sorted(perms), ["course.manage", "course.view", "session.view"])
        self.assertIn("course.manage", perms)
        self.assertIn("course.view", perms)
        self.assertIn("session.view", perms)
        # Vẫn không có quyền Admin
        self.assertNotIn("user.view", perms)
        self.assertNotIn("user.manage", perms)

    @patch("app.routes.auth_routes.authorization_service.get_user_permissions")
    @patch("app.routes.auth_routes.user_role_repository.get_role_codes_by_user_id")
    @patch("app.routes.auth_routes.authenticate_and_login")
    def test_login_returns_roles_array_and_union_permissions(
        self, mock_auth_login, mock_get_roles, mock_get_perms
    ):
        """Login trả về đầy đủ roles array và effective union permissions."""
        user = User(
            id="user-multi-login",
            email="ictu.multi@daotao.edu.vn",
            name="Học viên Test ICTU",
            role="trainee",
            status="active",
        )
        now = datetime.now(timezone.utc)
        session = LoginSession(
            session_id="sess-multi",
            user_id=user.id,
            refresh_jti="jti-refresh",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now,
            absolute_expires_at=now,
        )
        with self.app.app_context():
            tokens = create_login_tokens(user.id, session.session_id, roles=["trainee", "trainer"])

        mock_auth_login.return_value = (user, session, tokens)
        mock_get_roles.return_value = ["trainee", "trainer"]
        mock_get_perms.return_value = ["course.manage", "course.view", "session.view"]

        resp = self.client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "Demo@123456"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertIn("roles", data["user"])
        self.assertIn("permissions", data["user"])
        self.assertEqual(data["user"]["roles"], ["trainee", "trainer"])
        self.assertEqual(
            sorted(data["user"]["permissions"]),
            ["course.manage", "course.view", "session.view"],
        )
        # Display role vẫn tương thích
        self.assertEqual(data["user"]["role"], "trainee")

    @patch("app.routes.session_routes.authorization_service.get_user_permissions")
    @patch("app.routes.session_routes.user_role_repository.get_role_codes_by_user_id")
    @patch("app.routes.session_routes.user_repository.get_user_by_id")
    @patch("app.utils.session_auth.get_session_by_id")
    def test_session_endpoint_returns_roles_and_permissions(
        self, mock_get_session, mock_get_user, mock_get_roles, mock_get_perms
    ):
        """GET /api/auth/session trả về roles và permissions sau khi reload trang."""
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        session = LoginSession(
            session_id="sess-123",
            user_id="user-multi-session",
            refresh_jti="jti-123",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )
        mock_get_session.return_value = session
        mock_get_user.return_value = User(
            id="user-multi-session",
            email="ictu@daotao.edu.vn",
            role="trainee",
            status="active",
        )
        mock_get_roles.return_value = ["trainee", "trainer"]
        mock_get_perms.return_value = ["course.manage", "course.view", "session.view"]

        with self.app.app_context():
            tokens = create_login_tokens(session.user_id, session.session_id)

        resp = self.client.get(
            "/api/auth/session",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["roles"], ["trainee", "trainer"])
        self.assertEqual(sorted(data["permissions"]), ["course.manage", "course.view", "session.view"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_protected_api_with_multi_role(self, mock_get_session, mock_has_perm):
        """API được bảo vệ bằng permission_required: cho phép khi user có quyền từ vai trò phụ, chặn khi không có quyền."""
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        session = LoginSession(
            session_id="sess-api",
            user_id="user-api",
            refresh_jti="jti-api",
            created_at=now,
            last_activity_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )
        mock_get_session.return_value = session

        with self.app.app_context():
            tokens = create_login_tokens(session.user_id, session.session_id)

        # 1. Truy cập endpoint course.manage (POST /api/courses) - được phép nhờ role trainer
        mock_has_perm.side_effect = lambda uid, code: code == "course.manage"
        resp = self.client.post(
            "/api/courses",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        self.assertEqual(resp.status_code, 201)

        # 2. Truy cập endpoint user.view (GET /api/users) - bị từ chối 403 vì trainee+trainer không có quyền admin
        mock_has_perm.side_effect = lambda uid, code: False
        resp = self.client.get(
            "/api/users",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
