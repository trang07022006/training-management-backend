import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager

from app.routes.auth_routes import auth_bp
from app.services.session_service import create_login_session


class Scrum53ChangePasswordApiTests(unittest.TestCase):
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

        self.user_id = "user-scrum53-test"
        with self.app.app_context():
            self.session, self.tokens = create_login_session(self.user_id)

        # Patch repository cho session_auth decorator
        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get_session = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get_session.return_value = self.session

    def post_change_password(self, payload=None, token=None, is_json=True):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        elif token is None and token != False:
            headers["Authorization"] = f"Bearer {self.tokens['access_token']}"

        if is_json:
            return self.client.post(
                "/api/auth/change-password",
                json=payload,
                headers=headers,
            )
        else:
            return self.client.post(
                "/api/auth/change-password",
                data=payload,
                headers=headers,
            )

    # 1. Endpoint tồn tại và xử lý POST
    def test_01_endpoint_exists(self):
        res = self.post_change_password(
            payload={"current_password": "OldPass123!", "new_password": "NewPass456!"}
        )
        self.assertNotEqual(res.status_code, 404)

    # 2. Không có authentication -> bị từ chối 401
    def test_02_unauthenticated_request_rejected(self):
        res = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "OldPass123!", "new_password": "NewPass456!"},
        )
        self.assertEqual(res.status_code, 401)

    # 3. Authenticated request -> service được gọi với đúng user_id và session_id
    @patch("app.routes.auth_routes.change_password")
    def test_03_authenticated_request_calls_service(self, mock_service):
        mock_service.return_value = {"message": "Thành công"}

        res = self.post_change_password(
            payload={"current_password": "OldPass123!", "new_password": "NewPass456!"}
        )

        self.assertEqual(res.status_code, 200)
        mock_service.assert_called_once_with(
            user_id=self.user_id,
            current_password="OldPass123!",
            new_password="NewPass456!",
            current_session_id=self.session.session_id,
        )

    # 4. Thiếu current_password -> trả về 400
    def test_04_missing_current_password_rejected(self):
        res = self.post_change_password(
            payload={"new_password": "NewPass456!"}
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "CURRENT_PASSWORD_REQUIRED")

        # Rỗng
        res_empty = self.post_change_password(
            payload={"current_password": "", "new_password": "NewPass456!"}
        )
        self.assertEqual(res_empty.status_code, 400)
        self.assertEqual(res_empty.get_json()["code"], "CURRENT_PASSWORD_REQUIRED")

    # 5. Thiếu new_password -> trả về 400
    def test_05_missing_new_password_rejected(self):
        res = self.post_change_password(
            payload={"current_password": "OldPass123!"}
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NEW_PASSWORD_REQUIRED")

        # Rỗng
        res_empty = self.post_change_password(
            payload={"current_password": "OldPass123!", "new_password": ""}
        )
        self.assertEqual(res_empty.status_code, 400)
        self.assertEqual(res_empty.get_json()["code"], "NEW_PASSWORD_REQUIRED")

    # 6. Payload không phải JSON -> trả về 400
    def test_06_non_json_payload_rejected(self):
        res = self.post_change_password(
            payload="not-a-json-string",
            is_json=False,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_REQUEST")

    # 7. user_id gửi từ client không được sử dụng để đổi user khác
    @patch("app.routes.auth_routes.change_password")
    def test_07_client_supplied_user_id_is_strictly_ignored(self, mock_service):
        mock_service.return_value = {"message": "Thành công"}

        res = self.post_change_password(
            payload={
                "user_id": "malicious-hacker-trying-to-change-victim",
                "current_password": "OldPass123!",
                "new_password": "NewPass456!",
            }
        )

        self.assertEqual(res.status_code, 200)
        # Service nhận user_id từ JWT identity chứ không phải từ body
        self.assertEqual(mock_service.call_args[1]["user_id"], self.user_id)
        self.assertNotEqual(
            mock_service.call_args[1]["user_id"],
            "malicious-hacker-trying-to-change-victim",
        )

    # 8. Không leak thông tin nhạy cảm (không lộ password, hash, token trong response)
    def test_08_no_sensitive_info_leaked(self):
        res = self.post_change_password(
            payload={"current_password": "OldPass123!", "new_password": "NewPass456!"}
        )
        self.assertEqual(res.status_code, 200)
        body_text = res.get_data(as_text=True)

        self.assertNotIn("OldPass123!", body_text)
        self.assertNotIn("NewPass456!", body_text)
        self.assertNotIn("password_hash", body_text)
        self.assertNotIn("access_token", body_text)


if __name__ == "__main__":
    unittest.main()
