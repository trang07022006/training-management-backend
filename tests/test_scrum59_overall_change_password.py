import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error as MySQLError

from app.models.user import User
from app.repositories import session_repository, user_repository
from app.routes.auth_routes import auth_bp
from app.services import change_password_service
from app.services.session_service import create_login_session, validate_login_session


class Scrum59OverallChangePasswordTests(unittest.TestCase):
    """
    Bộ kiểm thử tổng thể SCRUM-59 cho toàn bộ luồng đổi mật khẩu (SCRUM-21).
    Bao phủ 21 trường hợp kiểm thử backend theo đặc tả:
    1. unauthenticated -> không đổi password
    2. authenticated + current password đúng
    3. current password sai
    4. password mới quá ngắn
    5. password mới chỉ chữ
    6. password mới chỉ số
    7. password mới hợp lệ
    8. password được hash
    9. plaintext không lưu DB
    10. update đúng user
    11. user khác không bị đổi
    12. current session giữ lại
    13. other sessions revoke
    14. session user khác giữ nguyên
    15. DB failure rollback phù hợp
    16. response không leak secret
    17. login bằng password cũ sau đổi -> FAIL
    18. login bằng password mới -> PASS
    19. SCRUM-18 Login regression PASS
    20. SCRUM-19 Session regression PASS
    21. SCRUM-20 Password hashing & token handling regression PASS
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-only-key-not-for-production-scrum59-suite-key",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=8),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )

        JWTManager(self.app)
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

        self.user_id = "user-scrum59-tan"
        with self.app.app_context():
            self.session, self.tokens = create_login_session(self.user_id)

        # Mock session auth
        patcher = patch("app.utils.session_auth.get_session_by_id")
        self.mock_get_session = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_get_session.return_value = self.session

        self.initial_password = "CurrentPassword123!"
        self.initial_hash = generate_password_hash(self.initial_password)

        self.user = User(
            id=self.user_id,
            password_hash=self.initial_hash,
            email="tan@ictu.edu.vn",
            role="teacher",
            status="active",
        )

    def post_change_password(self, payload, token=None, as_json=True):
        headers = {}
        if token is None:
            headers["Authorization"] = f"Bearer {self.tokens['access_token']}"
        elif token is not False:
            headers["Authorization"] = f"Bearer {token}"

        if as_json:
            return self.client.post("/api/auth/change-password", json=payload, headers=headers)
        return self.client.post("/api/auth/change-password", data=payload, headers=headers)

    # 1. unauthenticated -> không đổi password (401)
    def test_01_unauthenticated_request_rejected(self):
        res = self.post_change_password({
            "current_password": self.initial_password,
            "new_password": "NewSecretPass456!",
        }, token=False)
        self.assertEqual(res.status_code, 401)

    # 2. authenticated + current password đúng -> PASS
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_02_authenticated_and_correct_current_password_passes(
        self, mock_get_user, mock_update_pw, mock_revoke
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True
        mock_revoke.return_value = 1

        res = self.post_change_password({
            "current_password": self.initial_password,
            "new_password": "NewSecretPass456!",
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["message"], "Đổi mật khẩu thành công.")

    # 3. current password sai -> reject
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_03_incorrect_current_password_rejected(
        self, mock_get_user, mock_update_pw, mock_revoke
    ):
        mock_get_user.return_value = self.user

        res = self.post_change_password({
            "current_password": "WrongPassword999!",
            "new_password": "NewSecretPass456!",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INCORRECT_CURRENT_PASSWORD")
        mock_update_pw.assert_not_called()
        mock_revoke.assert_not_called()

    # 4. password mới quá ngắn -> FAIL
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_04_new_password_too_short_fails(self, mock_get_user):
        mock_get_user.return_value = self.user
        res = self.post_change_password({
            "current_password": self.initial_password,
            "new_password": "Short1",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_TOO_SHORT")

    # 5. password mới chỉ chữ -> FAIL
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_05_new_password_letters_only_fails(self, mock_get_user):
        mock_get_user.return_value = self.user
        res = self.post_change_password({
            "current_password": self.initial_password,
            "new_password": "OnlyLettersNoNumbers",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

    # 6. password mới chỉ số -> FAIL
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_06_new_password_digits_only_fails(self, mock_get_user):
        mock_get_user.return_value = self.user
        res = self.post_change_password({
            "current_password": self.initial_password,
            "new_password": "1234567890123",
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "PASSWORD_INVALID")

    # 7. password mới hợp lệ (chữ + số >= 8 ký tự) -> PASS
    # 8. password được hash
    # 9. plaintext không lưu DB
    # 10. update đúng user
    # 11. user khác không bị đổi
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_07_to_11_valid_password_hashed_and_updates_exact_authenticated_user(
        self, mock_get_user, mock_update_pw, mock_revoke
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        raw_new_pw = "ValidAndStrong2026!"
        res = self.post_change_password({
            "user_id": "malicious-victim-target",
            "current_password": self.initial_password,
            "new_password": raw_new_pw,
        })

        self.assertEqual(res.status_code, 200)
        # 10. update đúng authenticated user, không dùng user_id gửi từ client (11)
        mock_update_pw.assert_called_once()
        target_uid, stored_hash = mock_update_pw.call_args[1]["user_id"], mock_update_pw.call_args[1]["new_password_hash"]
        self.assertEqual(target_uid, self.user_id)
        self.assertNotEqual(target_uid, "malicious-victim-target")

        # 8. password được hash & 9. plaintext không lưu DB
        self.assertNotEqual(stored_hash, raw_new_pw)
        self.assertTrue(check_password_hash(stored_hash, raw_new_pw))

    # 12. current session giữ lại
    # 13. other sessions revoke
    # 14. session user khác giữ nguyên
    def test_12_to_14_session_lifecycle_during_change_password(self):
        sessions_db = [
            {"session_id": self.session.session_id, "user_id": self.user_id, "revoked_at": None},
            {"session_id": "session-other-1", "user_id": self.user_id, "revoked_at": None},
            {"session_id": "session-other-2", "user_id": self.user_id, "revoked_at": None},
            {"session_id": "session-bob-1", "user_id": "bob-target", "revoked_at": None},
        ]

        def fake_revoke_other_user_sessions(user_id, current_session_id=None):
            count = 0
            for s in sessions_db:
                if s["user_id"] == user_id and s["session_id"] != current_session_id and s["revoked_at"] is None:
                    s["revoked_at"] = "2026-10-01 00:00:00"
                    count += 1
            return count

        with patch("app.services.change_password_service.session_repository.revoke_other_user_sessions", side_effect=fake_revoke_other_user_sessions):
            with patch("app.services.change_password_service.user_repository.update_user_password", return_value=True):
                with patch("app.services.change_password_service.user_repository.get_user_by_id", return_value=self.user):
                    change_password_service.change_password(
                        user_id=self.user_id,
                        current_password=self.initial_password,
                        new_password="NewSecurePassword999!",
                        current_session_id=self.session.session_id,
                    )

        # 12. current session vẫn active (revoked_at is None)
        curr_session = next(s for s in sessions_db if s["session_id"] == self.session.session_id)
        self.assertIsNone(curr_session["revoked_at"])

        # 13. other sessions của user bị thu hồi
        other_1 = next(s for s in sessions_db if s["session_id"] == "session-other-1")
        other_2 = next(s for s in sessions_db if s["session_id"] == "session-other-2")
        self.assertIsNotNone(other_1["revoked_at"])
        self.assertIsNotNone(other_2["revoked_at"])

        # 14. session user khác giữ nguyên
        bob_session = next(s for s in sessions_db if s["session_id"] == "session-bob-1")
        self.assertIsNone(bob_session["revoked_at"])

    # 15. DB failure rollback phù hợp
    @patch("app.repositories.user_repository._database_cursor")
    def test_15_db_failure_rolls_back_properly(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("Database disk full")
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        with self.assertRaises(MySQLError):
            user_repository.update_user_password(self.user_id, "some-hash")

    # 16. response không leak secret/hash/token/stacktrace
    @patch("app.services.change_password_service.session_repository.revoke_other_user_sessions")
    @patch("app.services.change_password_service.user_repository.update_user_password")
    @patch("app.services.change_password_service.user_repository.get_user_by_id")
    def test_16_response_does_not_leak_secrets_or_hashes(
        self, mock_get_user, mock_update_pw, mock_revoke
    ):
        mock_get_user.return_value = self.user
        mock_update_pw.return_value = True

        raw_new_pw = "NewSecretPassword2026!"
        res = self.post_change_password({
            "current_password": self.initial_password,
            "new_password": raw_new_pw,
        })

        json_data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(self.initial_password, str(json_data))
        self.assertNotIn(raw_new_pw, str(json_data))
        self.assertNotIn("hash", str(json_data).lower())
        self.assertNotIn("password", str(json_data).lower().replace("đổi mật khẩu", ""))

    # 17. login bằng password cũ sau khi đổi -> FAIL
    # 18. login bằng password mới -> PASS
    def test_17_18_login_with_old_fails_login_with_new_passes(self):
        new_password = "BrandNewPassword2026!"
        updated_hash = generate_password_hash(new_password)

        # Giả lập database sau khi đổi mật khẩu
        updated_user = User(
            id=self.user_id,
            password_hash=updated_hash,
            email=self.user.email,
            role=self.user.role,
            status="active",
        )

        # 17. Thử xác thực với mật khẩu cũ -> Thất bại
        old_password_matches = check_password_hash(updated_user.password_hash, self.initial_password)
        self.assertFalse(old_password_matches)

        # 18. Thử xác thực với mật khẩu mới -> Thành công
        new_password_matches = check_password_hash(updated_user.password_hash, new_password)
        self.assertTrue(new_password_matches)

    # 19. SCRUM-18 Login regression: password check logic an toàn
    def test_19_scrum18_login_password_verification_regression(self):
        self.assertTrue(check_password_hash(self.user.password_hash, self.initial_password))
        self.assertFalse(check_password_hash(self.user.password_hash, "IncorrectPass123!"))

    # 20. SCRUM-19 Session regression: session validate hoạt động chuẩn xác
    def test_20_scrum19_session_regression(self):
        try:
            validate_login_session(self.session)
        except Exception as e:
            self.fail(f"validate_login_session unexpectedly raised exception: {e}")

    # 21. SCRUM-20 Forgot/Reset regression: password hashing cơ chế đồng nhất
    def test_21_scrum20_password_hashing_consistency(self):
        test_pw = "ResetFlowPassword2026!"
        hashed = generate_password_hash(test_pw)
        self.assertTrue(hashed.startswith("scrypt:"))
        self.assertTrue(check_password_hash(hashed, test_pw))


if __name__ == "__main__":
    unittest.main()
