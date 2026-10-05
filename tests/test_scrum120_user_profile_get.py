import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.config.jwt_handlers import register_jwt_handlers
from app.models.login_session import LoginSession
from app.models.user import User
from app.repositories import user_repository
from app.routes.user_routes import user_bp
from app.services import user_service


class Scrum120UserProfileTests(unittest.TestCase):
    """
    Bộ kiểm thử cho SCRUM-120 (Activity A1 & A2):
    A1: Kiểm tra và chuẩn bị dữ liệu hồ sơ cá nhân (name, email, phone, date_of_birth, address, role).
    A2: Xây dựng API GET hồ sơ của chính user đang đăng nhập (GET /api/v1/users/profile).
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum120-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "test-user-120"
        self.session_id = "test-session-120"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-120",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.sample_user = User(
            id=self.user_id,
            email="learner@daotao.edu.vn",
            password_hash="pbkdf2:sha256:600000$supersecret$hashvalue",
            name="Nguyễn Văn A",
            phone="0912345678",
            date_of_birth=date(1995, 5, 20),
            address="123 Đường Cầu Giấy, Hà Nội",
            role="trainee",
            status="active",
            failed_login_attempts=1,
            locked_until=None,
        )

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    # =========================================================================
    # A1: KIỂM TRA MODEL & REPOSITORY DATA
    # =========================================================================

    def test_01_user_model_has_required_profile_fields(self):
        """Kiểm tra User model hỗ trợ đầy đủ các trường SCRUM-120: name, email, phone, date_of_birth, address, role."""
        u = User(
            id="u-test",
            email="test@example.com",
            name="Trần Thị B",
            phone="0987654321",
            date_of_birth=date(2000, 1, 15),
            address="Số 456 Lê Lợi, TP HCM",
            role="trainer",
        )
        self.assertEqual(u.id, "u-test")
        self.assertEqual(u.email, "test@example.com")
        self.assertEqual(u.name, "Trần Thị B")
        self.assertEqual(u.phone, "0987654321")
        self.assertEqual(u.date_of_birth, date(2000, 1, 15))
        self.assertEqual(u.address, "Số 456 Lê Lợi, TP HCM")
        self.assertEqual(u.role, "trainer")

    def test_02_to_profile_dict_contract_and_security(self):
        """Kiểm tra to_profile_dict() trả đúng cấu trúc và TUYỆT ĐỐI không lộ password hay metadata nhạy cảm."""
        profile = self.sample_user.to_profile_dict()

        # Đúng contract yêu cầu
        self.assertEqual(profile["id"], self.user_id)
        self.assertEqual(profile["name"], "Nguyễn Văn A")
        self.assertEqual(profile["email"], "learner@daotao.edu.vn")
        self.assertEqual(profile["phone"], "0912345678")
        self.assertEqual(profile["date_of_birth"], "1995-05-20")
        self.assertEqual(profile["address"], "123 Đường Cầu Giấy, Hà Nội")
        self.assertEqual(profile["role"], "trainee")

        # Bảo mật: Tuyệt đối không chứa các trường nhạy cảm
        self.assertNotIn("password", profile)
        self.assertNotIn("password_hash", profile)
        self.assertNotIn("failed_login_attempts", profile)
        self.assertNotIn("locked_until", profile)
        self.assertNotIn("session_id", profile)
        self.assertNotIn("refresh_token", profile)

    def test_03_to_profile_dict_with_nullable_fields(self):
        """Kiểm tra khi phone, date_of_birth, address chưa có (null), trả về null an toàn."""
        u = User(
            id="u-empty",
            email="empty@daotao.edu.vn",
            role="user",
        )
        profile = u.to_profile_dict()
        self.assertEqual(profile["id"], "u-empty")
        self.assertEqual(profile["email"], "empty@daotao.edu.vn")
        self.assertIsNone(profile["name"])
        self.assertIsNone(profile["phone"])
        self.assertIsNone(profile["date_of_birth"])
        self.assertIsNone(profile["address"])
        self.assertEqual(profile["role"], "user")

    def test_04_user_repository_row_to_user_maps_profile_fields(self):
        """Kiểm tra _row_to_user nạp đúng date_of_birth và address từ database record."""
        row = {
            "id": "u-row-1",
            "email": "test@daotao.vn",
            "password_hash": "hash123",
            "role": "admin",
            "status": "active",
            "failed_login_attempts": 0,
            "locked_until": None,
            "name": "Lê Văn C",
            "phone": "0901234567",
            "date_of_birth": date(1992, 10, 5),
            "address": "Tầng 5 Tòa nhà Keangnam, Hà Nội",
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        user = user_repository._row_to_user(row)
        self.assertEqual(user.date_of_birth, date(1992, 10, 5))
        self.assertEqual(user.address, "Tầng 5 Tòa nhà Keangnam, Hà Nội")

    # =========================================================================
    # A2: API GET CURRENT USER PROFILE (/api/v1/users/profile)
    # =========================================================================

    def test_05_unauthorized_when_missing_token(self):
        """1. Chưa đăng nhập (không gửi Authorization header) -> 401."""
        response = self.client.get("/api/v1/users/profile")
        self.assertEqual(response.status_code, 401)
        data = response.get_json()
        self.assertIn("code", data)

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_role_repository.get_primary_role_code_by_user_id")
    def test_06_get_profile_success_200(self, mock_get_role, mock_get_user, mock_get_session):
        """2. User hợp lệ đăng nhập -> 200, response JSON đúng contract."""
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.sample_user
        mock_get_role.return_value = "trainee"

        token = self._create_token()
        response = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        json_body = response.get_json()
        self.assertEqual(json_body.get("status"), "success")
        self.assertIn("data", json_body)

        data = json_body["data"]
        # 3. Trả đúng profile user đang đăng nhập
        self.assertEqual(data["id"], self.user_id)
        self.assertEqual(data["name"], "Nguyễn Văn A")
        # 4. Email đúng
        self.assertEqual(data["email"], "learner@daotao.edu.vn")
        # 5. Role đúng
        self.assertEqual(data["role"], "trainee")
        # 6. Phone, date_of_birth, address đúng
        self.assertEqual(data["phone"], "0912345678")
        self.assertEqual(data["date_of_birth"], "1995-05-20")
        self.assertEqual(data["address"], "123 Đường Cầu Giấy, Hà Nội")

        # 7. Không trả password/password_hash/dữ liệu nhạy cảm
        self.assertNotIn("password", data)
        self.assertNotIn("password_hash", data)
        self.assertNotIn("failed_login_attempts", data)
        self.assertNotIn("locked_until", data)

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.user_role_repository.get_primary_role_code_by_user_id")
    def test_07_get_profile_null_optional_fields(self, mock_get_role, mock_get_user, mock_get_session):
        """6. phone/date_of_birth/address trả null nếu user chưa cập nhật."""
        user_no_extra = User(
            id=self.user_id,
            email="minimal@daotao.edu.vn",
            name="Người Dùng Mới",
            phone=None,
            date_of_birth=None,
            address=None,
            role="user",
        )
        mock_get_session.return_value = self.session
        mock_get_user.return_value = user_no_extra
        mock_get_role.return_value = "user"

        token = self._create_token()
        response = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertIsNone(data["phone"])
        self.assertIsNone(data["date_of_birth"])
        self.assertIsNone(data["address"])

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    def test_08_cannot_read_other_user_profile_via_client_params(self, mock_get_user, mock_get_session):
        """8. Không thể dùng user_id client (query param hoặc body) để đọc profile người khác."""
        victim_id = "victim-user-999"
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.sample_user

        token = self._create_token()

        # Thử truyền query param user_id của nạn nhân
        response = self.client.get(
            f"/api/v1/users/profile?user_id={victim_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        # Phải trả về user của chính phiên đăng nhập, KHÔNG đọc nạn nhân
        self.assertEqual(data["id"], self.user_id)
        mock_get_user.assert_called_with(self.user_id)

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    def test_09_user_not_found_handling(self, mock_get_user, mock_get_session):
        """9. User trong token không còn tồn tại trong DB -> 404 USER_NOT_FOUND."""
        mock_get_session.return_value = self.session
        mock_get_user.return_value = None

        token = self._create_token()
        response = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data.get("code"), "USER_NOT_FOUND")

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    def test_10_database_error_handled_cleanly(self, mock_get_user, mock_get_session):
        """Lỗi DB được xử lý an toàn (500), không leak stack trace hay thông tin nhạy cảm."""
        mock_get_session.return_value = self.session
        mock_get_user.side_effect = MySQLError("Database connection timeout error")

        token = self._create_token()
        response = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertEqual(data.get("code"), "DATABASE_ERROR")
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    @patch("app.utils.session_auth.get_session_by_id")
    @patch("app.repositories.user_repository.get_user_by_id")
    def test_11_supports_both_url_aliases(self, mock_get_user, mock_get_session):
        """Hỗ trợ cả 2 endpoint: /api/v1/users/profile và /api/users/profile."""
        mock_get_session.return_value = self.session
        mock_get_user.return_value = self.sample_user

        token = self._create_token()

        res1 = self.client.get("/api/v1/users/profile", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.get("/api/users/profile", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res2.status_code, 200)

    @patch("app.utils.session_auth.get_session_by_id")
    def test_12_revoked_or_invalid_session_returns_401(self, mock_get_session):
        """Session không hợp lệ hoặc đã bị thu hồi -> 401."""
        revoked_session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-120",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
            revoked_at=self.now,
        )
        mock_get_session.return_value = revoked_session

        token = self._create_token()
        response = self.client.get(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json().get("code"), "SESSION_REVOKED")


if __name__ == "__main__":
    unittest.main()
