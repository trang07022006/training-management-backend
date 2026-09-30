import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager
from mysql.connector import Error as MySQLError
from werkzeug.security import generate_password_hash

from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.change_password_service import (
    ChangePasswordError,
    change_password,
    verify_current_password,
)
from app.services.session_service import create_login_session


class Scrum54VerifyCurrentPasswordTests(unittest.TestCase):
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

        self.user_id = "user-scrum54-test"
        with self.app.app_context():
            self.session, self.tokens = create_login_session(self.user_id)

        # Mock session auth
        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get_session = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get_session.return_value = self.session

        self.raw_current_password = "CorrectPassword123!"
        self.hashed_password = generate_password_hash(self.raw_current_password)
        self.user = User(
            id=self.user_id,
            password_hash=self.hashed_password,
            email="user54@ictu.edu.vn",
            role="teacher",
            status="active",
        )

    def post_change_password(self, payload):
        return self.client.post(
            "/api/auth/change-password",
            json=payload,
            headers={"Authorization": f"Bearer {self.tokens['access_token']}"},
        )

    # 1. current password đúng -> PASS validation
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_01_correct_current_password_passes_validation(self, mock_get_user, mock_update_pw):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        res = self.post_change_password({
            "current_password": self.raw_current_password,
            "new_password": "NewSecretPassword456!",
        })

        self.assertEqual(res.status_code, 200)
        self.assertIn("thành công", res.get_json()["message"])

    # 2. current password sai -> reject với INCORRECT_CURRENT_PASSWORD
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_02_incorrect_current_password_rejected(self, mock_get_user):
        mock_get_user.return_value = self.user

        res = self.post_change_password({
            "current_password": "WrongPassword999!",
            "new_password": "NewSecretPassword456!",
        })

        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "INCORRECT_CURRENT_PASSWORD")
        self.assertEqual(data["message"], "Mật khẩu hiện tại không chính xác")

    # 3. user không tồn tại -> xử lý an toàn
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_03_nonexistent_user_handled_safely(self, mock_get_user):
        mock_get_user.return_value = None

        res = self.post_change_password({
            "current_password": self.raw_current_password,
            "new_password": "NewSecretPassword456!",
        })

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "USER_NOT_FOUND")

    # 4. password sai -> không thực hiện bất kỳ update nào vào DB
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_04_wrong_password_does_not_modify_db(self, mock_get_user):
        mock_get_user.return_value = self.user

        with patch("app.repositories.user_repository._database_cursor") as mock_cursor:
            res = self.post_change_password({
                "current_password": "WrongPassword999!",
                "new_password": "NewSecretPassword456!",
            })

            self.assertEqual(res.status_code, 400)
            mock_cursor.assert_not_called()

    # 5. Database error -> không fallback mock, trả về 500 DATABASE_ERROR
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_05_database_error_returns_500_without_mock_fallback(self, mock_get_user):
        mock_get_user.side_effect = MySQLError("Database connection timed out")

        res = self.post_change_password({
            "current_password": self.raw_current_password,
            "new_password": "NewSecretPassword456!",
        })

        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json()["code"], "DATABASE_ERROR")
        self.assertNotIn("thành công", res.get_data(as_text=True))

    # 6. Hash verification đúng cơ chế project (check_password_hash, không so sánh plaintext)
    def test_06_hash_verification_mechanism(self):
        # Plaintext so sánh trực tiếp phải trả False
        self.assertFalse(verify_current_password(self.raw_current_password, self.raw_current_password))
        # Hash hợp lệ với mật khẩu đúng
        self.assertTrue(verify_current_password(self.hashed_password, self.raw_current_password))
        # Hash hợp lệ với mật khẩu sai
        self.assertFalse(verify_current_password(self.hashed_password, "WrongPassword!"))
        # Rỗng / None
        self.assertFalse(verify_current_password("", self.raw_current_password))
        self.assertFalse(verify_current_password(self.hashed_password, ""))

    # 7. Password / hash không bao giờ xuất hiện trong response
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_07_password_and_hash_never_leaked_in_response(self, mock_get_user):
        mock_get_user.return_value = self.user

        res_ok = self.post_change_password({
            "current_password": self.raw_current_password,
            "new_password": "NewSecretPassword456!",
        })
        body_ok = res_ok.get_data(as_text=True)
        self.assertNotIn(self.raw_current_password, body_ok)
        self.assertNotIn(self.hashed_password, body_ok)

        res_fail = self.post_change_password({
            "current_password": "WrongPassword999!",
            "new_password": "NewSecretPassword456!",
        })
        body_fail = res_fail.get_data(as_text=True)
        self.assertNotIn("WrongPassword999!", body_fail)
        self.assertNotIn(self.hashed_password, body_fail)


if __name__ == "__main__":
    unittest.main()
