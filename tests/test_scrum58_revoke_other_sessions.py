import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash
from mysql.connector import Error as MySQLError

from app.models.user import User
from app.repositories import session_repository
from app.routes.auth_routes import auth_bp
from app.services import change_password_service
from app.services.session_service import create_login_session


class Scrum58RevokeOtherSessionsTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-58: Thu hồi các phiên đăng nhập khác sau khi đổi mật khẩu.
    1. user có session A/B/C -> đổi mật khẩu từ A -> A vẫn active, B và C bị thu hồi
    2. Phiên của người dùng khác không bị ảnh hưởng
    3. Update password thất bại -> không thu hồi session
    4. Lỗi khi thu hồi được xử lý an toàn
    5. Hồi quy SCRUM-19 (session management) vẫn PASS
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-only-key-not-for-production-123456789",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )

        JWTManager(self.app)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.user_id = "user-scrum58-alice"
        with self.app.app_context():
            self.session_a, self.tokens_a = create_login_session(self.user_id)

        # Mock session auth để access_token của session A được chấp nhận
        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get_session = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get_session.return_value = self.session_a

        self.current_password = "AliceCurrentPassword123!"
        self.new_password = "AliceBrandNewPassword2026!"
        self.user = User(
            id=self.user_id,
            password_hash=generate_password_hash(self.current_password),
            email="alice58@ictu.edu.vn",
            role="student",
            status="active",
        )

    def post_change_password(self, payload):
        return self.client.post(
            "/api/auth/change-password",
            json=payload,
            headers={"Authorization": f"Bearer {self.tokens_a['access_token']}"},
        )

    # 1. user có session A/B/C -> đổi mật khẩu từ A -> A vẫn active, B/C bị revoke
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_01_change_password_revokes_other_sessions_keeps_current_session(
        self, mock_get_user, mock_update_pw, mock_revoke_other
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True
        mock_revoke_other.return_value = 2  # giả lập 2 session khác (B và C) bị thu hồi

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 200)
        # Kiểm tra service đã gọi revoke_other_user_sessions với đúng user_id và session_id của A
        mock_revoke_other.assert_called_once_with(
            user_id=self.user_id,
            current_session_id=self.session_a.session_id,
        )

    # 2. session repository unit test: truy vấn SQL loại trừ current_session_id và chỉ lọc đúng user_id
    @patch("app.repositories.session_repository._database_cursor")
    def test_02_session_repository_revoke_other_user_sessions_sql(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 2
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        current_sid = "session-a-current-id"
        affected = session_repository.revoke_other_user_sessions(
            user_id="user-123",
            current_session_id=current_sid,
        )

        self.assertEqual(affected, 2)
        mock_cursor.execute.assert_called_once()
        sql, values = mock_cursor.execute.call_args[0]
        # SQL phải lọc đúng user_id và loại trừ session_id != %s
        self.assertIn("user_id = %s", sql)
        self.assertIn("session_id != %s", sql)
        self.assertIn("revoked_at IS NULL", sql)
        self.assertEqual(values[1], "user-123")
        self.assertEqual(values[2], current_sid)

    # 3. session của user khác không bị ảnh hưởng
    @patch("app.repositories.session_repository._database_cursor")
    def test_03_other_users_sessions_are_not_affected(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        # Khi gọi cho user-A, parameter chỉ truyền user-A
        session_repository.revoke_other_user_sessions(
            user_id="user-A",
            current_session_id="session-A-1",
        )
        _, values = mock_cursor.execute.call_args[0]
        self.assertEqual(values[1], "user-A")
        self.assertNotIn("user-B", values)

    # 4. Khi mật khẩu sai -> update DB không chạy -> revoke session KHÔNG ĐƯỢC CHẠY
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_04_password_verification_fail_does_not_revoke_sessions(
        self, mock_get_user, mock_update_pw, mock_revoke_other
    ):
        mock_get_user.return_value = self.user

        res = self.post_change_password({
            "current_password": "WrongPassword999!",
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INCORRECT_CURRENT_PASSWORD")
        mock_update_pw.assert_not_called()
        mock_revoke_other.assert_not_called()

    # 5. Khi password update vào DB lỗi -> revoke session KHÔNG ĐƯỢC CHẠY
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_05_update_password_db_error_does_not_revoke_sessions(
        self, mock_get_user, mock_update_pw, mock_revoke_other
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.side_effect = MySQLError("Database connection down")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")
        mock_revoke_other.assert_not_called()

    # 6. Khi revoke session bị lỗi database -> xử lý an toàn, trả 500
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_06_revoke_database_error_handled_cleanly(
        self, mock_get_user, mock_update_pw, mock_revoke_other
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True
        mock_revoke_other.side_effect = MySQLError("Deadlock in session revocation")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")
        self.assertNotIn("Deadlock", res.get_json()["message"])

    # 7. Mô phỏng danh sách session trong DB: user Alice có A, B, C; user Bob có D
    # Alice đổi password từ session A -> A giữ nguyên (active), B & C bị revoke, Bob D không đổi
    def test_07_simulation_session_a_active_bc_revoked_bob_unaffected(self):
        # Database rows giả lập
        sessions_db = [
            {"session_id": "sid-a", "user_id": self.user_id, "revoked_at": None},
            {"session_id": "sid-b", "user_id": self.user_id, "revoked_at": None},
            {"session_id": "sid-c", "user_id": self.user_id, "revoked_at": None},
            {"session_id": "sid-d", "user_id": "bob-user-id", "revoked_at": None},
        ]

        def fake_revoke_other_user_sessions(user_id, current_session_id=None):
            count = 0
            for s in sessions_db:
                if s["user_id"] == user_id and s["session_id"] != current_session_id and s["revoked_at"] is None:
                    s["revoked_at"] = "2026-10-01 01:00:00"
                    count += 1
            return count

        with patch("app.services.change_password_service.session_repository.revoke_other_user_sessions", side_effect=fake_revoke_other_user_sessions):
            with patch("app.services.change_password_service.user_repository.update_user_password", return_value=True):
                with patch("app.services.change_password_service.user_repository.get_user_by_id", return_value=self.user):
                    # Gọi change_password trực tiếp từ service với user_id='alice' và current_session_id='sid-a'
                    change_password_service.change_password(
                        user_id="alice",
                        current_password=self.current_password,
                        new_password=self.new_password,
                        current_session_id="sid-a",
                    )

        # Kiểm tra trạng thái của từng phiên:
        # Session A của Alice vẫn active
        session_a = next(s for s in sessions_db if s["session_id"] == "sid-a")
        self.assertIsNone(session_a["revoked_at"])

        # Session B và C của Alice đã bị thu hồi
        session_b = next(s for s in sessions_db if s["session_id"] == "sid-b")
        self.assertIsNotNone(session_b["revoked_at"])

        session_c = next(s for s in sessions_db if s["session_id"] == "sid-c")
        self.assertIsNotNone(session_c["revoked_at"])

        # Session D của Bob hoàn toàn không bị ảnh hưởng, vẫn active
        session_d = next(s for s in sessions_db if s["session_id"] == "sid-d")
        self.assertIsNone(session_d["revoked_at"])


if __name__ == "__main__":
    unittest.main()

