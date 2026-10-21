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


class Scrum83ListUsersApiTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-83: List Users API (GET /api/users).
    1. Authorized -> 200 (kèm metadata phân trang)
    2. Unauthenticated -> 401 UNAUTHORIZED
    3. Authenticated nhưng không có quyền 'user.view' -> 403 FORBIDDEN
    4. Phân trang đúng theo query parameters
    5. Invalid page/page_size -> 400
    6. Dữ liệu nhạy cảm (password_hash) không xuất hiện trong API response
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum83-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "test-user-83"
        self.session_id = "test-session-83"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-83",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.mock_users = [
            User(
                id="u-1",
                email="admin@daotao.edu.vn",
                password_hash="secret_hash_admin",
                role="admin",
                status="active",
                name="Quản trị viên",
                created_at=self.now,
            ),
            User(
                id="u-2",
                email="trainer@daotao.edu.vn",
                password_hash="secret_hash_trainer",
                role="trainer",
                status="active",
                name="Giảng viên A",
                created_at=self.now,
            ),
        ]

    def _create_token(self):
        with self.app.app_context():
            return create_access_token(
                identity=self.user_id,
                additional_claims={"sid": self.session_id},
            )

    # 1. Authorized -> 200
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_01_authorized_user_lists_users_successfully(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list_users
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_list_users.return_value = (self.mock_users, 2)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["total"], 2)
        self.assertEqual(data["data"]["page"], 1)
        self.assertEqual(data["data"]["page_size"], 10)
        self.assertEqual(data["data"]["total_pages"], 1)
        self.assertEqual(len(data["data"]["items"]), 2)
        mock_list_users.assert_called_with(page=1, page_size=10)

    # 2. Unauthenticated -> 401
    def test_02_unauthenticated_request_fails(self):
        res = self.client.get("/api/users")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    # 3. No permission -> 403
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_authenticated_without_permission_denied_with_403(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-trainee", code="trainee", name="Trainee")]
        # Trainee không có user.view
        mock_rp_codes.return_value = ["course.view"]

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    # 4. Pagination query params parsed correctly
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_pagination_params_forwarded_to_repository(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list_users
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_list_users.return_value = ([self.mock_users[0]], 35)

        token = self._create_token()
        res = self.client.get("/api/users?page=2&page_size=10", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        mock_list_users.assert_called_with(page=2, page_size=10)
        data = res.get_json()["data"]
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["page_size"], 10)
        self.assertEqual(data["total"], 35)
        self.assertEqual(data["total_pages"], 4)

    # 5. Invalid page & page_size -> 400
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_invalid_page_returns_400(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        token = self._create_token()

        res_invalid_page = self.client.get("/api/users?page=invalid", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_invalid_page.status_code, 400)
        self.assertEqual(res_invalid_page.get_json()["code"], "INVALID_PAGE")

        res_negative_page = self.client.get("/api/users?page=0", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_negative_page.status_code, 400)
        self.assertEqual(res_negative_page.get_json()["code"], "INVALID_PAGE")

        res_invalid_size = self.client.get("/api/users?page_size=500", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res_invalid_size.status_code, 400)
        self.assertEqual(res_invalid_size.get_json()["code"], "INVALID_PAGE_SIZE")

    # 6. Sensitive data absent
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_06_sensitive_fields_absent_from_response(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list_users
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_list_users.return_value = (self.mock_users, 2)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        json_str = res.get_data(as_text=True)
        self.assertNotIn("secret_hash_admin", json_str)
        self.assertNotIn("secret_hash_trainer", json_str)
        self.assertNotIn("password_hash", json_str)
        self.assertNotIn("password", json_str)

    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_get_single_user_success(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_get_user
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_get_user.return_value = self.mock_users[0]

        token = self._create_token()
        res = self.client.get("/api/users/u-admin-001", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["email"], self.mock_users[0].email)
        self.assertEqual(body["data"]["name"], self.mock_users[0].name)

    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_08_get_single_user_not_found(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_get_user
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_get_user.return_value = None

        token = self._create_token()
        res = self.client.get("/api/users/non-existent-id", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 404)
        body = res.get_json()
        self.assertEqual(body["code"], "USER_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
