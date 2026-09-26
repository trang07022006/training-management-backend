from app.services.session_service import renew_login_session
import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask
from flask_jwt_extended import JWTManager, decode_token

from app.services.session_service import (
    SessionValidationError,
    create_login_session,
    validate_login_session,
)


class SessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

        self.app.config.update(
            JWT_SECRET_KEY="test-only-key-not-for-real-application-123456",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )

        JWTManager(self.app)

    def test_create_session_with_matching_tokens_and_deadlines(self):
        with self.app.app_context():
            session, tokens = create_login_session("test-user")

            access = decode_token(tokens["access_token"])
            refresh = decode_token(tokens["refresh_token"])

            self.assertEqual(session.user_id, "test-user")
            self.assertEqual(access["sid"], session.session_id)
            self.assertEqual(refresh["sid"], session.session_id)
            self.assertEqual(refresh["jti"], session.refresh_jti)

            self.assertEqual(
                session.idle_expires_at,
                session.created_at + timedelta(minutes=30),
            )

            self.assertEqual(
                session.absolute_expires_at,
                datetime.fromtimestamp(refresh["exp"], tz=timezone.utc),
            )

            self.assertLessEqual(
                session.idle_expires_at,
                session.absolute_expires_at,
            )

            self.assertIsNone(session.revoked_at)

    def test_accept_active_session(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")

        validate_login_session(
            session,
            now=session.created_at + timedelta(minutes=29),
        )

    def test_reject_session_at_idle_deadline(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")

        with self.assertRaisesRegex(
            SessionValidationError,
            "SESSION_EXPIRED",
        ):
            validate_login_session(
                session,
                now=session.idle_expires_at,
            )

    def test_reject_session_at_absolute_deadline(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")

        session.idle_expires_at = session.absolute_expires_at

        with self.assertRaisesRegex(
            SessionValidationError,
            "SESSION_EXPIRED",
        ):
            validate_login_session(
                session,
                now=session.absolute_expires_at,
            )

    def test_reject_revoked_session(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")

        session.revoked_at = session.created_at

        with self.assertRaisesRegex(
            SessionValidationError,
            "SESSION_REVOKED",
        ):
            validate_login_session(
                session,
                now=session.created_at,
            )
    def test_renew_session_extends_idle_deadline(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")
            activity_time = session.created_at + timedelta(minutes=10)

            renewed = renew_login_session(session, now=activity_time)

        self.assertEqual(
            renewed.idle_expires_at,
            session.created_at + timedelta(minutes=40),
        )
        self.assertEqual(renewed.last_activity_at, activity_time)
        self.assertEqual(renewed.session_id, session.session_id)
        self.assertEqual(
            renewed.absolute_expires_at,
            session.absolute_expires_at,
        )

        # Đối tượng ban đầu vẫn giữ hạn cũ.
        self.assertEqual(
            session.idle_expires_at,
            session.created_at + timedelta(minutes=30),
        )

    def test_renew_session_does_not_exceed_absolute_deadline(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")

            # Mô phỏng phiên đã được gia hạn nhiều lần trước đó.
            session.idle_expires_at = session.absolute_expires_at
            activity_time = session.absolute_expires_at - timedelta(minutes=5)

            renewed = renew_login_session(session, now=activity_time)

        self.assertEqual(
            renewed.idle_expires_at,
            session.absolute_expires_at,
        )

    def test_cannot_renew_expired_session(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")

            with self.assertRaisesRegex(
                SessionValidationError,
                "SESSION_EXPIRED",
            ):
                renew_login_session(
                    session,
                    now=session.idle_expires_at,
                )

    def test_cannot_renew_revoked_session(self):
        with self.app.app_context():
            session, _ = create_login_session("test-user")
            session.revoked_at = session.created_at

            with self.assertRaisesRegex(
                SessionValidationError,
                "SESSION_REVOKED",
            ):
                renew_login_session(
                    session,
                    now=session.created_at + timedelta(minutes=1),
                )