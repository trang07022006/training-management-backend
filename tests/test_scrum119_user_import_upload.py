"""
Bộ kiểm thử cho SCRUM-119: Bulk User Import - Activity A2.
Kiểm tra API upload file Excel và đọc dữ liệu từ sheet Users.
"""

from io import BytesIO
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
import openpyxl

from app.models.login_session import LoginSession
from app.models.permission import Permission
from app.models.role import Role
from app.routes.user_routes import user_bp
from app.services.user_import_service import USER_IMPORT_TEMPLATE_HEADERS


def _create_excel_file(
    sheet_name="Users",
    headers=None,
    rows=None,
) -> BytesIO:
    """Helper tạo file Excel in-memory phục vụ kiểm thử."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    col_headers = headers if headers is not None else USER_IMPORT_TEMPLATE_HEADERS
    if col_headers:
        ws.append(col_headers)

    if rows:
        for r in rows:
            ws.append(r)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class Scrum119UserImportUploadTests(unittest.TestCase):
    """
    Test suite cho Activity A2 (SCRUM-119):
    1. Không đăng nhập → 401 UNAUTHORIZED
    2. Thiếu quyền user.manage → 403 FORBIDDEN
    3. Không gửi file trong request → 400 FILE_REQUIRED
    4. File sai định dạng (không phải .xlsx) → 400 INVALID_FILE_TYPE
    5. File rỗng (0 bytes) → 400 FILE_EMPTY
    6. File .xlsx hỏng (corrupted bytes) → 400 INVALID_EXCEL_FILE
    7. Thiếu sheet 'Users' → 400 MISSING_USERS_SHEET
    8. Header của sheet 'Users' sai cấu trúc → 400 INVALID_HEADER
    9. File không có dòng dữ liệu nào sau header → 400 NO_DATA
    10. File hợp lệ → 200 OK với đầy đủ metadata và rows
    11. Bỏ qua các dòng hoàn toàn trống và giữ đúng row_number thực tế
    12. Response tuyệt đối không làm lộ mật khẩu plaintext (chỉ trả password_present)
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum119-a2-suite-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "admin-scrum119-a2"
        self.session_id = "session-scrum119-a2"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-119-a2",
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

    def test_01_unauthenticated_request_returns_401(self):
        """1. Không đăng nhập → 401 UNAUTHORIZED."""
        buf = _create_excel_file()
        res = self.client.post(
            "/api/users/import/preview",
            data={"file": (buf, "test.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data["code"], "UNAUTHORIZED")

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
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "test.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_missing_file_in_request_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """3. Không gửi file trong request → 400 FILE_REQUIRED."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        # Request không có trường "file"
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "FILE_REQUIRED")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_invalid_file_extension_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """4. File sai định dạng (.csv thay vì .xlsx) → 400 INVALID_FILE_TYPE."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        csv_bytes = BytesIO(b"name,email,password\nNguyen Van A,a@test.com,Pass123\n")
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (csv_bytes, "users.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "INVALID_FILE_TYPE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_empty_file_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """5. File rỗng (0 bytes) → 400 FILE_EMPTY."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        empty_bytes = BytesIO(b"")
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (empty_bytes, "empty.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "FILE_EMPTY")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_06_corrupted_xlsx_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """6. File .xlsx bị hỏng không thể đọc bằng openpyxl → 400 INVALID_EXCEL_FILE."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        corrupt_bytes = BytesIO(b"not a valid zip or excel content at all")
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (corrupt_bytes, "corrupt.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "INVALID_EXCEL_FILE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_07_missing_users_sheet_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """7. File thiếu sheet 'Users' (ví dụ có sheet 'Sheet1') → 400 MISSING_USERS_SHEET."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        buf = _create_excel_file(sheet_name="WrongSheet")
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "wrong_sheet.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "MISSING_USERS_SHEET")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_08_invalid_header_structure_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """8. Header của sheet 'Users' không đúng cấu trúc contract → 400 INVALID_HEADER."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        buf = _create_excel_file(
            sheet_name="Users",
            headers=["ho_ten", "thu_dien_tu", "mat_khau"],
            rows=[["Nguyen Van A", "a@test.com", "Pass123"]],
        )
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "invalid_header.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "INVALID_HEADER")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_09_no_data_rows_returns_400(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """9. File có header nhưng không có dòng dữ liệu nào → 400 NO_DATA."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        # Chỉ có header, không có rows
        buf = _create_excel_file(sheet_name="Users", rows=[])
        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "no_data.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data["code"], "NO_DATA")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_10_valid_file_returns_200_and_parses_rows(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """10. File hợp lệ → 200 OK với đúng số dòng và dữ liệu được đọc chuẩn."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        rows = [
            ["Nguyễn Văn A", "a@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],
            ["Trần Thị B", "b@daotao.edu.vn", "Password456", "0987654321", "trainer", "active"],
        ]
        buf = _create_excel_file(sheet_name="Users", rows=rows)

        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "valid_users.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

        preview_data = data["data"]
        self.assertEqual(preview_data["filename"], "valid_users.xlsx")
        self.assertEqual(preview_data["headers"], USER_IMPORT_TEMPLATE_HEADERS)
        self.assertEqual(preview_data["total_rows"], 2)
        self.assertEqual(len(preview_data["rows"]), 2)

        # Kiểm tra dòng 1
        row1 = preview_data["rows"][0]
        self.assertEqual(row1["row_number"], 2)
        self.assertEqual(row1["name"], "Nguyễn Văn A")
        self.assertEqual(row1["email"], "a@daotao.edu.vn")
        self.assertEqual(row1["phone"], "0912345678")
        self.assertEqual(row1["role"], "trainee")
        self.assertEqual(row1["status"], "active")
        self.assertTrue(row1["password_present"])
        # Đảm bảo không lộ plaintext password trong JSON response
        self.assertNotIn("password", row1)
        self.assertNotIn("Password123", res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_11_skips_blank_rows_and_preserves_actual_row_number(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """11. Bỏ qua các dòng hoàn toàn trống và giữ nguyên row_number thực tế trong Excel."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        rows = [
            ["Nguyễn Văn A", "a@daotao.edu.vn", "Password123", "0912345678", "trainee", "active"],  # row 2
            [None, None, None, None, None, None],  # row 3: dòng trống hoàn toàn -> phải bỏ qua
            ["", "   ", None, "", None, None],  # row 4: dòng chứa khoảng trắng -> phải bỏ qua
            ["Lê Văn C", "c@daotao.edu.vn", "Password789", "0900000000", "user", "inactive"],  # row 5
        ]
        buf = _create_excel_file(sheet_name="Users", rows=rows)

        res = self.client.post(
            "/api/users/import/preview",
            headers={"Authorization": f"Bearer {token}"},
            data={"file": (buf, "sparse_users.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        preview_data = res.get_json()["data"]

        # Chỉ có 2 dòng có dữ liệu
        self.assertEqual(preview_data["total_rows"], 2)
        parsed_rows = preview_data["rows"]
        self.assertEqual(len(parsed_rows), 2)

        # Hàng 1 thực tế ở dòng 2 của Excel
        self.assertEqual(parsed_rows[0]["row_number"], 2)
        self.assertEqual(parsed_rows[0]["name"], "Nguyễn Văn A")

        # Hàng 2 thực tế ở dòng 5 của Excel (do dòng 3 và 4 trống)
        self.assertEqual(parsed_rows[1]["row_number"], 5)
        self.assertEqual(parsed_rows[1]["name"], "Lê Văn C")


if __name__ == "__main__":
    unittest.main()
