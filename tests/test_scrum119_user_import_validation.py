"""
Bộ kiểm thử cho SCRUM-119: Bulk User Import - Activity A3.
Kiểm tra chi tiết validation từng dòng dữ liệu và preview lỗi.
"""

from io import BytesIO
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
import openpyxl

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.routes.user_routes import user_bp
from app.services.user_import_service import USER_IMPORT_TEMPLATE_HEADERS


def _create_excel_file(rows=None) -> BytesIO:
    """Helper tạo file Excel in-memory với sheet Users và template header chuẩn."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users"
    ws.append(USER_IMPORT_TEMPLATE_HEADERS)

    if rows:
        for r in rows:
            ws.append(r)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class Scrum119UserImportValidationTests(unittest.TestCase):
    """
    Test suite cho Activity A3:
    1. Dòng hợp lệ → valid=True, errors=[]
    2. Thiếu họ tên → NAME_REQUIRED
    3. Email rỗng → EMAIL_REQUIRED
    4. Email sai format → INVALID_EMAIL
    5. Email đã tồn tại trong DB → DUPLICATE_EMAIL
    6. Email trùng trong cùng file → DUPLICATE_EMAIL_IN_FILE
    7. Thiếu password → PASSWORD_REQUIRED
    8. Password vi phạm chính sách (quá ngắn hoặc thiếu chữ/số) → PASSWORD_TOO_SHORT / PASSWORD_INVALID
    9. Phone không hợp lệ → INVALID_PHONE
    10. Role không hợp lệ → INVALID_ROLE
    11. Status không hợp lệ → INVALID_STATUS
    12. Trường phone tùy chọn để trống xử lý đúng (phone=None, không lỗi)
    13. Default role ('user') và status ('active') tự động áp dụng khi để trống
    14. Một dòng có nhiều lỗi thì trả đầy đủ errors
    15. Thống kê valid_rows và invalid_rows chính xác
    16. Tuyệt đối không để lộ mật khẩu plaintext trong response
    17. API preview tuyệt đối không ghi dữ liệu hay gọi create_user trong DB
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum119-a3-suite-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "admin-scrum119-a3"
        self.session_id = "session-scrum119-a3"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-119-a3",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

    def _create_token(self, user_id=None, session_id=None):
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    def _setup_rbac_mocks(self, mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_01_valid_row_returns_valid_true(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """1. Dòng hợp lệ đầy đủ → valid=True, errors=[]"""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn A", "a@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "valid.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 1)
        self.assertEqual(data["valid_rows"], 1)
        self.assertEqual(data["invalid_rows"], 0)

        row = data["rows"][0]
        self.assertTrue(row["valid"])
        self.assertEqual(row["errors"], [])
        self.assertEqual(row["name"], "Nguyễn Văn A")
        self.assertEqual(row["email"], "a@daotao.edu.vn")
        self.assertEqual(row["phone"], "0912345678")
        self.assertEqual(row["role"], "trainee")
        self.assertEqual(row["status"], "active")
        self.assertTrue(row["password_present"])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_02_missing_name_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """2. Thiếu họ tên hoặc khoảng trắng trống → NAME_REQUIRED."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["   ", "b@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "missing_name.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        error_codes = [e["code"] for e in row["errors"]]
        self.assertIn("NAME_REQUIRED", error_codes)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_empty_email_returns_error(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """3. Email rỗng → EMAIL_REQUIRED."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)

        rows = [["Trần Văn B", "", "Password123", "0912345678", "user", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "empty_email.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        error_codes = [e["code"] for e in row["errors"]]
        self.assertIn("EMAIL_REQUIRED", error_codes)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_invalid_email_format_returns_error(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """4. Email sai format → INVALID_EMAIL."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)

        rows = [["Trần Văn B", "not-an-email", "Password123", "0912345678", "user", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "invalid_email.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        error_codes = [e["code"] for e in row["errors"]]
        self.assertIn("INVALID_EMAIL", error_codes)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_05_email_already_exists_in_database_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """5. Email đã tồn tại trong DB → DUPLICATE_EMAIL."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = True

        rows = [["Lê Thị C", "exists@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "db_dup_email.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        error_codes = [e["code"] for e in row["errors"]]
        self.assertIn("DUPLICATE_EMAIL", error_codes)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_06_duplicate_email_in_same_file_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """6. Email trùng trong cùng file → dòng xuất hiện sau nhận DUPLICATE_EMAIL_IN_FILE."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [
            ["Người dùng 1", "same@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],  # row 2
            ["Người dùng 2", "same@daotao.edu.vn", "Password123", "0987654321", "trainer", "active"],  # row 3
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "file_dup_email.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        rows_data = res.get_json()["data"]["rows"]

        # Dòng 1 hợp lệ
        self.assertTrue(rows_data[0]["valid"])
        self.assertEqual(rows_data[0]["errors"], [])

        # Dòng 2 bị đánh lỗi DUPLICATE_EMAIL_IN_FILE
        self.assertFalse(rows_data[1]["valid"])
        error_codes = [e["code"] for e in rows_data[1]["errors"]]
        self.assertIn("DUPLICATE_EMAIL_IN_FILE", error_codes)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_07_missing_password_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """7. Mật khẩu để trống → PASSWORD_REQUIRED."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn D", "d@daotao.edu.vn", "", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "no_pass.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        error_codes = [e["code"] for e in row["errors"]]
        self.assertIn("PASSWORD_REQUIRED", error_codes)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_08_password_policy_violation_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """8. Mật khẩu < 8 ký tự hoặc thiếu chữ/số → PASSWORD_TOO_SHORT / PASSWORD_INVALID."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [
            ["User Short", "short@daotao.edu.vn", "Ab1", "0912345678", "trainee", "active"],  # < 8 ký tự
            ["User Letters", "letters@daotao.edu.vn", "onlylettershere", "0912345678", "trainee", "active"],  # thiếu số
            ["User Digits", "digits@daotao.edu.vn", "1234567890", "0912345678", "trainee", "active"],  # thiếu chữ
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "bad_passwords.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        rows_data = res.get_json()["data"]["rows"]

        # Row 1: quá ngắn
        self.assertIn("PASSWORD_TOO_SHORT", [e["code"] for e in rows_data[0]["errors"]])
        # Row 2: thiếu số
        self.assertIn("PASSWORD_INVALID", [e["code"] for e in rows_data[1]["errors"]])
        # Row 3: thiếu chữ
        self.assertIn("PASSWORD_INVALID", [e["code"] for e in rows_data[2]["errors"]])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_09_invalid_phone_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """9. Số điện thoại sai định dạng → INVALID_PHONE."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn E", "e@daotao.edu.vn", "Password123", "1234", "trainee", "active"]]  # quá ngắn
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "bad_phone.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        self.assertIn("INVALID_PHONE", [e["code"] for e in row["errors"]])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_10_invalid_role_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """10. Role không hợp lệ (không thuộc admin, trainer, trainee, user) → INVALID_ROLE."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn F", "f@daotao.edu.vn", "Password123", "0912345678", "super_admin", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "bad_role.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        self.assertIn("INVALID_ROLE", [e["code"] for e in row["errors"]])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_11_invalid_status_returns_error(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """11. Status không hợp lệ (không thuộc active, inactive, locked) → INVALID_STATUS."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn G", "g@daotao.edu.vn", "Password123", "0912345678", "trainee", "suspended"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "bad_status.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])
        self.assertIn("INVALID_STATUS", [e["code"] for e in row["errors"]])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_12_optional_phone_empty_handled_correctly(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """12. Trường phone để trống thì không phát sinh lỗi, phone trả về None."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn H", "h@daotao.edu.vn", "Password123", None, "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "empty_phone.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertTrue(row["valid"])
        self.assertIsNone(row["phone"])
        self.assertEqual(row["errors"], [])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_13_default_role_and_status_applied_when_omitted(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """13. Khi role và status để trống, tự động áp dụng default 'user' và 'active'."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [["Nguyễn Văn I", "i@daotao.edu.vn", "Password123", "0912345678", None, None]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "defaults.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertTrue(row["valid"])
        self.assertEqual(row["role"], "user")
        self.assertEqual(row["status"], "active")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_14_multiple_errors_in_single_row_reported_completely(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """14. Một dòng có nhiều lỗi thì mảng errors phải chứa đầy đủ tất cả các lỗi."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)

        # Dòng sai name, sai email, sai password, sai phone, sai role, sai status
        rows = [["", "bad-email", "123", "not-a-phone", "badrole", "badstatus"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "multi_errors.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]
        self.assertFalse(row["valid"])

        error_fields = {e["field"] for e in row["errors"]}
        self.assertIn("name", error_fields)
        self.assertIn("email", error_fields)
        self.assertIn("password", error_fields)
        self.assertIn("phone", error_fields)
        self.assertIn("role", error_fields)
        self.assertIn("status", error_fields)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_15_summary_counts_valid_and_invalid_rows_accurately(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """15. Thống kê valid_rows và invalid_rows chính xác theo từng trạng thái dòng."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [
            ["Hợp lệ 1", "v1@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],  # valid
            ["Lỗi Tên", "", "Password123", "0912345678", "trainee", "active"],  # invalid
            ["Hợp lệ 2", "v2@daotao.edu.vn", "Password123", "0912345678", "trainer", "active"],  # valid
            ["Lỗi Pass", "v3@daotao.edu.vn", "bad", "0912345678", "trainee", "active"],  # invalid
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "summary_check.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 4)
        self.assertEqual(data["valid_rows"], 2)
        self.assertEqual(data["invalid_rows"], 2)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_16_response_does_not_expose_plaintext_password(
        self,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """16. Response tuyệt đối không làm lộ mật khẩu plaintext (chỉ có password_present)."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        secret_password = "SecretPasswordToHide99"
        rows = [["Bảo Mật", "secure@daotao.edu.vn", secret_password, "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "security_check.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        row = res.get_json()["data"]["rows"][0]

        self.assertTrue(row["password_present"])
        self.assertNotIn("password", row)
        self.assertNotIn(secret_password, res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.create_user")
    @patch("app.repositories.user_repository.check_email_exists")
    def test_17_preview_does_not_create_users_or_modify_db(
        self,
        mock_check_email,
        mock_create_user,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """17. API preview tuyệt đối không ghi dữ liệu vào DB (create_user không bao giờ được gọi)."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [
            ["User 1", "u1@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
            ["User 2", "u2@daotao.edu.vn", "Password123", "0987654321", "trainer", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "no_write.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        # Khẳng định không có bất kỳ hành động insert người dùng nào diễn ra
        mock_create_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
