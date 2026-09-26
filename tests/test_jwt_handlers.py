import unittest
from datetime import timedelta
from unittest.mock import Mock

from flask import Flask
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    jwt_required,
)

from app.config.jwt_handlers import register_jwt_handlers


class JwtHandlersTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-only-key-not-for-production-123456789",
        )

        jwt = JWTManager(self.app)
        register_jwt_handlers(jwt)

        self.business_handler = Mock(return_value={"ok": True})

        @self.app.get("/test/access")
        @jwt_required(locations=["headers"])
        def access_route():
            return self.business_handler()

        @self.app.post("/test/refresh")
        @jwt_required(refresh=True, locations=["headers"])
        def refresh_route():
            return self.business_handler()

        self.client = self.app.test_client()

    def make_token(self, refresh=False, expired=False):
        create_token = (
            create_refresh_token if refresh else create_access_token
        )
        lifetime = timedelta(seconds=-1 if expired else 300)

        with self.app.app_context():
            return create_token(
                identity="test-user",
                expires_delta=lifetime,
            )

    def auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    def assert_rejected(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.get_json(), {"code": code})
        self.business_handler.assert_not_called()

    def test_valid_access_token_still_works(self):
        token = self.make_token()

        response = self.client.get(
            "/test/access",
            headers=self.auth_header(token),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.business_handler.assert_called_once_with()

    def test_expired_access_token_has_specific_code(self):
        token = self.make_token(expired=True)

        response = self.client.get(
            "/test/access",
            headers=self.auth_header(token),
        )

        self.assert_rejected(
            response, 401, "ACCESS_TOKEN_EXPIRED"
        )

    def test_expired_refresh_token_ends_session(self):
        token = self.make_token(refresh=True, expired=True)

        response = self.client.post(
            "/test/refresh",
            headers=self.auth_header(token),
        )

        self.assert_rejected(response, 401, "SESSION_EXPIRED")

    def test_missing_token(self):
        response = self.client.get("/test/access")

        self.assert_rejected(response, 401, "AUTH_REQUIRED")

    def test_malformed_token(self):
        response = self.client.get(
            "/test/access",
            headers=self.auth_header("not-a-valid-jwt"),
        )

        self.assert_rejected(response, 422, "TOKEN_INVALID")

    def test_wrong_token_type(self):
        token = self.make_token(refresh=True)

        response = self.client.get(
            "/test/access",
            headers=self.auth_header(token),
        )

        self.assert_rejected(response, 422, "TOKEN_INVALID")


if __name__ == "__main__":
    unittest.main()