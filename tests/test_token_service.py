import unittest

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token

from app.services.token_service import create_login_tokens


class TokenServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["JWT_SECRET_KEY"] = (
            "test-only-key-not-for-real-application-123456"
        )
        JWTManager(self.app)

    def test_create_tokens_for_same_user_and_session(self):
        with self.app.app_context():
            tokens = create_login_tokens("test-user", "test-session")

            access = decode_token(tokens["access_token"])
            refresh = decode_token(tokens["refresh_token"])

            self.assertEqual(access["type"], "access")
            self.assertEqual(refresh["type"], "refresh")

            for payload in (access, refresh):
                self.assertEqual(payload["sub"], "test-user")
                self.assertEqual(payload["sid"], "test-session")

    def test_reject_empty_user_id(self):
        with self.app.app_context():
            with self.assertRaises(ValueError):
                create_login_tokens("", "test-session")