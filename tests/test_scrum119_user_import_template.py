"""
Bộ kiểm thử cho SCRUM-119: Bulk User Import - Activity A1.
Kiểm tra API tải file Excel mẫu và cấu trúc file template.
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
from app.services.user_import_service import (
    EXCEL_MIMETYPE,
    USER_IMPORT_TEMPLATE_FILENAME,
    USER_IMPORT_TEMPLATE_HEADERS,
    generate_user_import_template,
)


class Scrum119UserImportTemplateTests(unittest.TestCase):
    """
    Test suite cho Activity A1 (SCRUM-119):
    1. Không đăng nhập (thiếu Authorization) -> 401 UNAUTHORIZED
    2. Không có permission user.manage -> 403 FORBIDDEN
    3. Có permission user.manage -> 200 OK với đúng Content-Type và Content-Disposition
    4. File trả về mở được bằng openpyxl, header đúng contract create user
    5. Dòng dữ liệu mẫu không chứa dữ liệu thật/nhạy cảm và tuân thủ policy
    6. Sheet hướng dẫn (Huong_Dan) tồn tại và đầy đủ thông tin
    7. Xử lý lỗi hệ thống -> 500 INTERNAL_ERROR
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum119-suite-that-is-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(user_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.user_id = "admin-scrum119"
        self.session_id = "session-scrum119"

        self.session = LoginSession(
            session_id=self.session_id,
            user_id=self.user_id,
            refresh_jti="ref-jti-119",
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
        """1. Không đăng nhập -> 401 UNAUTHORIZED."""
        res = self.client.get("/api/users/import/template")
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
        """2. Người dùng không có quyền user.manage -> 403 FORBIDDEN."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-view", code="user.view", name="Xem user")
        mock_ur_roles.return_value = [Role(id="r-trainer", code="trainer", name="Trainer")]
        mock_rp_codes.return_value = ["user.view", "course.view"]

        token = self._create_token()
        res = self.client.get(
            "/api/users/import/template",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_03_authorized_user_manage_returns_200_excel_file(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """3. Người dùng có quyền user.manage -> 200 OK với đúng Content-Type và Content-Disposition."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage", "user.view"]

        token = self._create_token()
        res = self.client.get(
            "/api/users/import/template",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(res.status_code, 200)
        self.assertIn(EXCEL_MIMETYPE, res.headers.get("Content-Type", ""))
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        self.assertIn(USER_IMPORT_TEMPLATE_FILENAME, res.headers.get("Content-Disposition", ""))

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_04_downloaded_file_is_valid_excel_and_matches_contract(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """4. File tải về mở được bằng openpyxl, header chuẩn xác theo contract tạo user."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        res = self.client.get(
            "/api/users/import/template",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 200)

        # Mở bằng openpyxl
        wb = openpyxl.load_workbook(BytesIO(res.data))
        self.assertIn("Users", wb.sheetnames)

        ws_users = wb["Users"]
        headers = [cell.value for cell in ws_users[1]]

        # Kiểm tra contract header: name, email, password, phone, role, status
        self.assertEqual(headers, USER_IMPORT_TEMPLATE_HEADERS)
        self.assertListEqual(
            headers,
            ["name", "email", "password", "phone", "role", "status"],
        )

        # Kiểm tra dòng mẫu minh họa
        sample_row = [cell.value for cell in ws_users[2]]
        self.assertEqual(len(sample_row), len(headers))
        self.assertEqual(sample_row[0], "Nguyen Van A")
        self.assertIn("@", sample_row[1])
        # Password mẫu phải thỏa mãn độ dài >= 8, có chữ và số
        self.assertGreaterEqual(len(sample_row[2]), 8)
        self.assertTrue(any(c.isalpha() for c in sample_row[2]))
        self.assertTrue(any(c.isdigit() for c in sample_row[2]))
        # Role và status phải hợp lệ
        self.assertIn(sample_row[4], ["admin", "trainer", "trainee", "user"])
        self.assertIn(sample_row[5], ["active", "inactive", "locked"])

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_05_guide_sheet_provides_field_requirements(
        self,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """5. Sheet hướng dẫn (Huong_Dan) mô tả rõ ràng các ràng buộc bắt buộc và tùy chọn."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]

        token = self._create_token()
        res = self.client.get(
            "/api/users/import/template",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 200)

        wb = openpyxl.load_workbook(BytesIO(res.data))
        self.assertIn("Huong_Dan", wb.sheetnames)

        ws_guide = wb["Huong_Dan"]
        guide_fields = [ws_guide.cell(row=r, column=1).value for r in range(2, 8)]
        self.assertEqual(guide_fields, USER_IMPORT_TEMPLATE_HEADERS)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.services.authorization_service.permission_repository.get_permission_by_code")
    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    @patch("app.services.user_import_service.generate_user_import_template")
    def test_06_server_error_returns_500(
        self,
        mock_generate,
        mock_rp_codes,
        mock_ur_roles,
        mock_perm_repo,
        mock_get_session,
    ):
        """6. Xảy ra lỗi ngoài ý muốn khi tạo file -> 500 INTERNAL_ERROR."""
        mock_get_session.return_value = self.session
        mock_perm_repo.return_value = Permission(id="p-manage", code="user.manage", name="Quản lý user")
        mock_ur_roles.return_value = [Role(id="r-admin", code="admin", name="Admin")]
        mock_rp_codes.return_value = ["user.manage"]
        mock_generate.side_effect = RuntimeError("Excel generation failure")

        token = self._create_token()
        res = self.client.get(
            "/api/users/import/template",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data["code"], "INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()
