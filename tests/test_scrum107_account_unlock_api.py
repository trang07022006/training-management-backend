import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.routes.user_routes import user_bp
from app.services.user_service import AccountAlreadyActiveError, UserNotFoundError


class Scrum107AccountUnlockApiTests(unittest.TestCase):
    """
    Kiểm thử SCRUM-107: API Mở khóa tài khoản người dùng (POST /api/users/<user_id>/unlock).
    1. Unlock thành công -> 200, status='active'
    2. User không tồn tại -> 404 USER_NOT_FOUND
    3. User đã ở trạng thái active -> 409 ALREADY_ACTIVE
    4. Chưa xác thực (thiếu token) -> 401 UNAUTHORIZED
    5. Không đủ quyền (thiếu user.manage) -> 403 FORBIDDEN
    6. Lỗi hệ thống -> 500 INTERNAL_ERROR
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum107-api-at-least-32-chars",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-107"
        self.session_id = "session-107"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-107",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_user_id,
                additional_claims={"sid": self.session_id},
            )
            self.trainee_token = create_access_token(
                identity="trainee-107",
                additional_claims={"sid": "trainee-session-107"},
            )

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_01_unlock_user_success(self, mock_unlock, mock_sess, mock_perm):
        """1. Mở khóa tài khoản thành công -> 200 và dữ liệu trạng thái active."""
        mock_sess.return_value = self.session
        mock_unlock.return_value = {"user_id": "target-locked-1", "status": "active"}

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/target-locked-1/unlock", headers=headers)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["user_id"], "target-locked-1")
        self.assertEqual(data["data"]["status"], "active")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_02_unlock_user_not_found(self, mock_unlock, mock_sess, mock_perm):
        """2. Mở khóa user không tồn tại -> 404 USER_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_unlock.side_effect = UserNotFoundError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/nonexistent/unlock", headers=headers)

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_03_unlock_already_active(self, mock_unlock, mock_sess, mock_perm):
        """3. Mở khóa tài khoản vốn đang active -> 409 ALREADY_ACTIVE."""
        mock_sess.return_value = self.session
        mock_unlock.side_effect = AccountAlreadyActiveError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/target-active/unlock", headers=headers)

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "ALREADY_ACTIVE")

    def test_04_unlock_unauthenticated(self):
        """4. Chưa xác thực -> 401 UNAUTHORIZED."""
        resp = self.client.post("/api/users/target-1/unlock")
        self.assertEqual(resp.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_unlock_forbidden_insufficient_permissions(self, mock_sess, mock_perm):
        """5. Không có quyền user.manage -> 403 FORBIDDEN."""
        trainee_sess = LoginSession(
            session_id="trainee-session-107",
            user_id="trainee-107",
            refresh_jti="ref-trainee",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        mock_sess.return_value = trainee_sess

        headers = {"Authorization": f"Bearer {self.trainee_token}"}
        resp = self.client.post("/api/users/target-1/unlock", headers=headers)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_06_unlock_internal_error_handling(self, mock_unlock, mock_sess, mock_perm):
        """6. Lỗi hệ thống khi mở khóa -> 500 INTERNAL_ERROR."""
        mock_sess.return_value = self.session
        mock_unlock.side_effect = Exception("System unlock failure")

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/target-1/unlock", headers=headers)

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["code"], "INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()
