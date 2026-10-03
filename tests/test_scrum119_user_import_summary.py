"""
Bộ kiểm thử cho SCRUM-119: Bulk User Import - Activity A5.
Kiểm tra chi tiết cấu trúc tổng hợp summary, invariants đếm dòng, error_summary theo mã lỗi,
trạng thái row result, message tiếng Việt thân thiện với người dùng và tính bảo mật.
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
from app.models.user import User
from app.routes.user_routes import user_bp
from app.services.user_import_service import USER_IMPORT_TEMPLATE_HEADERS
from app.services.user_service import DuplicateEmailError, UserValidationError


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


class Scrum119UserImportSummaryTests(unittest.TestCase):
    """Test suite tập trung vào cấu trúc Summary, Invariants, Error Summary và Messages (Activity A5)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum119-a5-suite-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "admin-scrum119-a5"
        self.session_id = "session-scrum119-a5"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-119-a5",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

    def _create_token(self, user_id=None, session_id=None) -> str:
        with self.app.app_context():
            return create_access_token(
                identity=user_id or self.user_id,
                additional_claims={"sid": session_id or self.session_id},
            )

    def _setup_rbac_mocks(
        self,
        mock_get_session,
        mock_perm_repo,
        mock_ur_roles,
        mock_rp_codes,
        has_permission: bool = True,
    ):
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(
            id="perm-manage-id",
            code="user.manage",
            name="Manage Users",
        )

        if has_permission:
            mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
            mock_rp_codes.return_value = ["user.manage", "user.view"]
        else:
            mock_ur_roles.return_value = [Role(id="r-user", code="user", name="User")]
            mock_rp_codes.return_value = ["user.view"]

    # =========================================================================
    # 1. ALL SUCCESS SUMMARY
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_01_all_success_summary_and_counts(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """1. Tất cả các dòng hợp lệ và import thành công: counts, summary, invariant, message tiếng Việt."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_create_service.return_value = User(id="u-ok", email="ok@daotao.edu.vn")

        rows = [
            ["Người 1", "u1@daotao.edu.vn", "Pass1234", "0912345671", "trainee", "active"],
            ["Người 2", "u2@daotao.edu.vn", "Pass1234", "0912345672", "trainer", "active"],
            ["Người 3", "u3@daotao.edu.vn", "Pass1234", "0912345673", "user", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "all_success.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()

        # Kiểm tra top-level message
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["message"], "Đã import thành công 3 người dùng.")

        data = body["data"]
        self.assertEqual(data["filename"], "all_success.xlsx")
        self.assertEqual(data["total_rows"], 3)
        self.assertEqual(data["valid_rows"], 3)
        self.assertEqual(data["invalid_rows"], 0)
        self.assertEqual(data["imported_rows"], 3)
        self.assertEqual(data["skipped_rows"], 0)
        self.assertEqual(data["failed_rows"], 0)

        # Invariants
        self.assertEqual(data["total_rows"], data["imported_rows"] + data["skipped_rows"])
        self.assertEqual(data["skipped_rows"], data["invalid_rows"] + data["failed_rows"])
        self.assertEqual(data["valid_rows"], data["imported_rows"] + data["failed_rows"])

        # Summary nested object
        self.assertEqual(data["summary"]["success"], 3)
        self.assertEqual(data["summary"]["validation_errors"], 0)
        self.assertEqual(data["summary"]["import_errors"], 0)

        # Error summary trống
        self.assertEqual(data["error_summary"], {})

        # Rows check
        self.assertEqual(len(data["rows"]), 3)
        for r in data["rows"]:
            self.assertTrue(r["imported"])
            self.assertEqual(r["result"], "imported")
            self.assertEqual(r["errors"], [])
            self.assertNotIn("password", r)
            self.assertNotIn("password_hash", r)

    # =========================================================================
    # 2. PARTIAL SUCCESS SUMMARY
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_02_partial_success_mix_validation_and_import_errors(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """2. Partial success gồm: 2 import thành công, 2 lỗi validation, 1 lỗi ghi DB (tổng 5 dòng)."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        # Dòng 1: valid -> insert thành công
        # Dòng 2: invalid (thiếu tên) -> validation_error
        # Dòng 3: valid -> insert ném DuplicateEmailError (import_error)
        # Dòng 4: invalid (sai role) -> validation_error
        # Dòng 5: valid -> insert thành công
        mock_create_service.side_effect = [
            User(id="u1", email="u1@daotao.edu.vn"),
            DuplicateEmailError(),
            User(id="u5", email="u5@daotao.edu.vn"),
        ]

        rows = [
            ["Hợp lệ 1", "u1@daotao.edu.vn", "Pass1234", "0912345671", "trainee", "active"],
            ["", "u2@daotao.edu.vn", "Pass1234", "0912345672", "trainee", "active"],  # thiếu tên
            ["Hợp lệ DB Dup", "dup@daotao.edu.vn", "Pass1234", "0912345673", "trainee", "active"],  # ném DuplicateEmailError
            ["Sai Role", "u4@daotao.edu.vn", "Pass1234", "0912345674", "superadmin", "active"],  # sai role
            ["Hợp lệ 5", "u5@daotao.edu.vn", "Pass1234", "0912345675", "trainee", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "partial.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()

        # Top-level message
        self.assertEqual(body["message"], "Đã import 2/5 người dùng. Có 3 dòng không được import.")

        data = body["data"]
        self.assertEqual(data["total_rows"], 5)
        self.assertEqual(data["valid_rows"], 3)  # dòng 1, 3, 5 pass validation A3
        self.assertEqual(data["invalid_rows"], 2)  # dòng 2, 4 fail validation A3
        self.assertEqual(data["imported_rows"], 2)  # dòng 1, 5
        self.assertEqual(data["failed_rows"], 1)  # dòng 3
        self.assertEqual(data["skipped_rows"], 3)  # 2 validation + 1 DB

        # Invariants
        self.assertEqual(data["total_rows"], data["imported_rows"] + data["skipped_rows"])
        self.assertEqual(data["skipped_rows"], data["invalid_rows"] + data["failed_rows"])
        self.assertEqual(data["valid_rows"], data["imported_rows"] + data["failed_rows"])

        # Summary nested
        self.assertEqual(data["summary"]["success"], 2)
        self.assertEqual(data["summary"]["validation_errors"], 2)
        self.assertEqual(data["summary"]["import_errors"], 1)

        # Error summary
        self.assertEqual(data["error_summary"]["NAME_REQUIRED"], 1)
        self.assertEqual(data["error_summary"]["INVALID_ROLE"], 1)
        self.assertEqual(data["error_summary"]["DUPLICATE_EMAIL"], 1)

        # Check từng row result
        self.assertEqual(data["rows"][0]["result"], "imported")
        self.assertEqual(data["rows"][1]["result"], "validation_error")
        self.assertEqual(data["rows"][2]["result"], "import_error")
        self.assertEqual(data["rows"][3]["result"], "validation_error")
        self.assertEqual(data["rows"][4]["result"], "imported")

    # =========================================================================
    # 3. ALL VALIDATION FAILURE
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_03_all_validation_failure_summary(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """3. Toàn bộ file đều lỗi validation -> imported=0, skipped=total, message thông báo không có người dùng."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [
            ["", "bad-email", "123", "abc", "invalid_role", "bad_status"],
            ["User 2", "", "short", "0912", "user", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "all_invalid.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()

        self.assertEqual(body["message"], "Không có người dùng nào được import.")

        data = body["data"]
        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["valid_rows"], 0)
        self.assertEqual(data["invalid_rows"], 2)
        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["failed_rows"], 0)
        self.assertEqual(data["skipped_rows"], 2)

        # Invariants
        self.assertEqual(data["total_rows"], data["imported_rows"] + data["skipped_rows"])
        self.assertEqual(data["skipped_rows"], data["invalid_rows"] + data["failed_rows"])

        # Summary
        self.assertEqual(data["summary"]["success"], 0)
        self.assertEqual(data["summary"]["validation_errors"], 2)
        self.assertEqual(data["summary"]["import_errors"], 0)

        # create_user_service tuyệt đối không được gọi
        mock_create_service.assert_not_called()

        for r in data["rows"]:
            self.assertFalse(r["imported"])
            self.assertEqual(r["result"], "validation_error")

    # =========================================================================
    # 4. ALL IMPORT FAILURE (DATABASE LOCK / CRASH)
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_04_all_import_failure_after_valid_preview(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """4. Cả 2 dòng đều pass validation nhưng khi ghi DB đều thất bại -> import_errors=2, message không import được."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_create_service.side_effect = RuntimeError("Database connection failure")

        rows = [
            ["User 1", "u1@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
            ["User 2", "u2@daotao.edu.vn", "Password123", "0912345679", "trainer", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "db_all_fail.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()

        self.assertEqual(body["message"], "Không có người dùng nào được import.")

        data = body["data"]
        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(data["valid_rows"], 2)
        self.assertEqual(data["invalid_rows"], 0)
        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["failed_rows"], 2)
        self.assertEqual(data["skipped_rows"], 2)

        self.assertEqual(data["summary"]["success"], 0)
        self.assertEqual(data["summary"]["validation_errors"], 0)
        self.assertEqual(data["summary"]["import_errors"], 2)

        self.assertEqual(data["error_summary"]["IMPORT_FAILED"], 2)

        for r in data["rows"]:
            self.assertFalse(r["imported"])
            self.assertEqual(r["result"], "import_error")
            self.assertEqual(r["errors"][0]["code"], "IMPORT_FAILED")

    # =========================================================================
    # 5. ERROR SUMMARY GROUPING WITH MULTIPLE CODES PER ROW
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_05_error_summary_groups_accurately(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """5. error_summary đếm chính xác từng mã lỗi khi một dòng có nhiều lỗi đồng thời."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False

        rows = [
            # Row 1: Thiếu họ tên + Password quá ngắn -> NAME_REQUIRED + PASSWORD_TOO_SHORT
            ["", "u1@daotao.edu.vn", "123", "0912345678", "trainee", "active"],
            # Row 2: Sai định dạng email + Sai role -> INVALID_EMAIL + INVALID_ROLE
            ["User 2", "bad-email", "Password123", "0912345678", "manager", "active"],
            # Row 3: Thiếu họ tên + Sai định dạng email -> NAME_REQUIRED + INVALID_EMAIL
            ["", "another-bad-email", "Password123", "0912345678", "trainee", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "multi_errors.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]

        err_sum = data["error_summary"]
        self.assertEqual(err_sum.get("NAME_REQUIRED"), 2)
        self.assertEqual(err_sum.get("PASSWORD_TOO_SHORT"), 1)
        self.assertEqual(err_sum.get("INVALID_EMAIL"), 2)
        self.assertEqual(err_sum.get("INVALID_ROLE"), 1)

    # =========================================================================
    # 6. IDEMPOTENT RE-IMPORT SUMMARY REFLECTION
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_06_idempotent_reimport_summary_and_error_summary(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """6. Import lại file đã tồn tại toàn bộ email trong DB -> summary báo 0 imported, 2 validation_errors (DUPLICATE_EMAIL)."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = True  # Tất cả email đã có trong DB

        rows = [
            ["User 1", "u1@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
            ["User 2", "u2@daotao.edu.vn", "Password123", "0912345679", "trainer", "active"],
        ]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "reimport_exist.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()

        self.assertEqual(body["message"], "Không có người dùng nào được import.")

        data = body["data"]
        self.assertEqual(data["imported_rows"], 0)
        self.assertEqual(data["skipped_rows"], 2)
        self.assertEqual(data["summary"]["validation_errors"], 2)
        self.assertEqual(data["summary"]["import_errors"], 0)
        self.assertEqual(data["error_summary"]["DUPLICATE_EMAIL"], 2)
        mock_create_service.assert_not_called()

    # =========================================================================
    # 7. SINGLE ROW FILE SUMMARY
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_07_single_row_success_message(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """7. File chỉ có 1 dòng dữ liệu hợp lệ: thông điệp 'Đã import thành công 1 người dùng.'"""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_create_service.return_value = User(id="u-single", email="single@daotao.edu.vn")

        rows = [["Người Duy Nhất", "single@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "single.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()

        self.assertEqual(body["message"], "Đã import thành công 1 người dùng.")
        data = body["data"]
        self.assertEqual(data["total_rows"], 1)
        self.assertEqual(data["imported_rows"], 1)
        self.assertEqual(data["skipped_rows"], 0)
        self.assertEqual(data["summary"]["success"], 1)
        self.assertEqual(data["rows"][0]["result"], "imported")

    # =========================================================================
    # 8. SECURITY & CONTRACT STABILITY
    # =========================================================================
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.repositories.user_repository.check_email_exists")
    @patch("app.services.user_service.create_user_service")
    def test_08_response_contains_no_sensitive_data_and_stable_schema(
        self,
        mock_create_service,
        mock_check_email,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """8. Response JSON có cấu trúc ổn định cho frontend, tuyệt đối không lộ password/secret/stack trace."""
        self._setup_rbac_mocks(mock_get_session, mock_perm_repo, mock_ur_roles, mock_rp_codes)
        mock_check_email.return_value = False
        mock_create_service.return_value = User(id="u-sec", email="sec@daotao.edu.vn")

        rows = [["Security Check", "sec@daotao.edu.vn", "SuperSecret123", "0912345678", "user", "active"]]
        buf = _create_excel_file(rows=rows)

        token = self._create_token()
        res = self.client.post(
            "/api/users/import",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "security.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        raw_text = res.get_data(as_text=True)

        self.assertNotIn("SuperSecret123", raw_text)
        self.assertNotIn("Traceback", raw_text)
        self.assertNotIn("password_hash", raw_text)

        data = res.get_json()["data"]
        expected_keys = {
            "filename",
            "total_rows",
            "valid_rows",
            "invalid_rows",
            "imported_rows",
            "skipped_rows",
            "failed_rows",
            "summary",
            "error_summary",
            "message",
            "rows",
        }
        self.assertTrue(expected_keys.issubset(data.keys()))


if __name__ == "__main__":
    unittest.main()
