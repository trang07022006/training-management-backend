import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask

from app.models.login_session import LoginSession
from app.services.session_service import (
    SessionValidationError,
    renew_stored_session,
)


class StoredSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SESSION_IDLE_TIMEOUT"] = timedelta(minutes=30)

        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

        self.session = LoginSession(
            session_id="session-test",
            user_id="user-test",
            refresh_jti="refresh-test",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        patcher = patch(
            "app.services.session_service.session_repository"
        )
        self.repository = patcher.start()
        self.addCleanup(patcher.stop)

        self.repository.get_session_by_id.return_value = self.session
        self.repository.update_session_activity.return_value = True

    def _renew(self, now=None, refresh_jti="refresh-test"):
        with self.app.app_context():
            return renew_stored_session(
                session_id="session-test",
                user_id="user-test",
                refresh_jti=refresh_jti,
                now=now if now is not None else (
                    self.now + timedelta(minutes=10)
                ),
            )

    def test_successful_renewal(self):
        renewed = self._renew()

        self.assertEqual(
            renewed.idle_expires_at,
            self.now + timedelta(minutes=40),
        )
        self.assertEqual(
            renewed.absolute_expires_at,
            self.session.absolute_expires_at,
        )
        self.repository.update_session_activity.assert_called_once_with(
            self.session,
            renewed,
        )

    def test_revoked_session_is_not_updated(self):
        self.session.revoked_at = self.now

        with self.assertRaisesRegex(
            SessionValidationError, "SESSION_REVOKED"
        ):
            self._renew()

        self.repository.update_session_activity.assert_not_called()

    def test_expired_session_is_not_updated(self):
        with self.assertRaisesRegex(
            SessionValidationError, "SESSION_EXPIRED"
        ):
            self._renew(now=self.session.idle_expires_at)

        self.repository.update_session_activity.assert_not_called()

    def test_wrong_refresh_token_is_not_accepted(self):
        with self.assertRaisesRegex(
            SessionValidationError, "REFRESH_TOKEN_INVALID"
        ):
            self._renew(refresh_jti="another-refresh-token")

        self.repository.update_session_activity.assert_not_called()

    def test_concurrent_update_returns_conflict(self):
        newer_session = replace(
            self.session,
            last_activity_at=self.now + timedelta(minutes=5),
            idle_expires_at=self.now + timedelta(minutes=35),
        )

        self.repository.get_session_by_id.side_effect = [
            self.session,
            newer_session,
        ]
        self.repository.update_session_activity.return_value = False

        with self.assertRaisesRegex(
            SessionValidationError, "SESSION_UPDATE_CONFLICT"
        ):
            self._renew()

        self.repository.update_session_activity.assert_called_once()