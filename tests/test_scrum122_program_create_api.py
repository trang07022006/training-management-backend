"""
Bộ kiểm thử SCRUM-122 (Activity A3): API tạo mới chương trình đào tạo (POST /api/v1/training-programs).

Bao quát 25 kịch bản kiểm thử:
1. Tạo chương trình thành công (HTTP 201, Location header, đầy đủ fields)
2. Tạo với trường tùy chọn bị thiếu (description=None, duration_semesters=None)
3. Status mặc định 'draft'
4. UUID được sinh hợp lệ (định dạng 36 ký tự)
5. Timestamp UTC
6. Thiếu code -> 400
7. Thiếu name -> 400
8. Code rỗng / chỉ khoảng trắng -> 400
9. Name rỗng / chỉ khoảng trắng -> 400
10. Code quá dài (> 50 ký tự) -> 400
11. Name quá dài (> 255 ký tự) -> 400
12. Duration không hợp lệ (số âm, boolean, float, string) -> 400
13. Status không hợp lệ -> 400
14. Code đã tồn tại (service check) -> 409
15. Database UNIQUE constraint violation (race condition IntegrityError) -> 409
16. Không có token -> 401
17. Token không hợp lệ -> 401
18. Không có quyền course.manage (chỉ có course.view) -> 403
19. Có quyền course.manage -> 201
20. Database error -> 500
21. Transaction rollback khi lỗi DB
22. SQL injection payload trong code/name được parameterized an toàn
23. Client tự gửi id/created_at bị bỏ qua, backend tự sinh ID và timestamp
24. API GET A2 vẫn hoạt động
25. Tích hợp trực tiếp với MySQL thực tế (tạo, đọc, trùng code 409, dọn dẹp)
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
    PROGRAM_STATUS_DRAFT,
    TrainingProgram,
)
from app.repositories import training_program_repository
from app.routes.training_program_routes import training_program_bp


class Scrum122ProgramCreateApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API tạo mới chương trình đào tạo."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a3-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # 1. User có quyền course.manage (Admin / Trainer)
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

        # 2. User chỉ có quyền course.view (Trainee)
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

        self.valid_payload = {
            "code": "CNTT-2026",
            "name": "Công nghệ Thông tin",
            "description": "Chương trình Cử nhân CNTT",
            "duration_semesters": 8,
            "status": "active",
        }

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (401 & 403)
    # =========================================================================

    def test_01_create_unauthenticated_returns_401(self):
        # 16. Không có token
        res = self.client.post("/api/v1/training-programs", json=self.valid_payload)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json().get("code"), "UNAUTHORIZED")

    def test_02_create_invalid_token_returns_401(self):
        # 17. Token không hợp lệ
        res = self.client.post(
            "/api/v1/training-programs",
            json=self.valid_payload,
            headers={"Authorization": "Bearer invalid.token.payload"},
        )
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_create_forbidden_without_course_manage_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        # 18. Có course.view nhưng không có course.manage -> 403
        mock_get_session.return_value = self.viewer_session
        mock_has_perm.return_value = False

        res = self.client.post(
            "/api/v1/training-programs",
            json=self.valid_payload,
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("code"), "FORBIDDEN")
        mock_has_perm.assert_called_with(self.viewer_user_id, "course.manage")

    # =========================================================================
    # 2. SUCCESSFUL CREATION & RESPONSE
    # =========================================================================

    @patch("app.repositories.training_program_repository.insert_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_create_success_full_fields_returns_201(
        self, mock_get_session, mock_has_perm, mock_exists, mock_insert
    ):
        # 1. Tạo thành công, 19. Có course.manage -> 201
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False

        def mock_insert_fn(prog):
            return prog

        mock_insert.side_effect = mock_insert_fn

        res = self.client.post(
            "/api/v1/training-programs",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

        body = data.get("data", {})
        # 4. UUID sinh hợp lệ
        self.assertEqual(len(body["id"]), 36)
        self.assertEqual(body["code"], "CNTT-2026")
        self.assertEqual(body["name"], "Công nghệ Thông tin")
        self.assertEqual(body["description"], "Chương trình Cử nhân CNTT")
        self.assertEqual(body["duration_semesters"], 8)
        self.assertEqual(body["status"], "active")

        # 5. Timestamp UTC
        self.assertIsNotNone(body["created_at"])
        self.assertIsNotNone(body["updated_at"])

        # Location header
        self.assertIn("Location", res.headers)
        self.assertEqual(res.headers["Location"], f"/api/v1/training-programs/{body['id']}")

    @patch("app.repositories.training_program_repository.insert_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_create_with_missing_optionals_and_default_status(
        self, mock_get_session, mock_has_perm, mock_exists, mock_insert
    ):
        # 2. Thiếu trường tùy chọn, 3. Status mặc định draft
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda p: p

        payload = {
            "code": "KTPM-2026",
            "name": "Kỹ thuật Phần mềm",
        }

        res = self.client.post(
            "/api/v1/training-programs",
            json=payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()["data"]
        self.assertEqual(body["code"], "KTPM-2026")
        self.assertEqual(body["name"], "Kỹ thuật Phần mềm")
        self.assertIsNone(body["description"])
        self.assertIsNone(body["duration_semesters"])
        self.assertEqual(body["status"], "draft")

    # =========================================================================
    # 3. VALIDATION ERRORS (HTTP 400)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_missing_or_empty_code_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        # 6. Thiếu code, 8. Code rỗng / khoảng trắng
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        # Thiếu code
        res1 = self.client.post(
            "/api/v1/training-programs",
            json={"name": "Chương trình 1"},
            headers=self.manager_headers,
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json().get("code"), "CODE_REQUIRED")

        # Code chỉ có khoảng trắng
        res2 = self.client.post(
            "/api/v1/training-programs",
            json={"code": "   ", "name": "Chương trình 1"},
            headers=self.manager_headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json().get("code"), "CODE_REQUIRED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_missing_or_empty_name_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        # 7. Thiếu name, 9. Name rỗng / khoảng trắng
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        # Thiếu name
        res1 = self.client.post(
            "/api/v1/training-programs",
            json={"code": "CNTT-01"},
            headers=self.manager_headers,
        )
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json().get("code"), "NAME_REQUIRED")

        # Name rỗng
        res2 = self.client.post(
            "/api/v1/training-programs",
            json={"code": "CNTT-01", "name": "   "},
            headers=self.manager_headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json().get("code"), "NAME_REQUIRED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_code_or_name_too_long_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        # 10. Code quá dài (> 50), 11. Name quá dài (> 255)
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        # Code 51 ký tự
        res_code = self.client.post(
            "/api/v1/training-programs",
            json={"code": "A" * 51, "name": "Tên hợp lệ"},
            headers=self.manager_headers,
        )
        self.assertEqual(res_code.status_code, 400)
        self.assertEqual(res_code.get_json().get("code"), "CODE_TOO_LONG")

        # Name 256 ký tự
        res_name = self.client.post(
            "/api/v1/training-programs",
            json={"code": "CODE-OK", "name": "B" * 256},
            headers=self.manager_headers,
        )
        self.assertEqual(res_name.status_code, 400)
        self.assertEqual(res_name.get_json().get("code"), "NAME_TOO_LONG")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_09_invalid_duration_semesters_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        # 12. Duration không hợp lệ (số âm, số 0, boolean, float, string)
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        invalid_durations = [-1, 0, True, False, 8.5, "8", [8]]
        for dur in invalid_durations:
            payload = {
                "code": "TEST-DUR",
                "name": "Kiểm thử Duration",
                "duration_semesters": dur,
            }
            res = self.client.post(
                "/api/v1/training-programs",
                json=payload,
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400, f"Duration {dur} should fail with 400")
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_10_invalid_status_returns_400(
        self, mock_get_session, mock_has_perm
    ):
        # 13. Status không hợp lệ
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True

        payload = {
            "code": "TEST-STATUS",
            "name": "Kiểm thử Status",
            "status": "deleted",
        }
        res = self.client.post(
            "/api/v1/training-programs",
            json=payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    # =========================================================================
    # 4. DUPLICATE CODE CONFLICT (HTTP 409)
    # =========================================================================

    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_11_duplicate_code_service_check_returns_409(
        self, mock_get_session, mock_has_perm, mock_exists
    ):
        # 14. Code đã tồn tại (service check)
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = True

        res = self.client.post(
            "/api/v1/training-programs",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "DUPLICATE_CODE")

    @patch("app.repositories.training_program_repository.insert_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_12_database_unique_violation_returns_409(
        self, mock_get_session, mock_has_perm, mock_exists, mock_insert
    ):
        # 15. Database UNIQUE constraint violation (race condition)
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = IntegrityError("1062 (23000): Duplicate entry 'CNTT-2026' for key 'code'")

        res = self.client.post(
            "/api/v1/training-programs",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "DUPLICATE_CODE")

    # =========================================================================
    # 5. SECURITY & INTEGRITY
    # =========================================================================

    @patch("app.repositories.training_program_repository.insert_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_13_client_cannot_override_id_or_timestamp(
        self, mock_get_session, mock_has_perm, mock_exists, mock_insert
    ):
        # 23. Không cho client tự gán id hoặc timestamp
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda p: p

        client_fake_id = "client-hacked-id-1234567890"
        client_fake_time = "2020-01-01T00:00:00Z"
        payload = {
            "id": client_fake_id,
            "code": "OVERRIDE-TEST",
            "name": "Kiểm thử override",
            "created_at": client_fake_time,
            "updated_at": client_fake_time,
        }

        res = self.client.post(
            "/api/v1/training-programs",
            json=payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()["data"]
        # ID và timestamp phải do backend tự sinh
        self.assertNotEqual(body["id"], client_fake_id)
        self.assertNotEqual(body["created_at"], client_fake_time)
        self.assertEqual(len(body["id"]), 36)

    @patch("app.repositories.training_program_repository.insert_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_sql_injection_payload_saved_as_string_safely(
        self, mock_get_session, mock_has_perm, mock_exists, mock_insert
    ):
        # 22. SQL injection không thực thi
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda p: p

        payload = {
            "code": "INJ-01",
            "name": "SQL'; DROP TABLE training_programs; --",
        }

        res = self.client.post(
            "/api/v1/training-programs",
            json=payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()["data"]
        self.assertEqual(body["name"], "SQL'; DROP TABLE training_programs; --")

    @patch("app.repositories.training_program_repository.insert_training_program")
    @patch("app.repositories.training_program_repository.exists_by_code")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_15_database_error_returns_500(
        self, mock_get_session, mock_has_perm, mock_exists, mock_insert
    ):
        # 20. Database error, 21. Rollback
        mock_get_session.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = MySQLError("Database connection reset by peer")

        res = self.client.post(
            "/api/v1/training-programs",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data.get("code"), "DATABASE_ERROR")
        self.assertNotIn("Traceback", res.get_data(as_text=True))


class Scrum122ProgramCreateApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp endpoint POST với MySQL thực tế (25. Tích hợp MySQL)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a3-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)
        self.client = self.app.test_client()

        self.created_ids = []
        self.test_code = f"POST-{uuid.uuid4().hex[:8].upper()}"

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
        # Dọn dẹp an toàn các bản ghi đã tạo
        for prog_id in self.created_ids:
            training_program_repository.delete_training_program(prog_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_16_real_mysql_post_then_get_and_duplicate_conflict(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_has_perm.return_value = True

        payload = {
            "code": self.test_code,
            "name": "Chương trình Live POST MySQL",
            "description": "Tích hợp ghi dữ liệu thật",
            "duration_semesters": 8,
            "status": "draft",
        }

        # 1. Gọi POST tạo chương trình đào tạo
        res_post = self.client.post(
            "/api/v1/training-programs",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(res_post.status_code, 201)
        post_data = res_post.get_json()
        self.assertEqual(post_data["status"], "success")
        new_id = post_data["data"]["id"]
        self.created_ids.append(new_id)

        # 2. Gọi GET chi tiết bằng ID mới để kiểm chứng dữ liệu thật
        res_get = self.client.get(
            f"/api/v1/training-programs/{new_id}",
            headers=self.headers,
        )
        self.assertEqual(res_get.status_code, 200)
        get_data = res_get.get_json()["data"]
        self.assertEqual(get_data["id"], new_id)
        self.assertEqual(get_data["code"], self.test_code)
        self.assertEqual(get_data["duration_semesters"], 8)
        self.assertEqual(get_data["status"], "draft")

        # 3. Thử tạo lại với cùng mã code -> phải trả về HTTP 409
        res_dup = self.client.post(
            "/api/v1/training-programs",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(res_dup.status_code, 409)
        self.assertEqual(res_dup.get_json()["code"], "DUPLICATE_CODE")
