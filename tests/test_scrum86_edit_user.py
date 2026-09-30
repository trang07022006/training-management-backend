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


class Scrum86EditUserTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-86: Edit User (PUT/PATCH /api/users/<user_id>).
    1. Update valid fields -> 200 OK với thông tin cập nhật
    2. User not found -> 404 USER_NOT_FOUND
    3. Duplicate email -> 409 DUPLICATE_EMAIL
    4. Invalid field values (empty name, invalid status, invalid email, invalid phone) -> 400
    5. Unknown extra sensitive fields (password, role, permissions, id) -> rejected với 400 FORBIDDEN_FIELD
    6. Unauthenticated -> 401 UNAUTHORIZED
    7. Forbidden (thiếu quyền user.manage) -> 403 FORBIDDEN
    8. Updated response không chứa secrets / password_hash
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum86-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_id = "admin-86"
        self.session_id = "session-86"
        self.target_user_id = "target-user-86"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_id,
            refresh_jti="ref-jti-86",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.existing_user = User(
            id=self.target_user_id,
            email="original@daotao.edu.vn",
            password_hash="secret_stored_hash",
            name="Tên Cũ",
            phone="0911223344",
            role="trainee",
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )

    def _create_token(self):
        with self.app.app_context():
            return create_access_token(
                identity=self.admin_id,
                additional_claims={"sid": self.session_id},
            )

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    @patch("app.services.user_service.user_repository.update_user")
    def test_01_update_valid_fields_returns_200(
        self,
        mock_update_user,
        mock_check_email,
        mock_get_user,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_user.return_value = User(
            id=self.target_user_id,
            email="original@daotao.edu.vn",
            password_hash="secret_stored_hash",
            name="Tên Cũ",
            phone="0911223344",
            role="trainee",
            status="active",
        )
        mock_check_email.return_value = False
        mock_update_user.return_value = True

        token = self._create_token()
        payload = {
            "name": "Tên Đã Cập Nhật",
            "phone": "0988998899",
            "email": "updated@daotao.edu.vn",
            "status": "locked",
        }
        res = self.client.put(f"/api/users/{self.target_user_id}", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["name"], "Tên Đã Cập Nhật")
        self.assertEqual(data["data"]["phone"], "0988998899")
        self.assertEqual(data["data"]["email"], "updated@daotao.edu.vn")
        self.assertEqual(data["data"]["status"], "locked")
        self.assertNotIn("password_hash", data["data"])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_02_user_not_found_returns_404(
        self,
        mock_get_user,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_user.return_value = None

        token = self._create_token()
        payload = {"name": "Tên Mới"}
        res = self.client.put("/api/users/non-existent-user", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    @patch("app.services.user_service.user_repository.check_email_exists")
    def test_03_duplicate_email_on_update_returns_409(
        self,
        mock_check_email,
        mock_get_user,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_user.return_value = User(
            id=self.target_user_id,
            email="myemail@daotao.edu.vn",
            name="User",
        )
        mock_check_email.return_value = True

        token = self._create_token()
        payload = {"email": "other_user_email@daotao.edu.vn"}
        res = self.client.put(f"/api/users/{self.target_user_id}", json=payload, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_EMAIL")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_04_invalid_field_values_rejected_with_400(
        self,
        mock_get_user,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_user.return_value = User(
            id=self.target_user_id,
            email="valid@daotao.edu.vn",
            name="Valid",
        )

        token = self._create_token()

        # Empty name
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"name": "   "}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NAME_REQUIRED")

        # Invalid status
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"status": "unknown_status"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_STATUS")

        # Invalid email
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"email": "bad_email"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_EMAIL")

        # Invalid phone
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"phone": "not_a_phone_number"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PHONE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_sensitive_fields_rejected_with_400(
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

        # Attempt to modify password via edit user
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"password": "HackedPassword123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_FIELD")

        # Attempt to modify role via edit user (belongs to SCRUM-26)
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"role": "admin"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_FIELD")

        # Attempt to modify permissions directly
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"permissions": ["user.manage"]}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_FIELD")

    def test_06_unauthenticated_request_fails_with_401(self):
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"name": "New Name"})
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
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"name": "New Name"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    @patch("app.services.user_service.user_repository.update_user")
    def test_08_updated_response_never_exposes_secrets(
        self,
        mock_update_user,
        mock_get_user,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-um", code="user.manage", name="Quản trị user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_user.return_value = User(
            id=self.target_user_id,
            email="valid@daotao.edu.vn",
            password_hash="sensitive_hash_value_123",
            name="Valid",
        )
        mock_update_user.return_value = True

        token = self._create_token()
        res = self.client.put(f"/api/users/{self.target_user_id}", json={"name": "Tên Cập Nhật"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)

        raw = res.get_data(as_text=True)
        self.assertNotIn("password_hash", raw)
        self.assertNotIn("sensitive_hash_value_123", raw)


if __name__ == "__main__":
    unittest.main()
