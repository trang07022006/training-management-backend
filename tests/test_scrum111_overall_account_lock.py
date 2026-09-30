import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token
from werkzeug.security import generate_password_hash

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.routes.user_routes import user_bp
from app.services.session_service import renew_stored_session, SessionValidationError
from app.services.user_service import (
    AccountAlreadyActiveError,
    AccountAlreadyLockedError,
    UserNotFoundError,
    lock_user_account,
    unlock_user_account,
)
from app.utils.session_auth import session_required


class Scrum111OverallAccountLockTests(unittest.TestCase):
    """
    SCRUM-111: Kiểm thử tổng thể chức năng Khóa / Mở khóa tài khoản (SCRUM-27 Backend Test Matrix).
    
    A. Lock
    1. valid lock -> 200 OK, status='locked'
    2. already locked -> 409 ALREADY_LOCKED
    3. user not found -> 404 USER_NOT_FOUND
    4. unauthorized -> 401 UNAUTHORIZED
    5. forbidden -> 403 FORBIDDEN
    
    B. Unlock
    6. valid unlock -> 200 OK, status='active'
    7. already active -> 409 ALREADY_ACTIVE
    8. user not found -> 404 USER_NOT_FOUND
    9. unauthorized -> 401 UNAUTHORIZED
    10. forbidden -> 403 FORBIDDEN
    
    C. Login
    11. locked user denied -> 403 ACCOUNT_LOCKED
    12. active user allowed -> 200 OK
    13. no token for locked user
    
    D. Sessions
    14. active session revoked after lock
    15. refresh blocked when session revoked
    16. protected request blocked
    17. unlock does not magically restore old session
    
    E. Security
    18. account state cannot be forged from frontend (server-side authority)
    19. RBAC enforced on lock/unlock endpoints
    20. SQL injection treated safely as data
    21. no sensitive data leakage
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum111-overall-suite-32-chars",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(user_bp)

        @self.app.get("/api/test-scrum111-guarded")
        @session_required
        def guarded():
            return jsonify({"status": "success", "message": "Access permitted"}), 200

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_user_id = "admin-111"
        self.session_id = "session-111"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.admin_user_id,
            refresh_jti="ref-111",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.trainee_session = LoginSession(
            session_id="trainee-session-111",
            user_id="trainee-111",
            refresh_jti="ref-trainee",
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
                identity="trainee-111",
                additional_claims={"sid": "trainee-session-111"},
            )

        self.plain_password = "ValidPassword123!"
        self.password_hash = generate_password_hash(self.plain_password)

    # =========================================================================
    # A. LOCK MATRIX
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_01_lock_valid(self, mock_lock, mock_sess, mock_perm):
        """1. Khóa tài khoản hợp lệ thành công -> 200 OK."""
        mock_sess.return_value = self.session
        mock_lock.return_value = {"user_id": "u-10", "status": "locked"}

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/u-10/lock", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["data"]["status"], "locked")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_02_lock_already_locked(self, mock_lock, mock_sess, mock_perm):
        """2. Khóa tài khoản đã bị khóa -> 409 ALREADY_LOCKED."""
        mock_sess.return_value = self.session
        mock_lock.side_effect = AccountAlreadyLockedError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/u-10/lock", headers=headers)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "ALREADY_LOCKED")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.lock_user_account")
    def test_03_lock_user_not_found(self, mock_lock, mock_sess, mock_perm):
        """3. Khóa user không tồn tại -> 404 USER_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_lock.side_effect = UserNotFoundError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/nonexistent/lock", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "USER_NOT_FOUND")

    def test_04_lock_unauthorized(self):
        """4. Khóa tài khoản khi chưa xác thực -> 401 UNAUTHORIZED."""
        resp = self.client.post("/api/users/u-10/lock")
        self.assertEqual(resp.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_lock_forbidden(self, mock_sess, mock_perm):
        """5. Khóa tài khoản khi thiếu quyền user.manage -> 403 FORBIDDEN."""
        mock_sess.return_value = self.trainee_session
        headers = {"Authorization": f"Bearer {self.trainee_token}"}
        resp = self.client.post("/api/users/u-10/lock", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    # =========================================================================
    # B. UNLOCK MATRIX
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_06_unlock_valid(self, mock_unlock, mock_sess, mock_perm):
        """6. Mở khóa tài khoản hợp lệ thành công -> 200 OK."""
        mock_sess.return_value = self.session
        mock_unlock.return_value = {"user_id": "u-10", "status": "active"}

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/u-10/unlock", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["data"]["status"], "active")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_07_unlock_already_active(self, mock_unlock, mock_sess, mock_perm):
        """7. Mở khóa tài khoản đang active -> 409 ALREADY_ACTIVE."""
        mock_sess.return_value = self.session
        mock_unlock.side_effect = AccountAlreadyActiveError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/u-10/unlock", headers=headers)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "ALREADY_ACTIVE")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.unlock_user_account")
    def test_08_unlock_user_not_found(self, mock_unlock, mock_sess, mock_perm):
        """8. Mở khóa user không tồn tại -> 404 USER_NOT_FOUND."""
        mock_sess.return_value = self.session
        mock_unlock.side_effect = UserNotFoundError()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/nonexistent/unlock", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "USER_NOT_FOUND")

    def test_09_unlock_unauthorized(self):
        """9. Mở khóa tài khoản khi chưa xác thực -> 401 UNAUTHORIZED."""
        resp = self.client.post("/api/users/u-10/unlock")
        self.assertEqual(resp.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_10_unlock_forbidden(self, mock_sess, mock_perm):
        """10. Mở khóa tài khoản khi thiếu quyền user.manage -> 403 FORBIDDEN."""
        mock_sess.return_value = self.trainee_session
        headers = {"Authorization": f"Bearer {self.trainee_token}"}
        resp = self.client.post("/api/users/u-10/unlock", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    # =========================================================================
    # C. LOGIN MATRIX
    # =========================================================================

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_11_login_locked_user_denied(self, mock_get_user, mock_create_sess):
        """11. Tài khoản bị khóa đăng nhập với đúng mật khẩu -> 403 ACCOUNT_LOCKED."""
        locked_user = User(
            id="u-locked",
            email="victim@tms.local",
            password_hash=self.password_hash,
            status="locked",
        )
        mock_get_user.return_value = locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "victim@tms.local",
            "password": self.plain_password,
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "ACCOUNT_LOCKED")
        mock_create_sess.assert_not_called()

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_12_login_active_user_allowed(self, mock_get_user, mock_create_sess):
        """12. Tài khoản hoạt động bình thường đăng nhập -> 200 OK."""
        active_user = User(
            id="u-active",
            email="active@tms.local",
            password_hash=self.password_hash,
            status="active",
        )
        mock_get_user.return_value = active_user
        mock_sess = LoginSession(
            session_id="new-sess",
            user_id="u-active",
            refresh_jti="ref",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        with self.app.app_context():
            mock_create_sess.return_value = (mock_sess, {
                "access_token": create_access_token("u-active"),
                "refresh_token": create_refresh_token("u-active"),
            })

            resp = self.client.post("/api/auth/login", json={
                "email": "active@tms.local",
                "password": self.plain_password,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.get_json())

    @patch("app.services.auth_service.create_stored_login_session")
    @patch("app.services.auth_service.user_repository.get_user_by_email")
    def test_13_no_token_issued_when_locked(self, mock_get_user, mock_create_sess):
        """13. Tuyệt đối không phát hành access token hay refresh token cho tài khoản locked."""
        locked_user = User(
            id="u-locked",
            email="victim@tms.local",
            password_hash=self.password_hash,
            status="locked",
        )
        mock_get_user.return_value = locked_user

        resp = self.client.post("/api/auth/login", json={
            "email": "victim@tms.local",
            "password": self.plain_password,
        })
        data = resp.get_json()
        self.assertNotIn("access_token", data)
        self.assertNotIn("refresh_token", data)
        mock_create_sess.assert_not_called()

    # =========================================================================
    # D. SESSIONS MATRIX
    # =========================================================================

    @patch("app.services.user_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.user_service.user_repository.update_user_status")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_14_active_session_revoked_after_lock(
        self, mock_get_user, mock_update_status, mock_revoke_sessions
    ):
        """14. Khi khóa tài khoản, toàn bộ phiên của người dùng được thu hồi ngay lập tức."""
        user = User(id="u-target", email="target@tms.local", status="active")
        mock_get_user.return_value = user

        res = lock_user_account("u-target")
        self.assertEqual(res["status"], "locked")
        mock_revoke_sessions.assert_called_once_with(user_id="u-target", current_session_id=None)

    @patch("app.services.session_service.session_repository.get_session_by_id")
    def test_15_refresh_blocked_when_session_revoked(self, mock_get_sess):
        """15. Phiên đã bị thu hồi do khóa tài khoản không thể làm mới token."""
        revoked_sess = LoginSession(
            session_id="sess-revoked",
            user_id="u-victim",
            refresh_jti="ref-revoked",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=self.now,
        )
        mock_get_sess.return_value = revoked_sess

        with self.app.app_context():
            with self.assertRaises(SessionValidationError) as ctx:
                renew_stored_session(
                    session_id="sess-revoked",
                    user_id="u-victim",
                    refresh_jti="ref-revoked",
                    now=self.now,
                )
            self.assertEqual(ctx.exception.code, "SESSION_REVOKED")

    @patch("app.utils.session_auth.get_session_by_id")
    def test_16_protected_request_blocked(self, mock_get_sess):
        """16. Request gửi access token của phiên đã thu hồi bị từ chối 401 SESSION_REVOKED."""
        revoked_sess = LoginSession(
            session_id="sess-revoked",
            user_id="u-victim",
            refresh_jti="ref-revoked",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=self.now,
        )
        mock_get_sess.return_value = revoked_sess

        with self.app.app_context():
            token = create_access_token(identity="u-victim", additional_claims={"sid": "sess-revoked"})
            headers = {"Authorization": f"Bearer {token}"}
            resp = self.client.get("/api/test-scrum111-guarded", headers=headers)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "SESSION_REVOKED")

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.services.user_service.user_repository.reset_user_lockout")
    @patch("app.services.user_service.user_repository.update_user_status")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_17_unlock_does_not_magically_restore_old_session(
        self, mock_get_user, mock_update_status, mock_reset_lockout, mock_get_sess
    ):
        """17. Mở khóa tài khoản KHÔNG phục hồi phiên cũ, token cũ vẫn bị từ chối."""
        user = User(id="u-victim", email="victim@tms.local", status="locked")
        mock_get_user.return_value = user

        unlock_res = unlock_user_account("u-victim")
        self.assertEqual(unlock_res["status"], "active")

        # Phiên cũ trong DB vẫn có revoked_at
        revoked_sess = LoginSession(
            session_id="sess-revoked",
            user_id="u-victim",
            refresh_jti="ref-revoked",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=self.now,
        )
        mock_get_sess.return_value = revoked_sess

        with self.app.app_context():
            token = create_access_token(identity="u-victim", additional_claims={"sid": "sess-revoked"})
            headers = {"Authorization": f"Bearer {token}"}
            resp = self.client.get("/api/test-scrum111-guarded", headers=headers)

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "SESSION_REVOKED")

    # =========================================================================
    # E. SECURITY MATRIX
    # =========================================================================

    @patch("app.services.user_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.user_service.user_repository.update_user_status")
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_18_account_state_cannot_be_forged_from_client(
        self, mock_get_user, mock_sess, mock_perm, mock_update, mock_revoke
    ):
        """18. Client gửi status trong body của endpoint lock/unlock không thể ghi đè logic máy chủ."""
        mock_sess.return_value = self.session
        active_user = User(id="u-10", email="target@tms.local", status="active")
        mock_get_user.return_value = active_user

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        # Client cố tình gửi status='active' vào endpoint lock
        resp = self.client.post("/api/users/u-10/lock", json={"status": "active"}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        # Server luôn chuyển sang 'locked' theo nghiệp vụ endpoint
        self.assertEqual(resp.get_json()["data"]["status"], "locked")

    @patch("app.utils.rbac_auth.has_permission", return_value=False)
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_19_rbac_enforced_privilege_escalation_blocked(self, mock_sess, mock_perm):
        """19. Người dùng không có quyền quản trị không thể tự gọi API mở khóa cho chính mình."""
        mock_sess.return_value = self.trainee_session
        headers = {"Authorization": f"Bearer {self.trainee_token}"}

        resp = self.client.post("/api/users/trainee-111/unlock", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_20_sql_injection_treated_as_data(self, mock_get_user, mock_sess, mock_perm):
        """20. Payload SQL Injection trong URL parameter được xử lý an toàn dạng chuỗi dữ liệu."""
        mock_sess.return_value = self.session
        mock_get_user.return_value = None

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        sqli_id = "1' OR '1'='1"
        resp = self.client.post(f"/api/users/{sqli_id}/lock", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "USER_NOT_FOUND")

    @patch("app.services.user_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.user_service.user_repository.update_user_status")
    @patch("app.utils.rbac_auth.has_permission", return_value=True)
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.user_service.user_repository.get_user_by_id")
    def test_21_no_sensitive_data_leakage(
        self, mock_get_user, mock_sess, mock_perm, mock_update, mock_revoke
    ):
        """21. Response tuyệt đối không để lộ password hash, salt hay thông tin nội bộ."""
        mock_sess.return_value = self.session
        secret_hash = "$2b$12$topsecretsalthash1234567890"
        user = User(id="u-secret", email="secret@tms.local", password_hash=secret_hash, status="active")
        mock_get_user.return_value = user

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        resp = self.client.post("/api/users/u-secret/lock", headers=headers)
        text = resp.get_data(as_text=True)

        self.assertNotIn("password_hash", text)
        self.assertNotIn(secret_hash, text)
        self.assertNotIn("salt", text)


if __name__ == "__main__":
    unittest.main()
