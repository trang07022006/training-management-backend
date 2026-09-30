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


class Scrum88OverallUserManagementTests(unittest.TestCase):
    """
    Bộ kiểm thử tổng thể SCRUM-88: User Management API.
    A. Authorization:
       1. Unauthenticated -> 401
       2. Authenticated no permission -> 403
       3. Authorized -> success
    B. Listing:
       4. Users list
       5. Pagination
       6. Empty result
       7. No sensitive fields
    C. Create:
       8. Valid create
       9. Duplicate email
       10. Validation (missing fields, format)
       11. Password secure
    D. Update:
       12. Valid update
       13. Missing user (404)
       14. Duplicate email on update (409)
       15. Forbidden fields rejected (400)
    E. Search:
       16. Search by name
       17. Search by email
       18. Search by phone
       19. Search with special characters
       20. Pagination with search
    F. Security:
       21. SQL injection payload treated as literal data
       22. Password hash never exposed in API responses
       23. No token/session leakage
       24. RBAC strictly enforced across all endpoints
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum88-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_id = "overall-admin-88"
        self.session_id = "overall-session-88"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_id,
            refresh_jti="ref-jti-88",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.admin_role = Role(id="r-admin", code="admin", name="Admin")
        self.trainee_role = Role(id="r-trainee", code="trainee", name="Trainee")

        self.perm_user_view = Permission(id="p-uv", code="user.view", name="Xem user")
        self.perm_user_manage = Permission(id="p-um", code="user.manage", name="Quản trị user")

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.admin_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    # =========================================================================
    # A. AUTHORIZATION
    # =========================================================================

    def test_01_unauthenticated_request_fails_with_401(self):
        # GET /api/users
        res_get = self.client.get("/api/users")
        self.assertEqual(res_get.status_code, 401)
        self.assertEqual(res_get.get_json()["code"], "UNAUTHORIZED")

        # POST /api/users
        res_post = self.client.post("/api/users", json={})
        self.assertEqual(res_post.status_code, 401)
        self.assertEqual(res_post.get_json()["code"], "UNAUTHORIZED")

        # PUT /api/users/1
        res_put = self.client.put("/api/users/1", json={})
        self.assertEqual(res_put.status_code, 401)
        self.assertEqual(res_put.get_json()["code"], "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_authenticated_no_permission_fails_with_403(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.trainee_role]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_authorized_succeeds(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view", "user.manage"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    # =========================================================================
    # B. LISTING
    # =========================================================================

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_users_list_returns_records(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]

        sample = [
            User(id="u1", email="u1@daotao.edu.vn", name="User 1", role="user", status="active", created_at=self.now),
            User(id="u2", email="u2@daotao.edu.vn", name="User 2", role="trainer", status="active", created_at=self.now),
        ]
        mock_list.return_value = (sample, 2)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_pagination_metadata(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]

        sample = [User(id=f"u{i}", email=f"u{i}@daotao.edu.vn") for i in range(10)]
        mock_list.return_value = (sample, 55)

        token = self._create_token()
        res = self.client.get("/api/users?page=2&page_size=10", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["page_size"], 10)
        self.assertEqual(data["total"], 55)
        self.assertEqual(data["total_pages"], 6)

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_06_empty_result(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        res = self.client.get("/api/users?page=99", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["total_pages"], 0)

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_no_sensitive_fields_in_listing(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]

        user = User(
            id="u-sens",
            email="sens@daotao.edu.vn",
            password_hash="hashed_secret_never_leak_this",
            role="admin",
            status="active",
        )
        mock_list.return_value = ([user], 1)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        raw = res.get_data(as_text=True)
        self.assertNotIn("password_hash", raw)
        self.assertNotIn("hashed_secret_never_leak_this", raw)

    # =========================================================================
    # C. CREATE
    # =========================================================================

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_email")
    @patch("app.services.user_service.user_repository.create_user")
    def test_08_valid_create(
        self, mock_create, mock_get_email, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_email.return_value = None

        def side_effect(u):
            u.id = "u-new-88"
            return u
        mock_create.side_effect = side_effect

        token = self._create_token()
        payload = {
            "name": "Người Dùng Mới",
            "email": "newbie@daotao.edu.vn",
            "password": "Password123",
            "phone": "0987654321",
        }
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["email"], "newbie@daotao.edu.vn")
        self.assertEqual(data["name"], "Người Dùng Mới")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_email")
    def test_09_duplicate_email_on_create(
        self, mock_get_email, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_email.return_value = User(id="exists", email="dup@daotao.edu.vn")

        token = self._create_token()
        payload = {"name": "Dup", "email": "dup@daotao.edu.vn", "password": "Password123"}
        res = self.client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_EMAIL")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_10_validation_on_create(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()

        # Missing name
        res = self.client.post("/api/users", json={"email": "a@daotao.edu.vn", "password": "Password123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NAME_REQUIRED")

        # Missing email
        res = self.client.post("/api/users", json={"name": "A", "password": "Password123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "EMAIL_REQUIRED")

        # Invalid email format
        res = self.client.post("/api/users", json={"name": "A", "email": "invalid_email", "password": "Password123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_EMAIL")

        # Invalid phone
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn", "password": "Password123", "phone": "123"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PHONE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_11_password_policy_secure(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()

        # Short password (< 8 chars)
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn", "password": "Short1"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_TOO_SHORT")

        # Missing digits
        res = self.client.post("/api/users", json={"name": "A", "email": "a@daotao.edu.vn", "password": "NoDigitsInThisPassword"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

    # =========================================================================
    # D. UPDATE
    # =========================================================================

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    @patch("app.services.user_service.user_repository.update_user")
    def test_12_valid_update(
        self, mock_update, mock_get_id, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_id.return_value = User(id="u12", email="u12@daotao.edu.vn", name="Old Name")
        mock_update.return_value = True

        token = self._create_token()
        payload = {"name": "New Name", "status": "locked"}
        res = self.client.put("/api/users/u12", json=payload, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["name"], "New Name")
        self.assertEqual(data["status"], "locked")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_13_missing_user_returns_404(
        self, mock_get_id, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_id.return_value = None

        token = self._create_token()
        res = self.client.put("/api/users/not-found", json={"name": "ABC"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    @patch("app.services.user_service.user_repository.get_user_by_email")
    def test_14_duplicate_email_on_update(
        self, mock_get_email, mock_get_id, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]
        mock_get_id.return_value = User(id="u14", email="current@daotao.edu.vn", name="User 14")
        # Other user has this email
        mock_get_email.return_value = User(id="u-other", email="taken@daotao.edu.vn")

        token = self._create_token()
        res = self.client.put("/api/users/u14", json={"email": "taken@daotao.edu.vn"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_EMAIL")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_15_forbidden_fields_rejected_on_update(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_manage
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        # Attempt to change password via update endpoint
        res = self.client.put("/api/users/u15", json={"password": "NewSecretPassword1"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_FIELD")

        # Attempt to change role via update endpoint (belongs to SCRUM-26)
        res = self.client.put("/api/users/u15", json={"role": "admin"}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN_FIELD")

    # =========================================================================
    # E. SEARCH & FILTERS
    # =========================================================================

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_16_search_by_name(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([User(id="1", name="Trần Văn Nam")], 1)

        token = self._create_token()
        res = self.client.get("/api/users?search=Nam", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search="Nam")

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_17_search_by_email(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([User(id="1", email="admin@daotao.edu.vn")], 1)

        token = self._create_token()
        res = self.client.get("/api/users?search=admin@", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search="admin@")

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_18_search_by_phone(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([User(id="1", phone="0988776655")], 1)

        token = self._create_token()
        res = self.client.get("/api/users?search=0988776655", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search="0988776655")

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_19_special_characters_handled_safely(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        query = "<script>alert('xss')</script>"
        res = self.client.get("/api/users", query_string={"search": query}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search=query)

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_20_pagination_with_search(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([User(id="1")], 15)

        token = self._create_token()
        res = self.client.get("/api/users?search=test&page=2&page_size=5", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["page_size"], 5)
        self.assertEqual(data["total"], 15)
        self.assertEqual(data["total_pages"], 3)
        mock_list.assert_called_with(page=2, page_size=5, search="test")

    # =========================================================================
    # F. SECURITY
    # =========================================================================

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_21_sql_injection_payload_treated_as_data(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        sqli = "1' UNION SELECT * FROM users --"
        res = self.client.get(f"/api/users?search={sqli}", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search=sqli)

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_22_password_hash_never_exposed(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]

        user = User(id="sec", email="sec@daotao.edu.vn", password_hash="bcrypt$super_secret_hash")
        mock_list.return_value = ([user], 1)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        body = res.get_data(as_text=True)
        self.assertNotIn("password_hash", body)
        self.assertNotIn("super_secret_hash", body)

    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_23_no_token_or_session_leakage(self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = self.perm_user_view
        mock_ur_roles.return_value = [self.admin_role]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        body = res.get_data(as_text=True)
        self.assertNotIn(self.session_id, body)
        self.assertNotIn("ref-jti-88", body)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_24_rbac_enforced_across_all_endpoints(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        # User only has course.view, not user.view or user.manage
        mock_perm_repo.return_value = Permission(id="p-cv", code="course.view", name="Xem course")
        mock_ur_roles.return_value = [self.trainee_role]
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        headers = {"Authorization": f"Bearer {token}"}

        # GET /api/users -> 403
        self.assertEqual(self.client.get("/api/users", headers=headers).status_code, 403)

        # POST /api/users -> 403
        self.assertEqual(self.client.post("/api/users", json={}, headers=headers).status_code, 403)

        # PUT /api/users/1 -> 403
        self.assertEqual(self.client.put("/api/users/1", json={}, headers=headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()
