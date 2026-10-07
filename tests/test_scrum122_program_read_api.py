"""
Bộ kiểm thử SCRUM-122 (Activity A2): API xem danh sách và chi tiết chương trình đào tạo.

Mục tiêu kiểm thử:
1. Xác thực Authentication (401 khi không có token, token rác, thiếu session)
2. Phân quyền RBAC (403 khi thiếu quyền 'course.view', 200 khi có quyền)
3. GET /api/v1/training-programs (danh sách có phân trang, lọc status, tìm kiếm search)
4. GET /api/v1/training-programs (danh sách rỗng)
5. Validation query parameters: page < 1 -> 400, page_size > 100 -> 400, status sai -> 400
6. GET /api/v1/training-programs/<id> (thành công -> 200 kèm đầy đủ các trường)
7. GET /api/v1/training-programs/<id> (không tồn tại -> 404, ID không hợp lệ -> 400)
8. Xử lý lỗi cơ sở dữ liệu (500 không rò rỉ stack trace)
9. Kiểm thử tích hợp trực tiếp với MySQL thực tế (tạo dữ liệu, gọi API, xác minh, dọn dẹp)
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.training_program import (
    PROGRAM_STATUS_ACTIVE,
    PROGRAM_STATUS_ARCHIVED,
    PROGRAM_STATUS_DRAFT,
    TrainingProgram,
)
from app.repositories import training_program_repository
from app.routes.training_program_routes import training_program_bp


class Scrum122ProgramReadApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API xem danh sách và chi tiết chương trình đào tạo."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a2-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Session người dùng có quyền (Trainer/Admin có 'course.view')
        self.authorized_user_id = "user-auth-course-view"
        self.authorized_session = LoginSession(
            session_id="session-authorized-122",
            user_id=self.authorized_user_id,
            refresh_jti="ref-auth-122",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Session người dùng thông thường KHÔNG có quyền 'course.view'
        self.forbidden_user_id = "user-no-course-view"
        self.forbidden_session = LoginSession(
            session_id="session-forbidden-122",
            user_id=self.forbidden_user_id,
            refresh_jti="ref-forbid-122",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.authorized_token = create_access_token(
                identity=self.authorized_user_id,
                additional_claims={"sid": "session-authorized-122"},
            )
            self.forbidden_token = create_access_token(
                identity=self.forbidden_user_id,
                additional_claims={"sid": "session-forbidden-122"},
            )

        self.auth_headers = {"Authorization": f"Bearer {self.authorized_token}"}
        self.forbidden_headers = {"Authorization": f"Bearer {self.forbidden_token}"}

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (401 & 403)
    # =========================================================================

    def test_01_list_unauthenticated_returns_401(self):
        res = self.client.get("/api/v1/training-programs")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    def test_02_detail_unauthenticated_returns_401(self):
        res = self.client.get("/api/v1/training-programs/prog-123")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_list_forbidden_without_course_view_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.forbidden_session
        mock_has_perm.return_value = False  # Không có course.view

        res = self.client.get("/api/v1/training-programs", headers=self.forbidden_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")
        mock_has_perm.assert_called_with(self.forbidden_user_id, "course.view")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_detail_forbidden_without_course_view_returns_403(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.forbidden_session
        mock_has_perm.return_value = False

        res = self.client.get("/api/v1/training-programs/prog-123", headers=self.forbidden_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")

    # =========================================================================
    # 2. LIST API (GET /api/v1/training-programs)
    # =========================================================================

    @patch("app.repositories.training_program_repository.count_training_programs")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_list_success_with_items_and_pagination(
        self, mock_get_session, mock_has_perm, mock_get_all, mock_count
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        mock_get_all.return_value = [
            TrainingProgram(
                id="prog-01",
                code="CNTT-2026",
                name="Công nghệ Thông tin",
                description="Mô tả ngành CNTT",
                duration_semesters=8,
                status=PROGRAM_STATUS_ACTIVE,
                created_at=self.now,
                updated_at=self.now,
            ),
            TrainingProgram(
                id="prog-02",
                code="KTPM-2026",
                name="Kỹ thuật Phần mềm",
                description="Mô tả ngành KTPM",
                duration_semesters=9,
                status=PROGRAM_STATUS_DRAFT,
                created_at=self.now,
                updated_at=self.now,
            ),
        ]
        mock_count.return_value = 2

        res = self.client.get("/api/v1/training-programs?page=1&page_size=10", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

        body = data.get("data", {})
        self.assertEqual(body.get("total"), 2)
        self.assertEqual(body.get("page"), 1)
        self.assertEqual(body.get("page_size"), 10)
        self.assertEqual(body.get("total_pages"), 1)

        items = body.get("items", [])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], "prog-01")
        self.assertEqual(items[0]["code"], "CNTT-2026")
        self.assertEqual(items[0]["duration_semesters"], 8)
        self.assertEqual(items[0]["status"], "active")
        self.assertIn("created_at", items[0])
        self.assertIn("updated_at", items[0])

    @patch("app.repositories.training_program_repository.count_training_programs")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_list_empty_returns_empty_items_200(
        self, mock_get_session, mock_has_perm, mock_get_all, mock_count
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/training-programs", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        body = data.get("data", {})
        self.assertEqual(body.get("items"), [])
        self.assertEqual(body.get("total"), 0)
        self.assertEqual(body.get("total_pages"), 0)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_list_validation_invalid_page(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/training-programs?page=0", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

        res_negative = self.client.get("/api/v1/training-programs?page=-5", headers=self.auth_headers)
        self.assertEqual(res_negative.status_code, 400)

        res_abc = self.client.get("/api/v1/training-programs?page=abc", headers=self.auth_headers)
        self.assertEqual(res_abc.status_code, 400)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_list_validation_invalid_page_size(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        # page_size > 100 bị chặn
        res_large = self.client.get("/api/v1/training-programs?page_size=101", headers=self.auth_headers)
        self.assertEqual(res_large.status_code, 400)

        # page_size < 1 bị chặn
        res_zero = self.client.get("/api/v1/training-programs?page_size=0", headers=self.auth_headers)
        self.assertEqual(res_zero.status_code, 400)

    @patch("app.repositories.training_program_repository.count_training_programs")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_09_list_filter_status_valid_and_invalid(
        self, mock_get_session, mock_has_perm, mock_get_all, mock_count
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        # status hợp lệ
        res_valid = self.client.get("/api/v1/training-programs?status=active", headers=self.auth_headers)
        self.assertEqual(res_valid.status_code, 200)
        mock_get_all.assert_called_with(status="active", search=None, limit=20, offset=0)

        # status không hợp lệ
        res_invalid = self.client.get("/api/v1/training-programs?status=deleted", headers=self.auth_headers)
        self.assertEqual(res_invalid.status_code, 400)
        self.assertEqual(res_invalid.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.repositories.training_program_repository.count_training_programs")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_10_list_search_parameter(
        self, mock_get_session, mock_has_perm, mock_get_all, mock_count
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/training-programs?search=CNTT", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        mock_get_all.assert_called_with(status=None, search="CNTT", limit=20, offset=0)

    # =========================================================================
    # 3. DETAIL API (GET /api/v1/training-programs/<id>)
    # =========================================================================

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_11_detail_success_returns_all_fields(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        mock_get_by_id.return_value = TrainingProgram(
            id="prog-uuid-detail",
            code="AI-ICTU",
            name="Trí tuệ nhân tạo ICTU",
            description="Chương trình đào tạo AI chuyên sâu",
            duration_semesters=9,
            status=PROGRAM_STATUS_ACTIVE,
            created_at=self.now,
            updated_at=self.now,
        )

        res = self.client.get("/api/v1/training-programs/prog-uuid-detail", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

        item = data.get("data", {})
        self.assertEqual(item["id"], "prog-uuid-detail")
        self.assertEqual(item["code"], "AI-ICTU")
        self.assertEqual(item["name"], "Trí tuệ nhân tạo ICTU")
        self.assertEqual(item["description"], "Chương trình đào tạo AI chuyên sâu")
        self.assertEqual(item["duration_semesters"], 9)
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["created_at"], self.now.isoformat())
        self.assertEqual(item["updated_at"], self.now.isoformat())

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_12_detail_not_found_returns_404(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = None

        res = self.client.get("/api/v1/training-programs/non-existent-id", headers=self.auth_headers)
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("code"), "PROGRAM_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_13_detail_invalid_id_returns_400(self, mock_get_session, mock_has_perm):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/training-programs/%20", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("code"), "INVALID_PARAMS")

    # =========================================================================
    # 4. ERROR HANDLING (500 DATABASE ERROR)
    # =========================================================================

    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_list_database_error_returns_500(
        self, mock_get_session, mock_has_perm, mock_get_all
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.side_effect = MySQLError("Database connection dropped")

        res = self.client.get("/api/v1/training-programs", headers=self.auth_headers)
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data.get("code"), "DATABASE_ERROR")
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_15_detail_database_error_returns_500(
        self, mock_get_session, mock_has_perm, mock_get_by_id
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_by_id.side_effect = MySQLError("Disk read error")

        res = self.client.get("/api/v1/training-programs/prog-123", headers=self.auth_headers)
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data.get("code"), "DATABASE_ERROR")

    # =========================================================================
    # 5. ROUTE ALIASING (/api/training-programs và /api/v1/training-programs)
    # =========================================================================

    @patch("app.repositories.training_program_repository.count_training_programs")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_16_both_v1_and_unprefixed_endpoints_work(
        self, mock_get_session, mock_has_perm, mock_get_all, mock_count
    ):
        mock_get_session.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res_v1 = self.client.get("/api/v1/training-programs", headers=self.auth_headers)
        res_legacy = self.client.get("/api/training-programs", headers=self.auth_headers)

        self.assertEqual(res_v1.status_code, 200)
        self.assertEqual(res_legacy.status_code, 200)


class Scrum122ProgramReadApiIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp endpoint với MySQL Database thực tế."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum122-a2-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(training_program_bp)
        self.client = self.app.test_client()

        # Chuẩn bị 1 bản ghi test có ID và CODE ngẫu nhiên
        self.test_id = str(uuid.uuid4())
        self.test_code = f"LIVE-{uuid.uuid4().hex[:8].upper()}"

        program = TrainingProgram(
            id=self.test_id,
            code=self.test_code,
            name="Chương trình Live Test MySQL",
            description="Kiểm thử tích hợp đọc dữ liệu thật",
            duration_semesters=8,
            status=PROGRAM_STATUS_ACTIVE,
        )
        training_program_repository.insert_training_program(program)

        self.now = datetime.now(timezone.utc)
        self.user_id = f"user-{uuid.uuid4().hex[:8]}"
        self.session = LoginSession(
            session_id=f"session-{uuid.uuid4().hex[:8]}",
            user_id=self.user_id,
            refresh_jti="ref-live",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.token = create_access_token(
                identity=self.user_id,
                additional_claims={"sid": self.session.session_id},
            )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        # Dọn dẹp dữ liệu test ngay sau khi chạy xong
        training_program_repository.delete_training_program(self.test_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_17_real_mysql_integration_list_and_detail(
        self, mock_get_session, mock_has_perm
    ):
        mock_get_session.return_value = self.session
        mock_has_perm.return_value = True

        # 1. Test GET danh sách tìm theo search
        res_list = self.client.get(
            f"/api/v1/training-programs?search={self.test_code}",
            headers=self.headers,
        )
        self.assertEqual(res_list.status_code, 200)
        list_data = res_list.get_json()
        self.assertEqual(list_data["status"], "success")
        self.assertEqual(list_data["data"]["total"], 1)
        self.assertEqual(list_data["data"]["items"][0]["id"], self.test_id)
        self.assertEqual(list_data["data"]["items"][0]["code"], self.test_code)

        # 2. Test GET chi tiết
        res_detail = self.client.get(
            f"/api/v1/training-programs/{self.test_id}",
            headers=self.headers,
        )
        self.assertEqual(res_detail.status_code, 200)
        detail_data = res_detail.get_json()
        self.assertEqual(detail_data["status"], "success")
        self.assertEqual(detail_data["data"]["id"], self.test_id)
        self.assertEqual(detail_data["data"]["code"], self.test_code)
        self.assertEqual(detail_data["data"]["duration_semesters"], 8)
        self.assertEqual(detail_data["data"]["status"], "active")
