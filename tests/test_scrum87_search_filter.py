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


class Scrum87SearchFilterTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-87: Search / Filter / Pagination (GET /api/users).
    1. Search name
    2. Search email
    3. Search phone
    4. No result
    5. Partial search
    6. Special characters
    7. SQL injection payload treated as data
    8. Filter status
    9. Filter role
    10. Pagination + search
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum87-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "user-87"
        self.session_id = "session-87"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-87",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.sample_users = [
            User(id="1", name="Nguyễn Văn A", email="nguyenvana@daotao.edu.vn", phone="0911000001", role="admin", status="active"),
            User(id="2", name="Trần Thị B", email="tranthib@daotao.edu.vn", phone="0911000002", role="trainer", status="active"),
            User(id="3", name="Lê Văn C", email="levanc@daotao.edu.vn", phone="0911000003", role="trainee", status="locked"),
        ]

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
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_01_search_by_name(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([self.sample_users[0]], 1)

        token = self._create_token()
        res = self.client.get("/api/users?search=Nguyễn", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["data"]["total"], 1)
        self.assertEqual(data["data"]["items"][0]["name"], "Nguyễn Văn A")
        mock_list.assert_called_with(page=1, page_size=20, search="Nguyễn")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_02_search_by_email(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([self.sample_users[1]], 1)

        token = self._create_token()
        res = self.client.get("/api/users?search=tranthib@", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["data"]["items"][0]["email"], "tranthib@daotao.edu.vn")
        mock_list.assert_called_with(page=1, page_size=20, search="tranthib@")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_03_search_by_phone(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([self.sample_users[2]], 1)

        token = self._create_token()
        res = self.client.get("/api/users?search=0911000003", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["data"]["items"][0]["phone"], "0911000003")
        mock_list.assert_called_with(page=1, page_size=20, search="0911000003")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_04_search_no_results(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        res = self.client.get("/api/users?search=khongtontai", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["data"]["items"], [])
        self.assertEqual(data["data"]["total"], 0)
        self.assertEqual(data["data"]["total_pages"], 0)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_05_partial_search(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = (self.sample_users, 3)

        token = self._create_token()
        res = self.client.get("/api/users?search=daotao", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search="daotao")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_06_special_characters_handled_safely(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        special_query = "%_#$*@!~`^&()-=+[]{};:,.<>?"
        res = self.client.get("/api/users", query_string={"search": special_query}, headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search=special_query)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_07_sql_injection_payload_treated_as_data(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([], 0)

        token = self._create_token()
        sqli_payload = "' OR '1'='1' -- "
        res = self.client.get(f"/api/users?search={sqli_payload}", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, search=sqli_payload.strip())

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_08_filter_by_status(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([self.sample_users[2]], 1)

        token = self._create_token()
        res = self.client.get("/api/users?status=locked", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, status="locked")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_09_filter_by_role(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([self.sample_users[1]], 1)

        token = self._create_token()
        res = self.client.get("/api/users?role=trainer", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        mock_list.assert_called_with(page=1, page_size=20, role="trainer")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.routes.user_routes.user_repository.list_users")
    def test_10_pagination_and_search_combined(self, mock_list, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]
        mock_list.return_value = ([self.sample_users[1]], 25)

        token = self._create_token()
        res = self.client.get("/api/users?search=daotao&page=2&page_size=10&role=trainer&status=active", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["data"]["page"], 2)
        self.assertEqual(data["data"]["page_size"], 10)
        self.assertEqual(data["data"]["total"], 25)
        self.assertEqual(data["data"]["total_pages"], 3)
        mock_list.assert_called_with(page=2, page_size=10, search="daotao", role="trainer", status="active")


if __name__ == "__main__":
    unittest.main()
