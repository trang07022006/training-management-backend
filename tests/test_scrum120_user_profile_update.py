import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.config.jwt_handlers import register_jwt_handlers
from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.user_routes import user_bp


class Scrum120UserProfileUpdateTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-120 (Activity A3):
    Cho người dùng đang đăng nhập cập nhật hồ sơ cá nhân của CHÍNH MÌNH (PUT /api/v1/users/profile).
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum120-a3-suite-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "user-a3-120"
        self.session_id = "session-a3-120"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-a3-120",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.base_user = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
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

    # 1. Chưa login -> 401
    def test_01_unauthorized_when_missing_token(self):
        response = self.client.put("/api/v1/users/profile", json={"name": "New Name"})
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertIn("code", data)

    # 2. Update name thành công
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_02_update_name_success(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
            name="Nguyễn Văn A",
            role="trainee",
        )
        mock_update.return_value = True

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Trần Văn Mới"},
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json["status"], "success")
        self.assertEqual(res_json["message"], "Cập nhật hồ sơ thành công.")
        self.assertEqual(res_json["data"]["name"], "Trần Văn Mới")
        mock_update.assert_called_once()

    # 3. Update phone thành công
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_03_update_phone_success(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
            name="Nguyễn Văn A",
            phone="0912345678",
            role="trainee",
        )
        mock_update.return_value = True

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"phone": "0987654321"},
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json["data"]["phone"], "0987654321")

    # 4. Update date_of_birth thành công
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_04_update_date_of_birth_success(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
            name="Nguyễn Văn A",
            date_of_birth=date(1995, 5, 20),
            role="trainee",
        )
        mock_update.return_value = True

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"date_of_birth": "2004-05-20"},
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json["data"]["date_of_birth"], "2004-05-20")

    # 5. Update address thành công
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_05_update_address_success(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
            name="Nguyễn Văn A",
            address="Hà Nội",
            role="trainee",
        )
        mock_update.return_value = True

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"address": "Thái Nguyên"},
        )

        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json["data"]["address"], "Thái Nguyên")

    # 6. Partial update không làm mất field khác
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_06_partial_update_preserves_other_fields(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
            name="Nguyễn Văn A",
            phone="0912345678",
            date_of_birth=date(1995, 5, 20),
            address="123 Cầu Giấy",
            role="trainee",
        )
        mock_update.return_value = True

        token = self._create_token()
        # Chỉ gửi address
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"address": "Hải Phòng"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["address"], "Hải Phòng")
        self.assertEqual(data["name"], "Nguyễn Văn A")
        self.assertEqual(data["phone"], "0912345678")
        self.assertEqual(data["date_of_birth"], "1995-05-20")
        self.assertEqual(data["email"], "learner.a3@daotao.edu.vn")
        self.assertEqual(data["role"], "trainee")

        # Kiểm tra repository được gọi với đúng các giá trị bảo toàn
        mock_update.assert_called_with(
            user_id=self.user_id,
            name="Nguyễn Văn A",
            phone="0912345678",
            date_of_birth=date(1995, 5, 20),
            address="Hải Phòng",
        )

    # 7. Response trả dữ liệu mới đúng contract
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_07_response_contract_matches_expected_schema(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = User(
            id=self.user_id,
            email="learner.a3@daotao.edu.vn",
            name="Nguyễn Văn A",
            role="trainee",
        )
        mock_update.return_value = True

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Hoàng Nam",
                "phone": "0933333333",
                "date_of_birth": "1998-08-18",
                "address": "Đà Nẵng",
            },
        )

        self.assertEqual(response.status_code, 200)
        res = response.get_json()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["message"], "Cập nhật hồ sơ thành công.")

        data = res["data"]
        self.assertEqual(
            set(data.keys()),
            {"id", "name", "email", "phone", "date_of_birth", "address", "role"},
        )
        self.assertEqual(data["id"], self.user_id)
        self.assertEqual(data["name"], "Hoàng Nam")
        self.assertEqual(data["phone"], "0933333333")
        self.assertEqual(data["date_of_birth"], "1998-08-18")
        self.assertEqual(data["address"], "Đà Nẵng")
        self.assertEqual(data["role"], "trainee")

    # 8. Dữ liệu thực sự được lưu DB (repository call verification)
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_08_database_update_invoked_correctly(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True

        token = self._create_token()
        self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên Mới", "address": "Địa Chỉ Mới"},
        )

        mock_update.assert_called_once_with(
            user_id=self.user_id,
            name="Tên Mới",
            phone=self.base_user.phone,
            date_of_birth=self.base_user.date_of_birth,
            address="Địa Chỉ Mới",
        )

    # 9. Gọi GET sau PUT thấy dữ liệu mới
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_09_get_profile_after_put_returns_updated_data(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_update.return_value = True

        # Trạng thái ban đầu
        stateful_user = User(
            id=self.user_id,
            email="flow@daotao.edu.vn",
            name="Tên Cũ",
            address="Hà Nội",
            role="user",
        )

        def side_effect_get_user(u_id):
            if u_id == self.user_id:
                return stateful_user
            return None

        mock_get_user.side_effect = side_effect_get_user

        token = self._create_token()

        # Thực hiện PUT
        put_res = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên Đã Đổi", "address": "TP Hồ Chí Minh"},
        )
        self.assertEqual(put_res.status_code, 200)

        # Cập nhật stateful_user như repository đã làm
        stateful_user.name = "Tên Đã Đổi"
        stateful_user.address = "TP Hồ Chí Minh"

        # Thực hiện GET
        get_res = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.get_json()["data"]
        self.assertEqual(get_data["name"], "Tên Đã Đổi")
        self.assertEqual(get_data["address"], "TP Hồ Chí Minh")

    # 10. Không thể update user khác
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_10_cannot_update_other_user_via_client_params(self, mock_update, mock_get_user, mock_get_session):
        victim_id = "victim-user-999"
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True

        token = self._create_token()

        # Thử truyền user_id nạn nhân qua query param
        response = self.client.put(
            f"/api/v1/users/profile?user_id={victim_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Hacked Name"},
        )

        self.assertEqual(response.status_code, 200)
        # update_user_profile phải được gọi với user_id của chính người đăng nhập
        self.assertEqual(mock_update.call_args[1]["user_id"], self.user_id)
        mock_get_user.assert_called_with(self.user_id)

    # 11. Email không được đổi (bị từ chối)
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_11_reject_attempt_to_change_email(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "hack@example.com"},
        )

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data.get("code"), "PROFILE_FIELD_NOT_EDITABLE")
        self.assertIn("Email và vai trò không thể thay đổi từ hồ sơ cá nhân", data.get("message", ""))
        mock_update.assert_not_called()

    # 12. Role không được đổi (bị từ chối)
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_12_reject_attempt_to_change_role(self, mock_update, mock_get_session):
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
        mock_update.assert_not_called()

    # 13. Password / security fields không được đổi
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_13_reject_attempt_to_change_security_fields(self, mock_update, mock_get_session):
        mock_get_session.return_value = self.session
        token = self._create_token()

        for forbidden in ["password", "password_hash", "status", "failed_login_attempts", "locked_until", "id", "user_id"]:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={forbidden: "forbidden_value"},
            )
            self.assertEqual(response.status_code, 400, f"Field {forbidden} should be rejected")
            self.assertEqual(response.get_json().get("code"), "PROFILE_FIELD_NOT_EDITABLE")

        mock_update.assert_not_called()

    # 14. Date sai format -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_14_invalid_date_format_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        # Format sai (DD-MM-YYYY hoặc chuỗi không hợp lệ)
        invalid_dates = ["20-05-1995", "invalid-date", "2024-02-31", 12345]
        for bad_date in invalid_dates:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"date_of_birth": bad_date},
            )
            self.assertEqual(response.status_code, 400, f"Date {bad_date} should be rejected")
            self.assertEqual(response.get_json().get("code"), "INVALID_DATE_OF_BIRTH")

        mock_update.assert_not_called()

    # 15. Name rỗng -> 400
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_15_empty_name_returns_400(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        token = self._create_token()

        invalid_names = ["", "   ", None]
        for bad_name in invalid_names:
            response = self.client.put(
                "/api/v1/users/profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": bad_name},
            )
            self.assertEqual(response.status_code, 400, f"Name {bad_name} should be rejected")
            self.assertEqual(response.get_json().get("code"), "NAME_REQUIRED")

        mock_update.assert_not_called()

    # 16. DB error không leak stack trace
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_16_database_error_handled_cleanly(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.side_effect = MySQLError("Deadlock found when trying to get lock")

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên Mới"},
        )

        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertEqual(data.get("code"), "DATABASE_ERROR")
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    # 17. Hỗ trợ cả 2 endpoint aliases: /api/v1/users/profile và /api/users/profile
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_repository.update_user_profile")
    def test_17_supports_both_put_url_aliases(self, mock_update, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.base_user
        mock_update.return_value = True

        token = self._create_token()

        res1 = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên V1"},
        )
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.put(
            "/api/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên Default"},
        )
        self.assertEqual(res2.status_code, 200)

    # 18. User không tồn tại -> 404 USER_NOT_FOUND
    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    def test_18_user_not_found_returns_404(self, mock_get_user, mock_get_session):
        mock_get_session.return_value = self.session
        mock_get_user.return_value = None

        token = self._create_token()
        response = self.client.put(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Tên Mới"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json().get("code"), "USER_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
