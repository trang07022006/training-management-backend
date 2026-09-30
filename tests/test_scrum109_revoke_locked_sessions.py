import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.routes.user_routes import user_bp
from app.services.session_service import renew_stored_session, SessionValidationError
from app.services.user_service import lock_user_account, unlock_user_account
from app.utils.session_auth import session_required


class Scrum109RevokeLockedSessionsTests(unittest.TestCase):
    """
    Kiểm thử SCRUM-109: Xử lý thu hồi phiên khi tài khoản bị khóa.
    1. Active session trước khi lock -> Đang hoạt động bình thường
    2. Account bị lock -> Tất cả phiên làm việc của user bị thu hồi (revoked_at được thiết lập)
    3. Request tiếp theo sử dụng token cũ bị từ chối ngay lập tức (401 SESSION_REVOKED)
    4. Yêu cầu làm mới token (Refresh token) bị từ chối vì phiên đã bị thu hồi
    5. Mở khóa tài khoản (Unlock) KHÔNG tự động phục hồi phiên cũ (old tokens remain revoked)
    6. Người dùng sau khi mở khóa phải đăng nhập lại để tạo phiên làm việc mới
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum109-sessions-32-chars",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(user_bp)

        # Route test được bảo vệ bởi session_required
        @self.app.get("/api/test-protected")
        @session_required
        def protected_endpoint():
            return jsonify({"status": "success", "message": "Access granted"}), 200

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "user-victim-109"
        self.session_id = "session-victim-109"
        self.refresh_jti = "refresh-jti-victim-109"

        self.active_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti=self.refresh_jti,
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=None,
        )

        self.revoked_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti=self.refresh_jti,
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=self.now,
        )

        with self.app.app_context():
            self.access_token = create_access_token(
                identity=self.user_id,
                additional_claims={"sid": self.session_id},
            )
            self.refresh_token = create_refresh_token(
                identity=self.user_id,
                additional_claims={"sid": self.session_id},
            )

    @patch("app.utils.session_auth.get_session_by_id")
    def test_01_active_session_before_lock_allows_access(self, mock_get_sess):
        """1. Phiên hoạt động trước khi khóa: Cho phép truy cập bình thường (200 OK)."""
        mock_get_sess.return_value = self.active_session

        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = self.client.get("/api/test-protected", headers=headers)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")

    @patch("app.services.user_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.user_service.user_repository.update_user_status")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_02_account_lock_revokes_all_user_sessions(
        self, mock_get_user, mock_update_status, mock_revoke_sessions
    ):
        """2. Khóa tài khoản -> gọi thu hồi toàn bộ phiên của người dùng."""
        user = User(id=self.user_id, email="victim@tms.local", status="active")
        mock_get_user.return_value = user

        result = lock_user_account(self.user_id)

        self.assertEqual(result["status"], "locked")
        mock_update_status.assert_called_once_with(user_id=self.user_id, status="locked")
        mock_revoke_sessions.assert_called_once_with(user_id=self.user_id, current_session_id=None)

    @patch("app.utils.session_auth.get_session_by_id")
    def test_03_request_after_lock_is_denied_session_revoked(self, mock_get_sess):
        """3. Sau khi bị khóa, request tiếp theo với token cũ bị từ chối 401 SESSION_REVOKED."""
        mock_get_sess.return_value = self.revoked_session

        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = self.client.get("/api/test-protected", headers=headers)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "SESSION_REVOKED")

    @patch("app.services.session_service.session_repository.get_session_by_id")
    def test_04_refresh_token_denied_when_session_revoked(self, mock_get_sess):
        """4. Cố gắng refresh token với phiên đã bị thu hồi -> Bị từ chối SessionValidationError."""
        mock_get_sess.return_value = self.revoked_session

        with self.app.app_context():
            with self.assertRaises(SessionValidationError) as ctx:
                renew_stored_session(
                    session_id=self.session_id,
                    user_id=self.user_id,
                    refresh_jti=self.refresh_jti,
                    now=self.now,
                )
            self.assertEqual(ctx.exception.code, "SESSION_REVOKED")

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.services.user_service.user_repository.reset_user_lockout")
    @patch("app.services.user_service.user_repository.update_user_status")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_05_unlock_does_not_restore_old_sessions(
        self, mock_get_user, mock_update_status, mock_reset_lockout, mock_get_sess
    ):
        """5. Mở khóa tài khoản không tự động phục hồi phiên cũ; token cũ vẫn bị từ chối."""
        locked_user = User(id=self.user_id, email="victim@tms.local", status="locked")
        mock_get_user.return_value = locked_user

        # Thực hiện mở khóa
        unlock_res = unlock_user_account(self.user_id)
        self.assertEqual(unlock_res["status"], "active")

        # Session cũ trong DB vẫn giữ nguyên revoked_at
        mock_get_sess.return_value = self.revoked_session

        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = self.client.get("/api/test-protected", headers=headers)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "SESSION_REVOKED")

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_06_user_must_login_again_after_unlock(self, mock_get_user, mock_create_sess):
        """6. Người dùng sau khi được mở khóa phải đăng nhập lại để nhận phiên mới."""
        from werkzeug.security import generate_password_hash
        plain = "MyNewPassword123!"
        unlocked_user = User(
            id=self.user_id,
            email="victim@tms.local",
            password_hash=generate_password_hash(plain),
            status="active",
        )
        mock_get_user.return_value = unlocked_user

        new_sess = LoginSession(
            session_id="new-session-id-109",
            user_id=self.user_id,
            refresh_jti="new-ref-jti",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=None,
        )
        with self.app.app_context():
            from flask_jwt_extended import create_access_token, create_refresh_token
            mock_create_sess.return_value = (new_sess, {
                "access_token": create_access_token(self.user_id),
                "refresh_token": create_refresh_token(self.user_id),
            })

            resp = self.client.post("/api/auth/login", json={
                "email": "victim@tms.local",
                "password": plain,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["session_id"], "new-session-id-109")


if __name__ == "__main__":
    unittest.main()
