import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager
from mysql.connector import Error as MySQLError
from werkzeug.security import generate_password_hash

from app.models.user import User
from app.routes.auth_routes import auth_bp
from app.services.session_service import create_login_session


class Scrum57ChangePasswordResponsesTests(unittest.TestCase):
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

        self.user_id = "user-scrum57-test"
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
        self.new_password = "BrandNewPassword2026!"
        self.user = User(
            id=self.user_id,
            password_hash=generate_password_hash(self.current_password),
            email="user57@ictu.edu.vn",
            role="teacher",
            status="active",
        )

    def post_change_password(self, payload, token=None):
        headers = {}
        if token is None and token != False:
            headers["Authorization"] = f"Bearer {self.tokens['access_token']}"
        elif token:
            headers["Authorization"] = f"Bearer {token}"

        return self.client.post(
            "/api/auth/change-password",
            json=payload,
            headers=headers,
        )

    # 1. Success response
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_01_success_response(self, mock_get_user, mock_update_pw):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {
            "message": "Đổi mật khẩu thành công."
        })

    # 2. Incorrect current password response
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_02_incorrect_current_password_response(self, mock_get_user):
        mock_get_user.return_value = self.user

        res = self.post_change_password({
            "current_password": "WrongPassword999!",
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json(), {
            "code": "INCORRECT_CURRENT_PASSWORD",
            "message": "Mật khẩu hiện tại không chính xác",
        })

    # 3. Invalid new password response
    def test_03_invalid_new_password_response(self):
        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": "short",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_TOO_SHORT")

    # 4. Unauthenticated response
    def test_04_unauthenticated_response(self):
        res = self.post_change_password(
            payload={
                "current_password": self.current_password,
                "new_password": self.new_password,
            },
            token=False,
        )
        self.assertEqual(res.status_code, 401)

    # 5. Server/database failure response - no stack trace leak
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_05_server_database_failure_response(self, mock_get_user):
        mock_get_user.side_effect = MySQLError("SELECT error from internal mysql host:port")

        res = self.post_change_password({
            "current_password": self.current_password,
            "new_password": self.new_password,
        })

        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn("Traceback", res.get_data(as_text=True))
        self.assertNotIn("mysql host:port", res.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
