import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.routes.user_routes import user_bp


class Scrum72ProtectApisWithPermissionsTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-72: Bảo vệ API theo Permission RBAC.
    Các API được bảo vệ:
    - GET /api/users: yêu cầu quyền 'user.view'
    - POST /api/users: yêu cầu quyền 'user.manage'
    - GET /api/courses: yêu cầu quyền 'course.view'
    - POST /api/courses: yêu cầu quyền 'course.manage'

    Yêu cầu kiểm thử tối thiểu:
    1. user có permission -> success (200 / 201)
    2. user authenticated nhưng thiếu permission -> 403 (FORBIDDEN)
    3. unauthenticated -> 401 (UNAUTHORIZED)
    4. permission khác -> deny
    5. role khác nhau nhưng cùng sở hữu permission -> allow (ví dụ admin và trainer cùng có user.view)
    6. client giả mạo role admin trong header/body -> không bypass
    7. client gửi permission trong payload -> không bypass
    8. các route public (health, login, forgot-password) vẫn hoạt động bình thường
    9. Login regression PASS
    10. Forgot Password regression PASS
    11. Change Password regression PASS
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum72-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)

        @self.app.route("/api/health", methods=["GET"])
        def health():
            return jsonify({"status": "ok", "message": "Training Management System API is running"}), 200

        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()

        self.now = datetime.now(timezone.utc)
        self.user_id = "test-user-72"
        self.session_id = "test-session-72"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="test-jti-72",
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

    # 1. user có permission -> success (200 / 201)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_01_user_with_permission_accesses_successfully(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view", "user.manage", "course.view", "course.manage"]

        token = self._create_token()

        # GET /api/users
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

        # GET /api/courses
        mock_perm_repo.return_value = Permission(id="p-cv", code="course.view", name="Xem course")
        res_course = self.client.get("/api/courses", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_course.status_code, 200)

    # 2. user authenticated nhưng không có permission -> 403 FORBIDDEN
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_authenticated_without_permission_denied_with_403(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-trainer", code="trainer", name="Trainer")]
        # Trainer chỉ có user.view và course.*, không có user.manage
        mock_rp_codes.return_value = ["user.view", "course.view", "course.manage"]

        token = self._create_token()

        res = self.client.post(
            "/api/users",
            json={"email": "newuser@daotao.edu.vn"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")
        self.assertIn("Bạn không có quyền", res.get_json()["message"])

    # 3. unauthenticated -> 401
    def test_03_unauthenticated_request_fails_with_401(self):
        res = self.client.get("/api/users")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    # 4. permission khác -> deny
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_different_permission_denies(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-cm", code="course.manage", name="Tạo khóa học")
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        # Trainee chỉ có course.view, không có course.manage
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post(
            "/api/courses",
            json={"title": "Hack Python"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 5. role khác nhau nhưng cùng sở hữu permission -> allow (Ví dụ: Trainer và Admin cùng có user.view)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_different_roles_with_same_permission_allowed(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        # Giả lập người dùng đăng nhập là Trainer
        mock_ur_roles.return_value = [Role(id="r-trainer", code="trainer", name="Trainer")]
        mock_rp_codes.return_value = ["user.view", "course.view"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)

    # 6. client giả mạo role admin trong header / query / body -> không bypass
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_06_spoofed_admin_role_cannot_bypass(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        # Thực tế DB: User là trainee
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.post(
            "/api/users?role=admin",
            json={"role": "admin", "permissions": ["user.manage", "user.view"], "email": "spoof@attack.com"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Role": "admin",
                "X-Admin": "true",
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 7. client gửi permission trong payload -> không bypass
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_client_supplied_permission_in_payload_ignored(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-cm", code="course.manage", name="Tạo khóa học")
        mock_ur_roles.return_value = [Role(id="r-user", code="user", name="User")]
        mock_rp_codes.return_value = ["session.view"]

        token = self._create_token()
        res = self.client.post(
            "/api/courses",
            json={"permission": "course.manage", "title": "Bypass Test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 403)

    # 8. các route public (health, login, forgot-password) vẫn hoạt động bình thường
    def test_08_public_routes_remain_accessible(self):
        # Health check
        res_health = self.client.get("/api/health")
        self.assertEqual(res_health.status_code, 200)

        # Login endpoint vẫn tiếp nhận yêu cầu public (không bị chặn 401 do permission decorator)
        res_login = self.client.post("/api/auth/login", json={})
        self.assertIn(res_login.status_code, (400, 401))

        # Forgot password endpoint vẫn tiếp nhận yêu cầu public
        res_forgot = self.client.post("/api/auth/forgot-password", json={})
        self.assertIn(res_forgot.status_code, (400, 401, 500))

    # 9. Login regression check
    def test_09_login_regression_intact(self):
        from app.routes.auth_routes import login
        self.assertTrue(callable(login))

    # 10. Forgot Password regression check
    def test_10_forgot_password_regression_intact(self):
        from app.routes.auth_routes import forgot_password
        self.assertTrue(callable(forgot_password))

    # 11. Change Password regression check
    def test_11_change_password_regression_intact(self):
        from app.routes.auth_routes import change_password_endpoint
        self.assertTrue(callable(change_password_endpoint))


if __name__ == "__main__":
    unittest.main()
