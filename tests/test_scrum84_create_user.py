import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.routes.user_routes import user_bp


class Scrum84CreateUserTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-84: Create User (POST /api/users).
    1. Valid create -> 201 Created với thông tin user
    2. Missing required fields (email, password, name) -> 400
    3. Invalid email -> 400
    4. Invalid phone -> 400
    5. Password policy violation -> 400
    6. Unauthorized -> 401
    7. Forbidden (thiếu quyền user.manage) -> 403
    8. Created user không trả password_hash
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum84-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "test-admin-84"
        self.session_id = "test-session-84"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-84",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_email")
    @patch("app.services.user_service.user_repository.create_user")
    @patch("app.services.user_service.role_repository.get_role_by_code")
    @patch("app.services.user_service.user_role_repository.assign_role_to_user")
    def test_01_valid_create_returns_201_and_user_data(
        self,
        mock_assign_role,
        mock_get_role,
        mock_create_user,
        mock_get_by_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage", "user.view"]
        mock_get_by_email.return_value = None
        mock_get_role.return_value = Role(id="r-trainer", code="trainer", name="Trainer")

        def side_effect_create(user):
            user.id = "new-uuid-123"
            return user
        mock_create_user.side_effect = side_effect_create

        token = self._create_token()
        payload = {
            "name": "Nguyễn Văn A",
            "email": "nguyenvana@daotao.edu.vn",
            "password": "Password123",
            "phone": "0912345678",
            "role": "trainer",
            "status": "active",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["email"], "nguyenvana@daotao.edu.vn")
        self.assertEqual(data["data"]["name"], "Nguyễn Văn A")
        self.assertEqual(data["data"]["role"], "trainer")
        self.assertEqual(data["data"]["status"], "active")
        # Ensure password_hash is not exposed
        self.assertNotIn("password_hash", data["data"])
        self.assertNotIn("Password123", res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_missing_required_fields_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()

        # Missing email
        res = self.client.post("/api/users", json={"name": "A", "password": "Password123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "EMAIL_REQUIRED")

        # Missing password
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_REQUIRED")

        # Missing name
        res = self.client.post("/api/users", json={"email": "a@daotao.edu.vn", "password": "Password123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NAME_REQUIRED")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_invalid_email_format_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        payload = {"name": "Test", "email": "invalid-email-format", "password": "Password123"}
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_EMAIL")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_invalid_phone_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        payload = {"name": "Test", "email": "user@daotao.edu.vn", "password": "Password123", "phone": "abc123notaphone"}
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PHONE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_password_policy_violation_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()

        # Too short (< 8 chars)
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn", "password": "Pass1"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_TOO_SHORT")

        # Missing digits
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn", "password": "PasswordOnly"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

        # Missing letters
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn", "password": "123456789"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

    def test_06_unauthenticated_request_fails_with_401(self):
        payload = {"name": "Test", "email": "a@daotao.edu.vn", "password": "Password123"}
        res = self.client.post("/api/users", json=payload)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_user_without_manage_permission_forbidden_with_403(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        # Trainee only has course.view, not user.manage
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        payload = {"name": "Test", "email": "a@daotao.edu.vn", "password": "Password123"}
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_email")
    @patch("app.services.user_service.user_repository.create_user")
    def test_08_created_user_never_exposes_password_hash(
        self,
        mock_create_user,
        mock_get_by_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_by_email.return_value = None

        def side_effect_create(user):
            user.id = "u-secret-check"
            return user
        mock_create_user.side_effect = side_effect_create

        token = self._create_token()
        payload = {
            "name": "Bảo Mật",
            "email": "secure@daotao.edu.vn",
            "password": "SecurePassword999",
            "phone": "0988776655",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 201)

        raw_response = res.get_data(as_text=True)
        self.assertNotIn("password_hash", raw_response)
        self.assertNotIn("scrypt:", raw_response)
        self.assertNotIn("pbkdf2:", raw_response)
        self.assertNotIn("SecurePassword999", raw_response)


if __name__ == "__main__":
    unittest.main()
