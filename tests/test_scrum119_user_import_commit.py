"""
Bộ kiểm thử cho SCRUM-119: Bulk User Import - Activity A4.
Kiểm tra thực thi import các dòng hợp lệ vào cơ sở dữ liệu và xử lý partial success.
"""

from io import BytesIO
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from werkzeug.security import check_password_hash
import openpyxl

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.routes.user_routes import user_bp
from app.services.user_import_service import USER_IMPORT_TEMPLATE_HEADERS
from app.services.user_service import DuplicateEmailError


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


class Scrum119UserImportCommitTests(unittest.TestCase):
    """
    Test suite cho Activity A4:
    1. Không đăng nhập → 401 UNAUTHORIZED
    2. Thiếu permission user.manage → 403 FORBIDDEN
    3. File có 1 dòng hợp lệ → user được tạo thành công
    4. Password được băm bằng werkzeug hash, không lưu plaintext, không lộ trong response
    5. Role và RBAC mapping được gán đúng
    6. Dòng không hợp lệ bị bỏ qua, không gọi tạo user
    7. Partial success: file có cả dòng valid và invalid → chỉ dòng valid được tạo, không rollback
    8. Duplicate email trong DB → bỏ qua dòng trùng, không tạo thêm user
    9. Duplicate email trong file → dòng đầu được tạo, dòng sau bị bỏ qua
    10. Import lại cùng file → phát hiện email đã tồn tại, không tạo trùng (idempotency)
    11. Lỗi DB ở một dòng → dòng đó import=False, các dòng hợp lệ khác vẫn được tạo bình thường
    12. Toàn bộ file không có dòng hợp lệ → không insert bất kỳ user nào
    13. Kiểm tra các lỗi file (thiếu file, file sai định dạng) trả về mã 400
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum119-a4-suite-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "admin-scrum119-a4"
        self.session_id = "session-scrum119-a4"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-119-a4",
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

    def test_01_unauthenticated_request_returns_401(self):
        """1. Không đăng nhập → 401 UNAUTHORIZED."""
        buf = _create_excel_file()
        res = self.client.post(
            "/api/users/import",
            data={"file": (buf, "test.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_02_forbidden_without_user_manage_returns_403(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """2. Người dùng thiếu quyền user.manage → 403 FORBIDDEN."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-view", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-trainer", code="trainer", name="Trainer")]
        mock_rp_codes.return_value = ["user.view"]

        token = self._create_token()
        buf = _create_excel_file()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "test.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_03_valid_single_row_creates_user(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """3. File có 1 dòng hợp lệ → create_user_service được gọi và import thành công."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        created_mock_user = User(
            id="new-uuid-1",
            email="nguyenvana@daotao.edu.vn",
            name="Nguyễn Văn A",
            role="trainer",
            status="active",
            phone="0912345678",
        )
        mock_create_service.return_value = created_mock_user

        rows = [["Nguyễn Văn A", "NguyenVanA@daotao.edu.vn", "Password123", "0912345678", "trainer", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "valid.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 1)
        self.assertEqual(data["imported_rows"], 1)
        self.assertEqual(data["skipped_rows"], 0)

        row_res = data["rows"][0]
        self.assertTrue(row_res["imported"])
        self.assertEqual(row_res["email"], "nguyenvana@daotao.edu.vn")
        self.assertEqual(row_res["errors"], [])

        # Kiểm tra create_user_service được gọi với đúng tham số chuẩn hóa
        mock_create_service.assert_called_once_with(
            email="nguyenvana@daotao.edu.vn",
            password="Password123",
            name="Nguyễn Văn A",
            phone="0912345678",
            role="trainer",
            status="active",
        )

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.repositories.user_repository.create_user")
    @patch("app.repositories.role_repository.get_role_by_code")
    @patch("app.repositories.user_role_repository.assign_role_to_user")
    def test_04_password_hashed_with_werkzeug_and_not_exposed(
        self,
        mock_assign_role,
        mock_get_role,
        mock_repo_create,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """4. Password được băm an toàn, không lưu plaintext, không xuất hiện trong response."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_get_role.return_value = Role(id="r-trainer", code="trainer", name="Trainer")

        def side_effect_create(user):
            user.id = "uuid-test-pass"
            return user
        mock_repo_create.side_effect = side_effect_create

        secret_raw_pass = "VerySecretPassword123"
        rows = [["Test User", "testpass@daotao.edu.vn", secret_raw_pass, "0912345678", "trainer", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "pass_test.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)

        # Kiểm tra user được truyền vào DB repository
        self.assertEqual(mock_repo_create.call_count, 1)
        created_user = mock_repo_create.call_args[0][0]

        # Password_hash phải là hash hợp lệ và xác thực được với plaintext
        self.assertNotEqual(created_user.password_hash, secret_raw_pass)
        self.assertTrue(check_password_hash(created_user.password_hash, secret_raw_pass))

        # Response tuyệt đối không chứa password plaintext
        self.assertNotIn(secret_raw_pass, res.get_data(as_text=True))
        row_res = res.get_json()["data"]["rows"][0]
        self.assertNotIn("password", row_res)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.repositories.user_repository.create_user")
    @patch("app.repositories.role_repository.get_role_by_code")
    @patch("app.repositories.user_role_repository.assign_role_to_user")
    def test_05_role_and_rbac_mapping_assigned_properly(
        self,
        mock_assign_role,
        mock_get_role,
        mock_repo_create,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """5. Role được ghi vào users và gán vào user_roles mapping bảng RBAC."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_get_role.return_value = Role(id="role-trainer-id", code="trainer", name="Trainer")

        mock_repo_create.side_effect = lambda u: u

        rows = [["Trainer Nam", "trainer.nam@daotao.edu.vn", "Password123", "0912345678", "trainer", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "role_test.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)

        # Kiểm tra gán role trong user_roles
        mock_get_role.assert_called_once_with("trainer")
        mock_assign_role.assert_called_once()
        self.assertEqual(mock_assign_role.call_args[0][1], "role-trainer-id")
        created_user = mock_repo_create.call_args[0][0]
        self.assertEqual(mock_assign_role.call_args[0][0], created_user.id)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.create_user_service")
    def test_06_invalid_row_is_skipped_without_calling_create(
        self,
        mock_create_service,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """6. Dòng lỗi không hợp lệ (sai email, thiếu tên) không bao giờ gọi create_user_service."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)

        rows = [["", "not-an-email", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "invalid_row.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["skipped_rows"], 1)
        row_res = data["rows"][0]
        self.assertFalse(row_res["imported"])
        self.assertGreater(len(row_res["errors"]), 0)

        mock_create_service.assert_not_called()

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_07_partial_success_mix_valid_and_invalid(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """7. Partial success: file có cả dòng hợp lệ và lỗi → chỉ dòng hợp lệ được import, không rollback."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        mock_create_service.return_value = User(id="u-ok", email="ok@test.com")

        rows = [
            ["User 1", "u1@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],  # valid
            ["User 2", "bad-email-format", "Password123", "0912345678", "trainee", "active"],  # invalid
            ["User 3", "u3@daotao.edu.vn", "Password123", "0912345678", "trainer", "active"],  # valid
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "mixed.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 3)
        self.assertEqual(data["imported_rows"], 2)
        self.assertEqual(data["skipped_rows"], 1)

        # Dòng 1: imported = True
        self.assertTrue(data["rows"][0]["imported"])
        # Dòng 2: imported = False
        self.assertFalse(data["rows"][1]["imported"])
        # Dòng 3: imported = True
        self.assertTrue(data["rows"][2]["imported"])

        # create_user_service được gọi đúng 2 lần cho dòng 1 và 3
        self.assertEqual(mock_create_service.call_count, 2)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_08_duplicate_email_in_db_skips_row(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """8. Email trùng với DB → dòng bị bỏ qua, không gọi tạo user."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = True

        rows = [["Trùng DB", "exists@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "db_dup.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["skipped_rows"], 1)
        self.assertFalse(data["rows"][0]["imported"])
        self.assertIn("DUPLICATE_EMAIL", [e["code"] for e in data["rows"][0]["errors"]])
        mock_create_service.assert_not_called()

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_09_duplicate_email_in_same_file_imports_first_only(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """9. Email trùng lặp trong cùng file → dòng đầu import=True, dòng sau import=False."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_create_service.return_value = User(id="u-same", email="same@daotao.edu.vn")

        rows = [
            ["Lần 1", "same@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],  # row 2
            ["Lần 2", "same@daotao.edu.vn", "Password123", "0987654321", "trainer", "active"],  # row 3
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "file_dup.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["imported_rows"], 1)
        self.assertEqual(data["skipped_rows"], 1)
        self.assertTrue(data["rows"][0]["imported"])
        self.assertFalse(data["rows"][1]["imported"])
        self.assertIn("DUPLICATE_EMAIL_IN_FILE", [e["code"] for e in data["rows"][1]["errors"]])

        # create_user_service chỉ được gọi đúng 1 lần cho dòng 1
        self.assertEqual(mock_create_service.call_count, 1)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_10_idempotent_reimport_does_not_create_duplicate(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """10. Import lại cùng file → DB báo đã tồn tại email nên không tạo duplicate (idempotent)."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)

        # Mô phỏng lần 2: check_email_exists trả về True vì đã được tạo ở lần 1
        mock_check_email.return_value = True

        rows = [["Đã Tạo", "already.imported@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "reimport.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["skipped_rows"], 1)
        self.assertFalse(data["rows"][0]["imported"])
        mock_create_service.assert_not_called()

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_11_single_row_db_failure_does_not_abort_other_rows(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """11. Một dòng bị lỗi khi ghi DB → chỉ dòng đó import=False, dòng khác vẫn thành công."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        # Dòng 1 ném exception bất ngờ khi ghi DB, dòng 2 thành công
        mock_create_service.side_effect = [
            RuntimeError("Database lock timeout"),
            User(id="u-ok-2", email="u2@daotao.edu.vn"),
        ]

        rows = [
            ["Dòng Lỗi DB", "error_db@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
            ["Dòng Thành Công", "success@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "db_fail.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["imported_rows"], 1)
        self.assertEqual(data["skipped_rows"], 1)

        self.assertFalse(data["rows"][0]["imported"])
        self.assertIn("IMPORT_FAILED", [e["code"] for e in data["rows"][0]["errors"]])

        self.assertTrue(data["rows"][1]["imported"])
        self.assertEqual(data["rows"][1]["errors"], [])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_service.create_user_service")
    def test_12_all_invalid_rows_inserts_nothing(
        self,
        mock_create_service,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """12. Toàn bộ file không có dòng hợp lệ → không gọi tạo user nào, imported_rows=0."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)

        rows = [
            ["", "bad1", "123", "", "invalid_role", ""],
            ["", "bad2", "abc", "", "invalid_role", ""],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "all_bad.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["skipped_rows"], 2)
        mock_create_service.assert_not_called()

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_13_file_upload_errors_return_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """13. Thiếu file hoặc file sai định dạng trả về 400 rõ ràng."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        token = self._create_token()

        # Không đính kèm file
        res1 = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={},
            content_type="multipart/form-data",
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "FILE_REQUIRED")

        # File không phải .xlsx
        res2 = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (BytesIO(b"name,email\n"), "test.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "INVALID_FILE_TYPE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_14_race_condition_duplicate_email_on_insert(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """14. Race condition: pass lúc validate nhưng lúc insert ném DuplicateEmailError -> đánh dấu row failed, không crash batch."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        # Dòng 1 ném DuplicateEmailError lúc insert, dòng 2 thành công
        mock_create_service.side_effect = [
            DuplicateEmailError(),
            User(id="u-ok-race", email="race2@daotao.edu.vn"),
        ]

        rows = [
            ["Race Row 1", "race1@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
            ["Race Row 2", "race2@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "race.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["imported_rows"], 1)
        self.assertEqual(data["skipped_rows"], 1)
        self.assertFalse(data["rows"][0]["imported"])
        self.assertEqual(data["rows"][0]["errors"][0]["code"], "DUPLICATE_EMAIL")
        self.assertTrue(data["rows"][1]["imported"])


if __name__ == "__main__":
    unittest.main()

