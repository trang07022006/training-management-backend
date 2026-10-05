import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.user_routes import user_bp


class Scrum120ProfileValidationTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-120 (Activity A4 & A5):
    A4: Bảo vệ các field không được phép tự sửa (email, role, status, password, id, ...).
    A5: Hoàn thiện validation hồ sơ cá nhân (name, phone VN, date_of_birth, address, empty payload, unknown fields).
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum120-a4a5-suite-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "user-val-120"
        self.session_id = "session-val-120"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-val-120",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.base_user = User(
            id=self.user_id,
            email="learner.val@daotao.edu.vn",
            password_hash="pbkdf2:sha256:600000$hash$value",
            name="Nguyễn Văn A",
            phone="0912345678",
            date_of_birth=date(1995, 5, 20),
            address="123 Đường Cầu Giấy, Hà Nội",
            role="trainee",
            status="active",
            failed_login_attempts=0,
            locked_until=None,
        )

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    # =========================================================================
    # A4: BẢO VỆ FIELD KHÔNG ĐƯỢC PHÉP SỬA
    # =========================================================================

    # 1. Email bị chặn
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_01_email_field_is_blocked(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "new_email@example.com"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "PROFILE_FIELD_NOT_EDITABLE")
        self.assertEqual(data.get("field"), "email")
        self.assertIn("Email và vai trò không thể thay đổi", data.get("message", ""))
        mock_update.assert_not_called()

    # 2. Role bị chặn
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_02_role_field_is_blocked(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "admin"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "PROFILE_FIELD_NOT_EDITABLE")
        self.assertEqual(data.get("field"), "role")
        mock_update.assert_not_called()

    # 3. Status bị chặn
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_03_status_field_is_blocked(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "inactive"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "PROFILE_FIELD_NOT_EDITABLE")
        self.assertEqual(data.get("field"), "status")
        mock_update.assert_not_called()

    # 4. Password / password_hash bị chặn
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_04_password_and_hash_are_blocked(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        for pwd_field in ["password", "password_hash"]:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={pwd_field: "injected_secret_value"},
            )
            self.assertEqual(response.status_code, 400)
            data = response.get_json()
            self.assertEqual(data.get("code"), "PROFILE_FIELD_NOT_EDITABLE")
            self.assertEqual(data.get("field"), pwd_field)
            mock_update.assert_not_called()

    # 5. Nhiều forbidden fields cùng lúc không update DB
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_05_multiple_forbidden_fields_rejected_together(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Tên Hợp Lệ",
                "email": "injected@daotao.vn",
                "role": "admin",
                "password": "pass",
                "status": "locked",
                "failed_login_attempts": 0,
            },
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "PROFILE_FIELD_NOT_EDITABLE")
        mock_update.assert_not_called()

    # 6. Message field cấm rõ ràng
    @patch("app.utils.session_auth.get_session_by_id")
    def test_06_forbidden_field_has_clear_error_message(self, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        res1 = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "hacked@example.com"},
        )
        self.assertIn("Email và vai trò không thể thay đổi", res1.get_json()["message"])

        res2 = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "locked"},
        )
        self.assertIn("Trường này không được phép thay đổi", res2.get_json()["message"])

    # =========================================================================
    # A5: VALIDATION PHONE VIỆT NAM
    # =========================================================================

    # 7. Phone VN hợp lệ -> PASS (các đầu số di động 03x, 05x, 07x, 08x, 09x)
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_07_valid_vietnamese_phone_numbers_pass(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        valid_phones = [
            "0912345678",  # Viettel / Vina / Mobi
            "0868889999",  # Viettel 086
            "0771234567",  # Mobifone 077
            "0561234567",  # Vietnamobile 056
            "0381234567",  # Viettel 038
            " 0987654321 ",  # Trim khoảng trắng hợp lệ
        ]

        for p in valid_phones:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"phone": p},
            )
            self.assertEqual(response.status_code, 200, f"Phone {p} should be valid")
            self.assertEqual(response.get_json()["data"]["phone"], p.strip())

    # 8. Phone null -> PASS (xóa số điện thoại)
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_08_phone_null_clears_phone(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"phone": None},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["data"]["phone"])
        mock_update.assert_called_with(
            user_id=self.user_id,
            name=self.base_user.name,
            phone=None,
            date_of_birth=self.base_user.date_of_birth,
            address=self.base_user.address,
        )

    # 9. Phone "" -> PASS / xóa đúng contract
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_09_phone_empty_string_clears_phone(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"phone": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["data"]["phone"])

    # 10. Phone quá ngắn -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_10_phone_too_short_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"phone": "091234567"},  # 9 chữ số
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "INVALID_PHONE")
        self.assertEqual(data.get("message"), "Số điện thoại không đúng định dạng.")
        mock_update.assert_not_called()

    # 11. Phone quá dài -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_11_phone_too_long_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"phone": "09123456789"},  # 11 chữ số
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json().get("code"), "INVALID_PHONE")
        mock_update.assert_not_called()

    # 12. Phone có chữ -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_12_phone_with_letters_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"phone": "091234567a"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json().get("code"), "INVALID_PHONE")
        mock_update.assert_not_called()

    # 13. Phone sai đầu số theo regex hiện tại -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_13_phone_with_invalid_prefix_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        invalid_prefixes = [
            "0123456789",  # Đầu 01x (11 số cũ, không hợp lệ)
            "0241234567",  # Đầu 02x cố định
            "0412345678",  # Đầu 04x không phải di động
            "1900123456",  # Tổng đài 1900
            "+8491234567",  # Không hỗ trợ +84 theo yêu cầu
        ]
        for bad_p in invalid_prefixes:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"phone": bad_p},
            )
            self.assertEqual(response.status_code, 400, f"Prefix {bad_p} should be rejected")
            self.assertEqual(response.get_json().get("code"), "INVALID_PHONE")
            mock_update.assert_not_called()

    # =========================================================================
    # A5: VALIDATION DATE OF BIRTH
    # =========================================================================

    # 14. DOB hợp lệ -> PASS
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_14_valid_dob_passes(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"date_of_birth": "1990-12-31"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["date_of_birth"], "1990-12-31")

    # 15. DOB sai format -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_15_dob_wrong_format_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        bad_formats = ["31-12-1990", "1990/12/31", "1990.12.31", "12-31-1990", "not-a-date"]
        for bad in bad_formats:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"date_of_birth": bad},
            )
            self.assertEqual(response.status_code, 400, f"Format {bad} should return 400")
            self.assertEqual(response.get_json().get("code"), "INVALID_DATE_OF_BIRTH")
            mock_update.assert_not_called()

    # 16. DOB ngày không tồn tại -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_16_dob_non_existent_date_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        non_existent_dates = [
            "2023-02-29",  # 2023 không phải năm nhuận
            "2024-02-30",  # Tháng 2 không bao giờ có ngày 30
            "2024-04-31",  # Tháng 4 chỉ có 30 ngày
            "2024-13-01",  # Tháng 13 không tồn tại
        ]
        for bad in non_existent_dates:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"date_of_birth": bad},
            )
            self.assertEqual(response.status_code, 400, f"Date {bad} should return 400")
            self.assertEqual(response.get_json().get("code"), "INVALID_DATE_OF_BIRTH")
            mock_update.assert_not_called()

    # 17. DOB tương lai -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_17_dob_future_date_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        future_date = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"date_of_birth": future_date},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json().get("code"), "INVALID_DATE_OF_BIRTH")
        mock_update.assert_not_called()

    # =========================================================================
    # A5: VALIDATION ADDRESS
    # =========================================================================

    # 18. Address <= 255 -> PASS
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_18_address_within_255_chars_passes(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        addr_255 = "A" * 255
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"address": addr_255},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["address"], addr_255)

    # 19. Address > 255 -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_19_address_exceeding_255_chars_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        addr_256 = "A" * 256
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"address": addr_256},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "ADDRESS_TOO_LONG")
        self.assertEqual(data.get("field"), "address")
        mock_update.assert_not_called()

    # 20. Unicode address -> PASS
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_20_unicode_vietnamese_address_passes(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        vn_address = "Số 123 Đường Cầu Giấy, Phường Dịch Vọng Hậu, Quận Cầu Giấy, Thành phố Hà Nội"
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"address": vn_address},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["address"], vn_address)

    # =========================================================================
    # A5: VALIDATION NAME
    # =========================================================================

    # 21. Name trim đúng
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_21_name_trimmed_correctly(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "   Nguyễn Văn B   "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["name"], "Nguyễn Văn B")
        self.assertEqual(mock_update.call_args[1]["name"], "Nguyễn Văn B")

    # 22. Name rỗng -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_22_empty_name_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        bad_names = ["", "     ", None]
        for bn in bad_names:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": bn},
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json().get("code"), "NAME_REQUIRED")
            mock_update.assert_not_called()

    # =========================================================================
    # A5: PAYLOAD KHÔNG HỢP LỆ (UNKNOWN / EMPTY)
    # =========================================================================

    # 23. Unknown field -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_23_unknown_field_returns_400(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên Mới", "unknown_custom_field": "val"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "UNKNOWN_FIELD")
        self.assertEqual(data.get("field"), "unknown_custom_field")
        mock_update.assert_not_called()

    # 24. Empty payload -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_24_empty_payload_returns_400(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json().get("code"), "EMPTY_UPDATE")
        mock_update.assert_not_called()

    # 25. Validation fail không thay đổi DB
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_25_validation_failure_does_not_update_db(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        # Thử nhiều loại validation fail
        fail_payloads = [
            {"phone": "invalid-phone"},
            {"date_of_birth": "2099-01-01"},
            {"address": "A" * 300},
            {"name": ""},
        ]
        for p in fail_payloads:
            res = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json=p,
            )
            self.assertEqual(res.status_code, 400)
            mock_update.assert_not_called()

    # 26. GET sau PUT hợp lệ trả dữ liệu đúng
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_26_get_after_valid_put_returns_updated_data(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_update.return_value = True

        current_user = User(
            id=self.user_id,
            email="learner.val@daotao.edu.vn",
            name="Tên Gốc",
            phone="0912345678",
            date_of_birth=date(1995, 1, 1),
            address="Hà Nội",
            role="trainee",
        )

        mock_get_user.side_effect = lambda u_id: current_user if u_id == self.user_id else None
        token = self._create_token()

        # Thực hiện PUT hợp lệ
        put_res = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Lê Văn Tiến",
                "phone": "0987654321",
                "date_of_birth": "2000-10-10",
                "address": "Đà Nẵng",
            },
        )
        self.assertEqual(put_res.status_code, 200)

        # Cập nhật state in-memory tương tự như repository
        current_user.name = "Lê Văn Tiến"
        current_user.phone = "0987654321"
        current_user.date_of_birth = date(2000, 10, 10)
        current_user.address = "Đà Nẵng"

        # Thực hiện GET
        get_res = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(get_res.status_code, 200)
        data = get_res.get_json()["data"]
        self.assertEqual(data["name"], "Lê Văn Tiến")
        self.assertEqual(data["phone"], "0987654321")
        self.assertEqual(data["date_of_birth"], "2000-10-10")
        self.assertEqual(data["address"], "Đà Nẵng")
        self.assertEqual(data["email"], "learner.val@daotao.edu.vn")
        self.assertEqual(data["role"], "trainee")


if __name__ == "__main__":
    unittest.main()
