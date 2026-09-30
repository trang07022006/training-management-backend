import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.user_routes import user_bp
from app.services.user_service import AccountAlreadyLockedError, UserNotFoundError


class Scrum106AccountLockApiTests(unittest.TestCase):
    """
    Kiểm thử SCRUM-106: API Khóa tài khoản người dùng (POST /api/users/<user_id>/lock).
    1. Lock thành công -> 200, status='locked'
    2. User không tồn tại -> 404 USER_NOT_FOUND
    3. User đã bị khóa -> 409 ALREADY_LOCKED
    4. Chưa xác thực (thiếu token) -> 401 UNAUTHORIZED
    5. Không đủ quyền (thiếu user.manage) -> 403 FORBIDDEN
    6. Lỗi cơ sở dữ liệu -> 500 DATABASE_ERROR
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum106-api-at-least-32-chars",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-106"
        self.session_id = "session-106"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-106",
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
                identity="trainee-106",
                additional_claims={"sid": "trainee-session-106"},
            )

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_01_lock_user_success(self, mock_lock, mock_sess, mock_perm):
        """1. Khóa tài khoản thành công -> 200 và dữ liệu trạng thái locked."""
        mock_sess.return_value = self.session
        mock_lock.return_value = {"user_id": "target-1", "status": "locked"}

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/target-1/lock", headers=headers)

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["user_id"], "target-1")
        self.assertEqual(data["data"]["status"], "locked")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_02_lock_user_not_found(self, mock_lock, mock_sess, mock_perm):
        """2. Khóa user không tồn tại -> 404 USER_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_lock.side_effect = UserNotFoundError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/nonexistent/lock", headers=headers)

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_03_lock_already_locked(self, mock_lock, mock_sess, mock_perm):
        """3. Khóa tài khoản đã ở trạng thái khóa -> 409 ALREADY_LOCKED."""
        mock_sess.return_value = self.session
        mock_lock.side_effect = AccountAlreadyLockedError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/target-1/lock", headers=headers)

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "ALREADY_LOCKED")

    def test_04_lock_unauthenticated(self):
        """4. Chưa xác thực -> 401 UNAUTHORIZED."""
        resp = self.client.post("/api/users/target-1/lock")
        self.assertEqual(resp.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_lock_forbidden_insufficient_permissions(self, mock_sess, mock_perm):
        """5. Không có quyền user.manage -> 403 FORBIDDEN."""
        trainee_sess = LoginSession(
            session_id="trainee-session-106",
            user_id="trainee-106",
            refresh_jti="ref-trainee",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        mock_sess.return_value = trainee_sess

        headers = {"Authorization": f"Bearer {self.trainee_token}"}
        resp = self.client.post("/api/users/target-1/lock", headers=headers)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_06_lock_internal_error_handling(self, mock_lock, mock_sess, mock_perm):
        """6. Lỗi hệ thống khi khóa -> 500 INTERNAL_ERROR."""
        mock_sess.return_value = self.session
        mock_lock.side_effect = Exception("System lock failure")

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/target-1/lock", headers=headers)

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["code"], "INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()
