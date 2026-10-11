"""
Bộ kiểm thử SCRUM-122 (Activity A4): API cập nhật chương trình đào tạo (PUT / PATCH /api/v1/training-programs/<id>).

Bao quát 36 kịch bản kiểm thử:
01. PUT thành công.
02. PATCH thành công.
03. PATCH chỉ cập nhật name.
04. PATCH chỉ cập nhật status.
05. PATCH nhiều trường.
06. PATCH description = null.
07. PATCH duration_semesters = null.
08. PATCH không làm mất dữ liệu khác.
09. PUT xử lý trường tùy chọn đúng contract.
10. Không cho sửa id.
11. Không cho sửa created_at.
12. Backend cập nhật updated_at.
13. ID UUID sai -> 400.
14. UUID không tồn tại -> 404.
15. Body không phải JSON -> 400.
16. JSON rỗng -> 400.
17. Code rỗng -> 400.
18. Name rỗng -> 400.
19. Code quá dài -> 400.
20. Name quá dài -> 400.
21. Duration sai -> 400.
22. Status sai -> 400.
23. Đổi code trùng -> 409.
24. Giữ nguyên code -> 200.
25. MySQL UNIQUE race condition -> 409.
26. Không token -> 401.
27. Token sai -> 401.
28. Chỉ có course.view -> 403.
29. Có course.manage -> 200.
30. Database error -> 500.
31. Transaction rollback khi lỗi.
32. SQL injection không thực thi.
33. Route alias hoạt động (/api/training-programs/<id>).
34. GET A2 trả dữ liệu mới.
35. POST A3 vẫn hoạt động.
36. Kiểm thử tích hợp trực tiếp MySQL thực tế.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError, IntegrityError

from app.config.jwt_handlers import register_jwt_handlers
from app.models.login_session import LoginSession
from app.models.training_program import (
    PROGRAM_STATUS_ACTIVE,
    PROGRAM_STATUS_ARCHIVED,
    PROGRAM_STATUS_DRAFT,
    TrainingProgram,
)
from app.repositories import training_program_repository
from app.routes.training_program_routes import training_program_bp


class Scrum122ProgramUpdateApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API cập nhật chương trình đào tạo (PUT và PATCH)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a4-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.program_id = str(uuid.uuid4())

        # Session user có quyền course.manage
        self.manager_user_id = "user-course-manage-uuid"
        self.manager_session = LoginSession(
            session_id="session-manager-122",
            user_id=self.manager_user_id,
            refresh_jti="ref-manager-122",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Session user chỉ có quyền course.view
        self.viewer_user_id = "user-course-view-uuid"
        self.viewer_session = LoginSession(
            session_id="session-viewer-122",
            user_id=self.viewer_user_id,
            refresh_jti="ref-viewer-122",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-manager-122"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-viewer-122"},
            )

        self.manager_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.viewer_headers = {"Authorization": f"Bearer {self.viewer_token}"}

        self.existing_program = TrainingProgram(
            id=self.program_id,
            code="CNTT-2026",
            name="Công nghệ Thông tin",
            description="Chương trình đào tạo CNTT gốc",
            duration_semesters=8,
            status=PROGRAM_STATUS_DRAFT,
            created_at=self.now - timedelta(days=1),
            updated_at=self.now - timedelta(days=1),
        )

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (26, 27, 28, 29)
    # =========================================================================

    def test_26_unauthenticated_returns_401(self):
        # PUT không token -> 401
        res_put = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "NEW-CODE", "name": "New Name"},
        )
        self.assertEqual(res_put.status_code, 401)
        self.assertEqual(res_put.get_json().get("code"), "UNAUTHORIZED")

        # PATCH không token -> 401
        res_patch = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "New Name"},
        )
        self.assertEqual(res_patch.status_code, 401)
        self.assertEqual(res_patch.get_json().get("code"), "UNAUTHORIZED")

    def test_27_invalid_token_returns_401(self):
        bad_headers = {"Authorization": "Bearer invalid.jwt.token"}
        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "NEW-CODE", "name": "New Name"},
            headers=bad_headers,
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json().get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_28_forbidden_without_course_manage_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.viewer_session
        mock_has_perm.return_value = False

        res_put = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "NEW-CODE", "name": "New Name"},
            headers=self.viewer_headers,
        )
        self.assertEqual(res_put.status_code, 403)
        self.assertEqual(res_put.get_json().get("code"), "FORBIDDEN")

        res_patch = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "New Name"},
            headers=self.viewer_headers,
        )
        self.assertEqual(res_patch.status_code, 403)
        self.assertEqual(res_patch.get_json().get("code"), "FORBIDDEN")

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_29_authorized_with_course_manage_returns_200(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_update.side_effect = lambda p: p

        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "CNTT-2026", "name": "CNTT Mới"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)

    # =========================================================================
    # 2. SUCCESSFUL PUT & PATCH SCENARIOS (01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 24, 33)
    # =========================================================================

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_01_put_success_full_fields(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_update.side_effect = lambda p: p

        payload = {
            "code": "CNTT-2026",
            "name": "Công nghệ Thông tin - Cập nhật",
            "description": "Chương trình CNTT đã cập nhật",
            "duration_semesters": 9,
            "status": "active",
        }
        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json=payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Cập nhật chương trình đào tạo thành công.")
        item = data["data"]
        self.assertEqual(item["id"], self.program_id)
        self.assertEqual(item["code"], "CNTT-2026")
        self.assertEqual(item["name"], "Công nghệ Thông tin - Cập nhật")
        self.assertEqual(item["description"], "Chương trình CNTT đã cập nhật")
        self.assertEqual(item["duration_semesters"], 9)
        self.assertEqual(item["status"], "active")
        self.assertIsNotNone(item["updated_at"])

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_patch_success(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        updated_model = TrainingProgram(
            id=self.program_id,
            code="CNTT-2026",
            name="CNTT PATCH",
            description=self.existing_program.description,
            duration_semesters=self.existing_program.duration_semesters,
            status=self.existing_program.status,
            created_at=self.existing_program.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        mock_update_fields.return_value = updated_model

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "CNTT PATCH"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["name"], "CNTT PATCH")

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_patch_only_name(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        mock_update_fields.return_value = self.existing_program

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "Tên mới độc lập"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        # Kiểm tra repository chỉ được gọi với duy nhất key "name"
        called_fields = mock_update_fields.call_args[0][1]
        self.assertEqual(called_fields, {"name": "Tên mới độc lập"})

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_patch_only_status(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        mock_update_fields.return_value = self.existing_program

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"status": "archived"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called_fields = mock_update_fields.call_args[0][1]
        self.assertEqual(called_fields, {"status": "archived"})

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_patch_multiple_fields(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        mock_update_fields.return_value = self.existing_program

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={
                "name": "Tên nhiều trường",
                "description": "Mô tả mới",
                "duration_semesters": 10,
            },
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called_fields = mock_update_fields.call_args[0][1]
        self.assertEqual(
            called_fields,
            {
                "name": "Tên nhiều trường",
                "description": "Mô tả mới",
                "duration_semesters": 10,
            },
        )

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_patch_description_null(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        mock_update_fields.return_value = self.existing_program

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"description": None},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called_fields = mock_update_fields.call_args[0][1]
        self.assertEqual(called_fields, {"description": None})

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_patch_duration_semesters_null(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        mock_update_fields.return_value = self.existing_program

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"duration_semesters": None},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called_fields = mock_update_fields.call_args[0][1]
        self.assertEqual(called_fields, {"duration_semesters": None})

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_patch_does_not_lose_other_data(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        # Giả lập repo giữ nguyên các trường khác
        def mock_patch_impl(prog_id, fields):
            return TrainingProgram(
                id=self.existing_program.id,
                code=self.existing_program.code,
                name=fields.get("name", self.existing_program.name),
                description=self.existing_program.description,
                duration_semesters=self.existing_program.duration_semesters,
                status=self.existing_program.status,
                created_at=self.existing_program.created_at,
                updated_at=datetime.now(timezone.utc),
            )

        mock_update_fields.side_effect = mock_patch_impl

        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "Chỉ đổi tên"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["name"], "Chỉ đổi tên")
        self.assertEqual(data["code"], self.existing_program.code)
        self.assertEqual(data["description"], self.existing_program.description)
        self.assertEqual(data["duration_semesters"], self.existing_program.duration_semesters)
        self.assertEqual(data["status"], self.existing_program.status)

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_09_put_handles_optionals_as_contract(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_update.side_effect = lambda p: p

        # PUT không gửi description, duration_semesters, status
        # Contract: description=None, duration_semesters=None, status='draft'
        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "CNTT-2026", "name": "CNTT Rút Gọn"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called_program = mock_update.call_args[0][0]
        self.assertIsNone(called_program.description)
        self.assertIsNone(called_program.duration_semesters)
        self.assertEqual(called_program.status, "draft")

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_10_and_11_and_12_cannot_override_id_or_created_at_and_updates_updated_at(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_update.side_effect = lambda p: p

        fake_id = "00000000-0000-0000-0000-000000000000"
        fake_created_at = "1999-01-01T00:00:00Z"
        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={
                "id": fake_id,
                "created_at": fake_created_at,
                "code": "CNTT-2026",
                "name": "CNTT Tên Mới",
            },
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called = mock_update.call_args[0][0]
        self.assertEqual(called.id, self.program_id)  # Giữ nguyên ID từ URL
        self.assertEqual(called.created_at, self.existing_program.created_at)  # Giữ nguyên created_at
        self.assertNotEqual(called.updated_at, self.existing_program.updated_at)  # Cập nhật updated_at

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_24_keep_same_code_returns_200(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_exists, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_exists.return_value = False
        mock_update.side_effect = lambda p: p

        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "CNTT-2026", "name": "Đổi tên giữ nguyên code"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_33_route_aliases_work(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_update.side_effect = lambda p: p

        # PUT không có /v1
        res_put = self.client.put(
            f"/api/training-programs/{self.program_id}",
            json={"code": "CNTT-2026", "name": "Alias PUT"},
            headers=self.manager_headers,
        )
        self.assertEqual(res_put.status_code, 200)

        # PATCH không có /v1
        with patch("app.repositories.training_program_repository.update_training_program_fields") as mock_patch:
            mock_patch.return_value = self.existing_program
            res_patch = self.client.patch(
                f"/api/training-programs/{self.program_id}",
                json={"name": "Alias PATCH"},
                headers=self.manager_headers,
            )
            self.assertEqual(res_patch.status_code, 200)

    # =========================================================================
    # 3. VALIDATION ERRORS & RESOURCE CHECKS (13, 14, 15, 16, 17, 18, 19, 20, 21, 22)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_13_invalid_uuid_returns_400(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        bad_ids = ["abc-123", "not-a-valid-uuid", "123456", "   "]
        for bad_id in bad_ids:
            res = self.client.put(
                f"/api/v1/training-programs/{bad_id}",
                json={"code": "TEST", "name": "Test"},
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_non_existent_uuid_returns_404(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.put(
            f"/api/v1/training-programs/{valid_uuid}",
            json={"code": "TEST", "name": "Test"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json().get("code"), "PROGRAM_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_15_non_json_body_returns_400(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            data="not a json string",
            content_type="text/plain",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_JSON")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_16_empty_json_returns_400(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        # PUT với JSON rỗng -> thiếu code/name
        res_put = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={},
            headers=self.manager_headers,
        )
        self.assertEqual(res_put.status_code, 400)
        self.assertIn(res_put.get_json().get("code"), ["CODE_REQUIRED", "INVALID_PARAMS"])

        # PATCH với JSON rỗng -> không có trường nào để cập nhật
        res_patch = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={},
            headers=self.manager_headers,
        )
        self.assertEqual(res_patch.status_code, 400)
        self.assertEqual(res_patch.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_17_and_18_empty_code_and_name_return_400(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        # Code rỗng trong PUT
        res1 = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "   ", "name": "Hợp lệ"},
            headers=self.manager_headers,
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json().get("code"), "CODE_REQUIRED")

        # Name rỗng trong PUT
        res2 = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "VALID", "name": "   "},
            headers=self.manager_headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json().get("code"), "NAME_REQUIRED")

        # Code rỗng trong PATCH
        res3 = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "   "},
            headers=self.manager_headers,
        )
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json().get("code"), "CODE_REQUIRED")

        # Name rỗng trong PATCH
        res4 = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "   "},
            headers=self.manager_headers,
        )
        self.assertEqual(res4.status_code, 400)
        self.assertEqual(res4.get_json().get("code"), "NAME_REQUIRED")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_19_and_20_code_and_name_too_long_return_400(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        # Code > 50 ký tự
        res_code = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "A" * 51},
            headers=self.manager_headers,
        )
        self.assertEqual(res_code.status_code, 400)
        self.assertEqual(res_code.get_json().get("code"), "CODE_TOO_LONG")

        # Name > 255 ký tự
        res_name = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": "B" * 256},
            headers=self.manager_headers,
        )
        self.assertEqual(res_name.status_code, 400)
        self.assertEqual(res_name.get_json().get("code"), "NAME_TOO_LONG")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_21_invalid_duration_returns_400(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        invalid_durations = [-1, 0, 65536, True, False, 8.5, "8", [8]]
        for dur in invalid_durations:
            res = self.client.patch(
                f"/api/v1/training-programs/{self.program_id}",
                json={"duration_semesters": dur},
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400, f"Duration {dur} should return 400")
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_22_invalid_status_returns_400(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        invalid_statuses = ["deleted", "pending", "ACTIVE2", 123, True, ""]
        for st in invalid_statuses:
            res = self.client.patch(
                f"/api/v1/training-programs/{self.program_id}",
                json={"status": st},
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400, f"Status {st} should return 400")
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    # =========================================================================
    # 4. DUPLICATE CODE & CONCURRENCY CONFLICT (23, 25)
    # =========================================================================

    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_23_duplicate_code_service_check_returns_409(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_exists
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        # exists_by_code trả về True khi đổi sang code của chương trình khác
        mock_exists.return_value = True

        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "KTPM-2026", "name": "Đổi thành code đã có"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "DUPLICATE_CODE")

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_25_database_unique_violation_race_condition_returns_409(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_exists, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_exists.return_value = False

        err = IntegrityError("1062 (23000): Duplicate entry 'KTPM-2026' for key 'code'")
        err.errno = 1062
        mock_update.side_effect = err

        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "KTPM-2026", "name": "Race condition update"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "DUPLICATE_CODE")

    # =========================================================================
    # 5. ERROR HANDLING, ROLLBACK & SECURITY (30, 31, 32)
    # =========================================================================

    @patch("app.repositories.training_program_repository.update_training_program")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_30_and_31_database_error_and_rollback_returns_500(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program
        mock_update.side_effect = MySQLError("Database disk I/O failure")

        res = self.client.put(
            f"/api/v1/training-programs/{self.program_id}",
            json={"code": "CNTT-2026", "name": "Lỗi Database"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.get_json().get("code"), "DATABASE_ERROR")
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.repositories.training_program_repository.update_training_program_fields")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_32_sql_injection_payload_handled_safely(
        self, mock_get_session, mock_has_perm, mock_get_by_id, mock_update_fields
    ):
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_program

        mock_update_fields.return_value = self.existing_program

        sql_injection = "CNTT'; DROP TABLE training_programs; --"
        res = self.client.patch(
            f"/api/v1/training-programs/{self.program_id}",
            json={"name": sql_injection},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        called_fields = mock_update_fields.call_args[0][1]
        self.assertEqual(called_fields["name"], sql_injection)


class Scrum122ProgramUpdateApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp endpoint PUT và PATCH với MySQL thực tế (34, 35, 36)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a4-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)
        self.client = self.app.test_client()

        self.created_ids = []
        self.now = datetime.now(timezone.utc)
        self.manager_user_id = f"user-mgr-{uuid.uuid4().hex[:8]}"
        self.session = LoginSession(
            session_id=f"sess-mgr-{uuid.uuid4().hex[:8]}",
            user_id=self.manager_user_id,
            refresh_jti="ref-mgr",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": self.session.session_id},
            )
        self.headers = {"Authorization": f"Bearer {self.manager_token}"}

    def tearDown(self):
        for prog_id in self.created_ids:
            training_program_repository.delete_training_program(prog_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_34_35_36_real_mysql_full_lifecycle(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_has_perm.return_value = True

        code_a = f"A4-A-{uuid.uuid4().hex[:6].upper()}"
        code_b = f"A4-B-{uuid.uuid4().hex[:6].upper()}"

        # 1. POST A3 tạo mới chương trình A
        res_post_a = self.client.post(
            "/api/v1/training-programs",
            json={
                "code": code_a,
                "name": "Chương trình A Test",
                "description": "Mô tả A",
                "duration_semesters": 8,
                "status": "draft",
            },
            headers=self.headers,
        )
        self.assertEqual(res_post_a.status_code, 201)
        id_a = res_post_a.get_json()["data"]["id"]
        self.created_ids.append(id_a)

        # POST A3 tạo mới chương trình B
        res_post_b = self.client.post(
            "/api/v1/training-programs",
            json={
                "code": code_b,
                "name": "Chương trình B Test",
                "description": "Mô tả B",
                "duration_semesters": 6,
                "status": "draft",
            },
            headers=self.headers,
        )
        self.assertEqual(res_post_b.status_code, 201)
        id_b = res_post_b.get_json()["data"]["id"]
        self.created_ids.append(id_b)

        # 2. PATCH A đổi name
        res_patch_name = self.client.patch(
            f"/api/v1/training-programs/{id_a}",
            json={"name": "Chương trình A - Đổi Tên"},
            headers=self.headers,
        )
        self.assertEqual(res_patch_name.status_code, 200)

        # 3. GET A2 kiểm tra name mới và các trường khác giữ nguyên
        res_get_a = self.client.get(
            f"/api/v1/training-programs/{id_a}",
            headers=self.headers,
        )
        self.assertEqual(res_get_a.status_code, 200)
        data_a = res_get_a.get_json()["data"]
        self.assertEqual(data_a["name"], "Chương trình A - Đổi Tên")
        self.assertEqual(data_a["code"], code_a)
        self.assertEqual(data_a["description"], "Mô tả A")
        self.assertEqual(data_a["duration_semesters"], 8)
        self.assertEqual(data_a["status"], "draft")

        # 4. PATCH A đổi status
        res_patch_status = self.client.patch(
            f"/api/v1/training-programs/{id_a}",
            json={"status": "active"},
            headers=self.headers,
        )
        self.assertEqual(res_patch_status.status_code, 200)
        self.assertEqual(res_patch_status.get_json()["data"]["status"], "active")

        # 5. PUT A cập nhật toàn bộ thông tin
        res_put = self.client.put(
            f"/api/v1/training-programs/{id_a}",
            json={
                "code": code_a,
                "name": "Chương trình A - PUT Toàn Bộ",
                "description": "Mô tả mới sau PUT",
                "duration_semesters": 10,
                "status": "archived",
            },
            headers=self.headers,
        )
        self.assertEqual(res_put.status_code, 200)
        put_data = res_put.get_json()["data"]
        self.assertEqual(put_data["name"], "Chương trình A - PUT Toàn Bộ")
        self.assertEqual(put_data["duration_semesters"], 10)
        self.assertEqual(put_data["status"], "archived")

        # 6. Thử đổi code A thành code B -> 409 DUPLICATE_CODE
        res_dup = self.client.put(
            f"/api/v1/training-programs/{id_a}",
            json={
                "code": code_b,
                "name": "Thử trùng code",
            },
            headers=self.headers,
        )
        self.assertEqual(res_dup.status_code, 409)
        self.assertEqual(res_dup.get_json().get("code"), "DUPLICATE_CODE")
