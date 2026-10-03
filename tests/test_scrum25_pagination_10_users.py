"""
Kiểm thử SCRUM-25: Phân trang 10 người dùng mỗi trang.
Mục tiêu:
- page size mặc định = 10
- 10 user -> 1 trang
- 11 user -> 2 trang (Trang 1 = 10 user, Trang 2 = 1 user)
- 21 user -> 3 trang
- Trang 2 trả đúng dữ liệu / offset
- total_pages tính đúng
- API response trả đủ: items, users, total, page, page_size, total_pages
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask_jwt_extended import create_access_token

from app.main import app
from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.repositories.user_repository import list_users


class TestScrum25Pagination10Users(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

        self.now = datetime.now(timezone.utc)
        self.session_id = "sess-scrum25"
        self.user_id = "u-admin"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-25",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

    def tearDown(self):
        self.ctx.pop()

    def _create_token(self):
        with self.app.app_context():
            return create_access_token(
                identity=self.user_id,
                additional_claims={"sid": self.session_id},
            )

    # 1. Repository: default page_size is 10 and offset calculation
    @patch("app.repositories.user_repository.get_db_connection")
    def test_repo_default_page_size_10_and_offset(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.fetchone.return_value = {"total": 11}
        mock_cursor.fetchall.return_value = [
            {"id": f"u-{i}", "email": f"u{i}@tms.local", "name": f"User {i}", "role": "user", "status": "active"}
            for i in range(1, 11)
        ]

        # Trang 1 mặc định (page=1, không truyền page_size)
        users, total = list_users(page=1)
        self.assertEqual(total, 11)
        self.assertEqual(len(users), 10)
        # Limit 10, offset 0
        mock_cursor.execute.assert_called_with(unittest.mock.ANY, (10, 0))

        # Trang 2: offset phải là (2 - 1) * 10 = 10
        list_users(page=2, page_size=10)
        mock_cursor.execute.assert_called_with(unittest.mock.ANY, (10, 10))

    # 2. API default page_size = 10, response structure
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_api_default_page_size_is_10(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_users = [User(id=f"u-{i}", email=f"u{i}@tms.local") for i in range(10)]
        mock_list.return_value = (mock_users, 11)

        token = self._create_token()
        res = self.client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)

        data = res.get_json()["data"]
        self.assertIn("items", data)
        self.assertIn("users", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 10)
        self.assertEqual(data["total"], 11)
        self.assertEqual(data["total_pages"], 2)
        mock_list.assert_called_with(page=1, page_size=10)

    # 3. 10 users -> 1 page
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_10_users_results_in_1_page(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_users = [User(id=f"u-{i}", email=f"u{i}@tms.local") for i in range(10)]
        mock_list.return_value = (mock_users, 10)

        token = self._create_token()
        res = self.client.get("/api/users?page=1&page_size=10", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)

        data = res.get_json()["data"]
        self.assertEqual(data["total"], 10)
        self.assertEqual(data["page_size"], 10)
        self.assertEqual(data["total_pages"], 1)
        self.assertEqual(len(data["items"]), 10)

    # 4. 11 users -> 2 pages (Trang 1 = 10, Trang 2 = 1)
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_11_users_results_in_2_pages(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        token = self._create_token()

        # Trang 1: 10 user
        mock_page1_users = [User(id=f"u-{i}", email=f"u{i}@tms.local") for i in range(1, 11)]
        mock_list.return_value = (mock_page1_users, 11)

        res1 = self.client.get("/api/users?page=1&page_size=10", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()["data"]
        self.assertEqual(data1["page"], 1)
        self.assertEqual(data1["total"], 11)
        self.assertEqual(data1["total_pages"], 2)
        self.assertEqual(len(data1["items"]), 10)

        # Trang 2: 1 user
        mock_page2_users = [User(id="u-11", email="u11@tms.local")]
        mock_list.return_value = (mock_page2_users, 11)

        res2 = self.client.get("/api/users?page=2&page_size=10", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()["data"]
        self.assertEqual(data2["page"], 2)
        self.assertEqual(data2["total"], 11)
        self.assertEqual(data2["total_pages"], 2)
        self.assertEqual(len(data2["items"]), 1)
        self.assertEqual(data2["items"][0]["id"], "u-11")

    # 5. 21 users -> 3 pages
    @patch("app.routes.user_routes.user_repository.list_users")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_21_users_results_in_3_pages(
        self, mock_rp_codes, mock_ur_roles, mock_perm_repo, mock_get_session, mock_list
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-uv", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.view"]

        mock_users = [User(id=f"u-{i}", email=f"u{i}@tms.local") for i in range(1, 11)]
        mock_list.return_value = (mock_users, 21)

        token = self._create_token()
        res = self.client.get("/api/users?page=1&page_size=10", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["total"], 21)
        self.assertEqual(data["total_pages"], 3)


if __name__ == "__main__":
    unittest.main()
