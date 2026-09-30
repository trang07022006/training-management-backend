import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.role import Role
from app.models.user import User
from app.routes.user_role_routes import user_role_bp


class Scrum100ProtectUserRoleApiTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-100: Bảo vệ API quản trị vai trò người dùng bằng RBAC.
    Kiểm tra 4 endpoints:
    - GET /api/roles
    - GET /api/users/<id>/roles
    - POST /api/users/<id>/roles
    - DELETE /api/users/<id>/roles/<role_id>
    Ma trận:
    1. Unauthenticated -> 401 cho cả 4 endpoints
    2. Missing required permission -> 403 cho cả 4 endpoints
    3. Trainee/User privilege escalation (tự gán role admin) -> 403 FORBIDDEN
    4. Trainer (có user.view nhưng không có user.manage):
       - Xem được danh sách role (GET /api/roles) -> 200
       - Xem được roles của user (GET /api/users/<id>/roles) -> 200
       - Thử gán role (POST) -> 403
       - Thử gỡ role (DELETE) -> 403
    5. Admin (có user.manage và user.view): thành công cho cả 4 endpoints
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum100-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_role_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # 3 users: Admin, Trainer, Trainee
        self.admin_session = LoginSession(
            session_id="session-admin-100",
            user_id="user-admin-100",
            refresh_jti="ref-admin",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.trainer_session = LoginSession(
            session_id="session-trainer-100",
            user_id="user-trainer-100",
            refresh_jti="ref-trainer",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.trainee_session = LoginSession(
            session_id="session-trainee-100",
            user_id="user-trainee-100",
            refresh_jti="ref-trainee",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity="user-admin-100", additional_claims={"sid": "session-admin-100"}
            )
            self.trainer_token = create_access_token(
                identity="user-trainer-100", additional_claims={"sid": "session-trainer-100"}
            )
            self.trainee_token = create_access_token(
                identity="user-trainee-100", additional_claims={"sid": "session-trainee-100"}
            )

        self.target_user = User(
            id="target-100",
            email="target@tms.local",
            name="Target User",
            role="user",
        )
        self.target_role = Role(
            id="role-admin-id",
            code="admin",
            name="Quản trị viên",
        )

    # 1. Unauthenticated -> 401 cho cả 4 endpoints
    def test_01_unauthenticated_all_endpoints(self):
        resp1 = self.client.get("/api/roles")
        self.assertEqual(resp1.status_code, 401)

        resp2 = self.client.get("/api/users/target-100/roles")
        self.assertEqual(resp2.status_code, 401)

        resp3 = self.client.post("/api/users/target-100/roles", json={"role_id": "role-admin-id"})
        self.assertEqual(resp3.status_code, 401)

        resp4 = self.client.delete("/api/users/target-100/roles/role-admin-id")
        self.assertEqual(resp4.status_code, 401)

    # 2. Trainee không có quyền gì đối với user -> 403 cho cả 4 endpoints
    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_trainee_forbidden_all_endpoints(self, mock_session, mock_perm):
        mock_session.return_value = self.trainee_session
        headers = {"Authorization": f"Bearer {self.trainee_token}"}

        resp1 = self.client.get("/api/roles", headers=headers)
        self.assertEqual(resp1.status_code, 403)

        resp2 = self.client.get("/api/users/target-100/roles", headers=headers)
        self.assertEqual(resp2.status_code, 403)

        resp3 = self.client.post("/api/users/target-100/roles", headers=headers, json={"role_id": "role-admin-id"})
        self.assertEqual(resp3.status_code, 403)

        resp4 = self.client.delete("/api/users/target-100/roles/role-admin-id", headers=headers)
        self.assertEqual(resp4.status_code, 403)

    # 3. Privilege escalation prevention: Trainee cố tình gọi API gán quyền admin cho chính mình -> 403
    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_privilege_escalation_prevented(self, mock_session, mock_perm):
        mock_session.return_value = self.trainee_session
        headers = {"Authorization": f"Bearer {self.trainee_token}"}

        resp = self.client.post(
            "/api/users/user-trainee-100/roles",
            headers=headers,
            json={"role_code": "admin"},
        )
        self.assertEqual(resp.status_code, 403)
        json_data = resp.get_json()
        self.assertEqual(json_data["code"], "FORBIDDEN")

    # 4. Trainer có 'user.view' nhưng không có 'user.manage'
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.role_repository.get_all_roles")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.user_role_repository.get_roles_by_user_id")
    def test_04_trainer_can_view_but_cannot_modify(
        self, mock_user_roles, mock_user, mock_roles, mock_session
    ):
        mock_session.return_value = self.trainer_session
        mock_user.return_value = self.target_user
        mock_roles.return_value = [self.target_role]
        mock_user_roles.return_value = [self.target_role]

        headers = {"Authorization": f"Bearer {self.trainer_token}"}

        # Trainer có user.view = True, user.manage = False
        def fake_has_perm(uid, pcode):
            return pcode == "user.view"

        with patch("app.utils.rbac_auth.has_permission", side_effect=fake_has_perm):
            # Xem danh sách role -> OK
            resp1 = self.client.get("/api/roles", headers=headers)
            self.assertEqual(resp1.status_code, 200)

            # Xem role của user -> OK
            resp2 = self.client.get("/api/users/target-100/roles", headers=headers)
            self.assertEqual(resp2.status_code, 200)

            # Thử gán role -> 403
            resp3 = self.client.post("/api/users/target-100/roles", headers=headers, json={"role_id": "role-admin-id"})
            self.assertEqual(resp3.status_code, 403)

            # Thử gỡ role -> 403
            resp4 = self.client.delete("/api/users/target-100/roles/role-admin-id", headers=headers)
            self.assertEqual(resp4.status_code, 403)

    # 5. Admin có đầy đủ quyền user.view và user.manage -> thành công
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_role_service.role_repository.get_all_roles")
    @patch("app.services.user_role_service.user_repository.get_user_by_id")
    @patch("app.services.user_role_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.user_role_service.role_repository.get_role_by_id")
    @patch("app.services.user_role_service.user_role_repository.check_user_role_exists")
    @patch("app.services.user_role_service.user_role_repository.assign_role_to_user")
    @patch("app.services.user_role_service.user_role_repository.remove_role_from_user")
    @patch("app.services.user_role_service.user_role_repository.get_primary_role_code_by_user_id")
    def test_05_admin_authorized_for_all(
        self, mock_primary, mock_remove, mock_assign, mock_exists, mock_get_role, mock_user_roles, mock_user, mock_roles, mock_session, mock_perm
    ):
        mock_session.return_value = self.admin_session
        mock_user.return_value = self.target_user
        mock_roles.return_value = [self.target_role]
        mock_user_roles.return_value = [self.target_role]
        mock_get_role.return_value = self.target_role
        mock_remove.return_value = True
        mock_primary.return_value = "admin"

        headers = {"Authorization": f"Bearer {self.admin_token}"}

        # 1. GET /api/roles -> 200
        resp1 = self.client.get("/api/roles", headers=headers)
        self.assertEqual(resp1.status_code, 200)

        # 2. GET /api/users/<id>/roles -> 200
        resp2 = self.client.get("/api/users/target-100/roles", headers=headers)
        self.assertEqual(resp2.status_code, 200)

        # 3. POST /api/users/<id>/roles -> 201 (mapping chưa có)
        mock_exists.return_value = False
        resp3 = self.client.post("/api/users/target-100/roles", headers=headers, json={"role_id": "role-admin-id"})
        self.assertEqual(resp3.status_code, 201)

        # 4. DELETE /api/users/<id>/roles/<role_id> -> 200 (mapping có)
        mock_exists.return_value = True
        resp4 = self.client.delete("/api/users/target-100/roles/role-admin-id", headers=headers)
        self.assertEqual(resp4.status_code, 200)


if __name__ == "__main__":
    unittest.main()
