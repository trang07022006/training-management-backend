import unittest
from datetime import timedelta
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token
from mysql.connector import Error as MySQLError

from app.services.session_service import create_stored_login_session


class CreateStoredSessionTests(unittest.TestCase):
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

        patcher = patch(
            "app.services.session_service.session_repository.insert_session"
        )
        self.mock_insert = patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_session_matching_returned_tokens(self):
        with self.app.app_context():
            session, tokens = create_stored_login_session("test-user")

            access = decode_token(tokens["access_token"])
            refresh = decode_token(tokens["refresh_token"])

        self.mock_insert.assert_called_once_with(session)

        self.assertEqual(session.user_id, "test-user")
        self.assertEqual(access["sub"], session.user_id)
        self.assertEqual(refresh["sub"], session.user_id)
        self.assertEqual(access["sid"], session.session_id)
        self.assertEqual(refresh["sid"], session.session_id)
        self.assertEqual(refresh["jti"], session.refresh_jti)

    def test_raise_error_when_database_insert_fails(self):
        self.mock_insert.side_effect = MySQLError(
            "Simulated database failure"
        )

        with self.app.app_context():
            with self.assertRaises(MySQLError):
                create_stored_login_session("test-user")

        self.mock_insert.assert_called_once()

    def test_invalid_user_id_does_not_insert_session(self):
        with self.app.app_context():
            with self.assertRaises(ValueError):
                create_stored_login_session("")

        self.mock_insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
    