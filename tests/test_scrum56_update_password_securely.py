import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager
from mysql.connector import Error as MySQLError
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.user import User
from app.repositories import user_repository
from app.routes.auth_routes import auth_bp
from app.services.change_password_service import change_password
from app.services.session_service import create_login_session


class Scrum56UpdatePasswordSecurelyTests(unittest.TestCase):
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

        self.user_id = "user-scrum56-id"
        with self.app.app_context():
            self.session, self.tokens = create_login_session(self.user_id)

        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get_session = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get_session.return_value = self.session

        revoke_patcher = patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
        self.mock_revoke_other = revoke_patcher.start()
        self.addCleanup(revoke_patcher.stop)

        self.current_password = "OldValidPassword123!"
        self.new_password = "BrandNewPassword2026!"
        self.user = User(
            id=self.user_id,
            password_hash=generate_password_hash(self.current_password),
            email="user56@ictu.edu.vn",
            role="teacher",
            status="active",
        )

    def post_change_password(self, payload):
        return self.client.post(
            "/api/auth/change-password",
            json=payload,
            headers={"Authorization": f"Bearer {self.tokens['access_token']}"},
        )

    # 1. password hợp lệ update thành công
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_01_valid_password_updates_successfully(self, mock_get_user, mock_update_pw):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 200)
        self.assertIn("thành công", res.get_json()["message"])
        mock_update_pw.assert_called_once()

    # 2, 3 & 4. DB lưu hash; hash != plaintext; plaintext không bao giờ xuất hiện trong DB write
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_02_03_04_db_receives_only_password_hash_never_plaintext(
        self, mock_get_user, mock_update_pw
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })
        self.assertEqual(res.status_code, 200)

        # Lấy tham số gửi vào update_user_password
        called_args = mock_update_pw.call_args[1]
        passed_hash = called_args["new_password_hash"]

        # Hash không được trùng với mật khẩu plaintext
        self.assertNotEqual(passed_hash, self.new_password)
        # Hash phải verify thành công với mật khẩu mới
        self.assertTrue(check_password_hash(passed_hash, self.new_password))
        # Hash bắt đầu bằng tiền tố pbkdf2 hoặc scrypt bảo mật
        self.assertTrue(passed_hash.startswith("pbkdf2:") or passed_hash.startswith("scrypt:"))

    # 5 & 6. update đúng authenticated user, không update user khác
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_05_06_updates_only_authenticated_user(self, mock_get_user, mock_update_pw):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        res = self.post_change_password({
            "user_id": "other-user-victim",
            "current_password": self.current_password,
            "new_password": self.new_password,
        })
        self.assertEqual(res.status_code, 200)

        called_user_id = mock_update_pw.call_args[1]["user_id"]
        self.assertEqual(called_user_id, self.user_id)
        self.assertNotEqual(called_user_id, "other-user-victim")

    # 7. Lỗi DB tự động rollback và không cập nhật sai
    def test_07_db_error_triggers_rollback(self):
        with patch("app.repositories.user_repository.get_db_connection") as mock_conn:
            fake_conn = MagicMock()
            fake_cursor = MagicMock()
            fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
            mock_conn.return_value = fake_conn

            fake_cursor.execute.side_effect = MySQLError("Deadlock detected")

            with self.assertRaises(MySQLError):
                user_repository.update_user_password(self.user_id, "some-hash")

            fake_conn.rollback.assert_called_once()
            fake_conn.commit.assert_not_called()

    # 8. Lỗi DB trả 500 DATABASE_ERROR, không dùng mock fallback
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_08_db_error_returns_500_without_mock_fallback(self, mock_get_user, mock_update_pw):
        mock_get_user.return_value = self.user
        mock_update_pw.side_effect = MySQLError("Database unavailable")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")
        self.assertNotIn("thành công", res.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
