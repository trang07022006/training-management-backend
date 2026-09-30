import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector.errors import IntegrityError

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.routes.user_routes import user_bp


class Scrum85DuplicateEmailTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-85: Duplicate Email Validation.
    1. Duplicate exact email -> 409 DUPLICATE_EMAIL
    2. Duplicate different casing (case-insensitive normalization) -> 409 DUPLICATE_EMAIL
    3. New email allowed -> 201 Created
    4. Database duplicate exception (IntegrityError 1062 race condition) -> 409 DUPLICATE_EMAIL
    5. Response user-friendly, không leak SQL, tracebacks hay DB internals
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum85-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "admin-85"
        self.session_id = "session-85"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-85",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

    def _create_token(self):
        with self.app.app_context():
            return create_access_token(
                identity=self.user_id,
                additional_claims={"sid": self.session_id},
            )

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    def test_01_duplicate_exact_email_rejected_with_409(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_check_email.return_value = True

        token = self._create_token()
        payload = {
            "name": "Nguyễn Văn B",
            "email": "existing@daotao.edu.vn",
            "password": "Password123",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "DUPLICATE_EMAIL")
        self.assertIn("đã được sử dụng", data["message"])
        mock_check_email.assert_called_with("existing@daotao.edu.vn")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    def test_02_duplicate_different_casing_rejected_with_409(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_check_email.return_value = True

        token = self._create_token()
        # Input has uppercase letters and whitespace
        payload = {
            "name": "Nguyễn Văn C",
            "email": "  Admin_Test@DaoTao.Edu.Vn  ",
            "password": "Password123",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "DUPLICATE_EMAIL")
        # Ensure email was normalized before check
        mock_check_email.assert_called_with("admin_test@daotao.edu.vn")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    @patch("app.services.user_service.user_repository.create_user")
    @patch("app.services.user_service.role_repository.get_role_by_code")
    @patch("app.services.user_service.user_role_repository.assign_role_to_user")
    def test_03_new_email_allowed_and_creates_user(
        self,
        mock_assign_role,
        mock_get_role,
        mock_create_user,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_check_email.return_value = False
        mock_get_role.return_value = Role(id="r-user", code="user", name="User")

        def side_effect(user):
            user.id = "new-uuid-85"
            return user
        mock_create_user.side_effect = side_effect

        token = self._create_token()
        payload = {
            "name": "User Mới",
            "email": "brandnew@daotao.edu.vn",
            "password": "Password123",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["email"], "brandnew@daotao.edu.vn")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    @patch("app.services.user_service.user_repository.create_user")
    def test_04_db_duplicate_exception_mapped_correctly(
        self,
        mock_create_user,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        # Simulate race condition: check_email_exists returned False, but DB insert raises duplicate entry error
        mock_check_email.return_value = False

        db_err = IntegrityError(errno=1062, msg="Duplicate entry 'race@daotao.edu.vn' for key 'users.email'")
        mock_create_user.side_effect = db_err

        token = self._create_token()
        payload = {
            "name": "Race User",
            "email": "race@daotao.edu.vn",
            "password": "Password123",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "DUPLICATE_EMAIL")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    def test_05_response_does_not_leak_sql_or_database_internals(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_check_email.return_value = True

        token = self._create_token()
        payload = {
            "name": "Leak Check",
            "email": "checkleak@daotao.edu.vn",
            "password": "Password123",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        raw = res.get_data(as_text=True)

        self.assertNotIn("SELECT", raw)
        self.assertNotIn("FROM", raw)
        self.assertNotIn("INSERT INTO", raw)
        self.assertNotIn("Traceback", raw)
        self.assertNotIn("IntegrityError", raw)
        self.assertNotIn("errno", raw)


if __name__ == "__main__":
    unittest.main()
