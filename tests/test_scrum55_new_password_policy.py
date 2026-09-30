import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.security import generate_password_hash

from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.change_password_service import (
    ChangePasswordError,
    change_password,
    validate_new_password_policy,
)
from app.services.session_service import create_login_session


class Scrum55NewPasswordPolicyTests(unittest.TestCase):
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

        self.user_id = "user-scrum55-test"
        with self.app.app_context():
            self.session, self.tokens = create_login_session(self.user_id)

        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get_session = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get_session.return_value = self.session

        revoke_patcher = patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
        self.mock_revoke_other = revoke_patcher.start()
        self.addCleanup(revoke_patcher.stop)

        self.current_password = "CurrentPassword123!"
        self.user = User(
            id=self.user_id,
            password_hash=generate_password_hash(self.current_password),
            email="user55@ictu.edu.vn",
            role="teacher",
            status="active",
        )

    def post_change_password(self, payload):
        return self.client.post(
            "/api/auth/change-password",
            json=payload,
            headers={"Authorization": f"Bearer {self.tokens['access_token']}"},
        )

    # 1. empty string -> FAIL
    def test_01_empty_password_fails(self):
        with self.assertRaises(ChangePasswordError) as ctx:
            validate_new_password_policy("")
        self.assertEqual(ctx.exception.code, "NEW_PASSWORD_REQUIRED")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": "",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NEW_PASSWORD_REQUIRED")

    # 2. null -> FAIL
    def test_02_null_password_fails(self):
        with self.assertRaises(ChangePasswordError) as ctx:
            validate_new_password_policy(None)
        self.assertEqual(ctx.exception.code, "NEW_PASSWORD_REQUIRED")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": None,
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NEW_PASSWORD_REQUIRED")

    # 3. dưới 8 ký tự -> FAIL
    def test_03_under_8_chars_fails(self):
        for short_pw in ["1", "ab1", "Pass1", "Seven7!"]:
            with self.assertRaises(ChangePasswordError) as ctx:
                validate_new_password_policy(short_pw)
            self.assertEqual(ctx.exception.code, "PASSWORD_TOO_SHORT")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": "Abc1",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_TOO_SHORT")

    # 4. chỉ chữ (không có số) -> FAIL
    def test_04_only_letters_fails(self):
        for letters_pw in ["OnlyLettersHere", "LongPasswordWithoutNumbers"]:
            with self.assertRaises(ChangePasswordError) as ctx:
                validate_new_password_policy(letters_pw)
            self.assertEqual(ctx.exception.code, "PASSWORD_INVALID")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": "OnlyLettersHere",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

    # 5. chỉ số (không có chữ) -> FAIL
    def test_05_only_digits_fails(self):
        for digits_pw in ["12345678", "9876543210123"]:
            with self.assertRaises(ChangePasswordError) as ctx:
                validate_new_password_policy(digits_pw)
            self.assertEqual(ctx.exception.code, "PASSWORD_INVALID")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": "1234567890123",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

    # 6. chữ + số >= 8 ký tự -> PASS
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_06_alphanumeric_8_or_more_chars_passes(self, mock_get_user, mock_update_pw):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        for valid_pw in ["ValidPass1", "SecurePassword2026", "A1b2C3d4E5!@#"]:
            validate_new_password_policy(valid_pw, current_password=self.current_password)

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": "NewValidPass999!",
        })
        self.assertEqual(res.status_code, 200)

    # 7. Mật khẩu mới trùng với mật khẩu hiện tại -> FAIL
    def test_07_same_as_current_password_fails(self):
        with self.assertRaises(ChangePasswordError) as ctx:
            validate_new_password_policy(
                self.current_password,
                current_password=self.current_password,
            )
        self.assertEqual(ctx.exception.code, "PASSWORD_SAME_AS_CURRENT")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.current_password,
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_SAME_AS_CURRENT")

    # 8. Validation error không thực hiện bất kỳ update nào vào DB
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_08_validation_error_does_not_modify_db(self, mock_get_user):
        mock_get_user.return_value = self.user

        with patch("app.repositories.user_repository._database_cursor") as mock_cursor:
            res = self.post_change_password({
                "current_password": self.current_password,
                "new_password": "short",
            })
            self.assertEqual(res.status_code, 400)
            mock_cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
