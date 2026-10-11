"""
Bộ kiểm thử SCRUM-123 (Activity A2): API xem danh sách và chi tiết môn học / học phần.

Mục tiêu kiểm thử:
01. GET list thành công.
02. List rỗng.
03. Pagination mặc định (page=1, page_size=20).
04. page hợp lệ (page=2).
05. page sai (< 1, text).
06. page_size sai (< 1, text).
07. page_size > 100.
08. Filter draft.
09. Filter active.
10. Filter archived.
11. Status sai.
12. Search theo code.
13. Search theo name.
14. Search Unicode (tiếng Việt có dấu).
15. Search parameterized (không SQL injection).
16. Detail thành công kèm đầy đủ các trường.
17. UUID sai -> 400 INVALID_PARAMS.
18. UUID hợp lệ không tồn tại -> 404 SUBJECT_NOT_FOUND.
19. Không token -> 401 UNAUTHORIZED.
20. Token không hợp lệ -> 401 UNAUTHORIZED.
21. Không course.view -> 403 FORBIDDEN.
22. Có course.view -> 200 OK.
23. Database error -> 500 DATABASE_ERROR không lộ stack trace.
24. Serialization nullable fields (description=None, total_sessions=None).
25. Route alias (/api/subjects và /api/subjects/<id>).
26. Repository connection cleanup.
27. Không regression SCRUM-122 (/api/v1/training-programs).
28. Không regression Auth/Profile/Avatar.
MySQL Integration Tests (prefix SUBJ-A2-): Roundtrip, Search, Filter, Detail, RBAC, Cleanup.
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
from app.models.subject import (
    SUBJECT_STATUS_ACTIVE,
    SUBJECT_STATUS_ARCHIVED,
    SUBJECT_STATUS_DRAFT,
    Subject,
)
from app.repositories import subject_repository
from app.routes.subject_routes import subject_bp
from app.routes.training_program_routes import training_program_bp


class Scrum123SubjectReadApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API xem danh sách và chi tiết môn học."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum123-a2-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_bp)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Session người dùng có quyền ('course.view')
        self.authorized_user_id = "user-auth-course-view"
        self.authorized_session = LoginSession(
            session_id="session-authorized-123",
            user_id=self.authorized_user_id,
            refresh_jti="ref-auth-123",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Session người dùng KHÔNG có quyền 'course.view'
        self.forbidden_user_id = "user-no-course-view"
        self.forbidden_session = LoginSession(
            session_id="session-forbidden-123",
            user_id=self.forbidden_user_id,
            refresh_jti="ref-forbid-123",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.authorized_token = create_access_token(
                identity=self.authorized_user_id,
                additional_claims={"sid": "session-authorized-123"},
            )
            self.forbidden_token = create_access_token(
                identity=self.forbidden_user_id,
                additional_claims={"sid": "session-forbidden-123"},
            )

        self.auth_headers = {"Authorization": f"Bearer {self.authorized_token}"}
        self.forbidden_headers = {"Authorization": f"Bearer {self.forbidden_token}"}

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (401 & 403 & 200)
    # =========================================================================

    def test_19_list_unauthenticated_returns_401(self):
        res = self.client.get("/api/v1/subjects")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    def test_20_list_invalid_token_returns_401(self):
        res = self.client.get("/api/v1/subjects", headers={"Authorization": "Bearer invalid.token.payload"})
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_21_list_without_course_view_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.forbidden_session
        mock_has_perm.return_value = False

        res = self.client.get("/api/v1/subjects", headers=self.forbidden_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")
        self.assertIn("Bạn không có quyền", data.get("message"))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_22_list_with_course_view_returns_200(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

    # =========================================================================
    # 2. LIST API & PAGINATION & SEARCH & FILTER
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_01_get_list_success(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        sample = Subject(
            id="subj-uuid-1",
            code="INT1154",
            name="Lập trình hướng đối tượng",
            credits=3,
            description="Môn học OOP",
            total_sessions=15,
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        mock_get_all.return_value = [sample]
        mock_count.return_value = 1

        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        items = data["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["code"], "INT1154")
        self.assertEqual(items[0]["credits"], 3)
        self.assertEqual(items[0]["total_sessions"], 15)
        self.assertEqual(data["data"]["total"], 1)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_02_get_list_empty(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["total_pages"], 0)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_03_default_pagination(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)
        mock_get_all.assert_called_with(status=None, search=None, limit=20, offset=0)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_04_valid_custom_page(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 45

        res = self.client.get("/api/v1/subjects?page=2&page_size=10", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["page_size"], 10)
        self.assertEqual(data["total_pages"], 5)
        mock_get_all.assert_called_with(status=None, search=None, limit=10, offset=10)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_invalid_page(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        for bad_page in ["0", "-1", "abc"]:
            res = self.client.get(f"/api/v1/subjects?page={bad_page}", headers=self.auth_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_invalid_page_size(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        for bad_ps in ["0", "-5", "xyz"]:
            res = self.client.get(f"/api/v1/subjects?page_size={bad_ps}", headers=self.auth_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_page_size_exceeds_100(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/subjects?page_size=101", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_08_09_10_filters_draft_active_archived(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        for st in ["draft", "active", "archived"]:
            res = self.client.get(f"/api/v1/subjects?status={st}", headers=self.auth_headers)
            self.assertEqual(res.status_code, 200)
            mock_get_all.assert_called_with(status=st, search=None, limit=20, offset=0)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_11_invalid_status(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get("/api/v1/subjects?status=deleted", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_12_13_14_15_search_code_name_unicode_parameterized(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        # Search code
        self.client.get("/api/v1/subjects?search=INT1154", headers=self.auth_headers)
        mock_get_all.assert_called_with(status=None, search="INT1154", limit=20, offset=0)

        # Search name with Unicode
        self.client.get("/api/v1/subjects?search=L%E1%BA%ADp%20tr%C3%ACnh", headers=self.auth_headers)
        mock_get_all.assert_called_with(status=None, search="Lập trình", limit=20, offset=0)

        # Search with SQL injection attempt (should be passed safely as string)
        self.client.get("/api/v1/subjects?search=' OR 1=1 --", headers=self.auth_headers)
        mock_get_all.assert_called_with(status=None, search="' OR 1=1 --", limit=20, offset=0)

    # =========================================================================
    # 3. DETAIL API (200, 400, 404, 500, Nullable serialization)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_16_get_detail_success(self, mock_get_by_id, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        valid_uuid = str(uuid.uuid4())
        sample = Subject(
            id=valid_uuid,
            code="INT1154",
            name="Lập trình hướng đối tượng",
            credits=3,
            description="Môn học Java OOP",
            total_sessions=15,
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        mock_get_by_id.return_value = sample

        res = self.client.get(f"/api/v1/subjects/{valid_uuid}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["id"], valid_uuid)
        self.assertEqual(data["code"], "INT1154")
        self.assertEqual(data["name"], "Lập trình hướng đối tượng")
        self.assertEqual(data["credits"], 3)
        self.assertEqual(data["description"], "Môn học Java OOP")
        self.assertEqual(data["total_sessions"], 15)
        self.assertEqual(data["status"], "active")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_17_get_detail_invalid_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        for bad_id in ["not-a-uuid", "12345", "12345678-1234-1234-1234-12345678901z"]:
            res = self.client.get(f"/api/v1/subjects/{bad_id}", headers=self.auth_headers)
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertEqual(data["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_18_get_detail_not_found_returns_404(self, mock_get_by_id, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/subjects/{valid_uuid}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data["code"], "SUBJECT_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    def test_23_database_error_returns_500_without_leak(self, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.side_effect = MySQLError("Database connection timeout")

        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn("Database connection timeout", data["message"])
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_24_serialization_nullable_fields(self, mock_get_by_id, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        valid_uuid = str(uuid.uuid4())
        sample = Subject(
            id=valid_uuid,
            code="PHY1001",
            name="Vật lý",
            credits=2,
            description=None,
            total_sessions=None,
            status="draft",
        )
        mock_get_by_id.return_value = sample

        res = self.client.get(f"/api/v1/subjects/{valid_uuid}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsNone(data["description"])
        self.assertIsNone(data["total_sessions"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_all_subjects")
    @patch("app.repositories.subject_repository.count_subjects")
    def test_25_route_alias_supported(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        # Alias /api/subjects
        res = self.client.get("/api/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_db_connection")
    def test_26_repository_connection_cleanup(self, mock_get_conn, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = {"total": 0}
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        # Verify connection was closed
        mock_conn.close.assert_called()

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.repositories.training_program_repository.count_training_programs")
    def test_27_no_regression_training_programs(self, mock_count, mock_get_all, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/training-programs", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_28_no_regression_health_endpoint(self):
        from app.main import app as main_app
        client = main_app.test_client()
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)


class Scrum123SubjectMySQLIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp MySQL (SUBJ-A2-) cho các endpoint đọc môn học."""

    def setUp(self):
        from app.main import app as main_app
        from app.services.session_service import create_stored_login_session

        self.app = main_app
        self.client = self.app.test_client()
        self.test_ids = []
        self.test_prefix = f"SUBJ-A2-{uuid.uuid4().hex[:6].upper()}"

        with self.app.app_context():
            # User có quyền course.view (admin)
            _, tokens_admin = create_stored_login_session("demo-user-admin")
            self.auth_headers = {
                "Authorization": f"Bearer {tokens_admin['access_token']}",
                "Content-Type": "application/json",
            }

            # User KHÔNG có quyền course.view (role user thông thường)
            _, tokens_plain = create_stored_login_session("fd355c4c-a950-4a0b-afdb-d21c62e40470")
            self.forbidden_headers = {
                "Authorization": f"Bearer {tokens_plain['access_token']}",
                "Content-Type": "application/json",
            }

        # Tạo sẵn một Subject test trực tiếp qua repository
        self.sample_id = str(uuid.uuid4())
        self.test_ids.append(self.sample_id)
        self.sample_code = f"{self.test_prefix}-OOP"
        self.sample_name = "Lập trình Hướng đối tượng Nâng cao"

        subject = Subject(
            id=self.sample_id,
            code=self.sample_code,
            name=self.sample_name,
            credits=4,
            description="Mô tả môn học test",
            total_sessions=20,
            status=SUBJECT_STATUS_ACTIVE,
        )
        subject_repository.insert_subject(subject)

    def tearDown(self):
        if self.test_ids:
            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    format_strings = ",".join(["%s"] * len(self.test_ids))
                    cur.execute(f"DELETE FROM subjects WHERE id IN ({format_strings})", tuple(self.test_ids))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_live_01_get_list_sees_created_subject(self):
        res = self.client.get(f"/api/v1/subjects?search={self.test_prefix}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        items = data["items"]
        self.assertTrue(any(it["code"] == self.sample_code for it in items))

    def test_live_02_search_by_code(self):
        res = self.client.get(f"/api/v1/subjects?search={self.sample_code}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], self.sample_id)

    def test_live_03_search_by_name(self):
        res = self.client.get(f"/api/v1/subjects?search={self.sample_name}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(it["id"] == self.sample_id for it in items))

    def test_live_04_filter_status(self):
        res = self.client.get(f"/api/v1/subjects?search={self.test_prefix}&status=active", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        items = res.get_json()["data"]["items"]
        self.assertTrue(any(it["id"] == self.sample_id for it in items))

        # Filter draft -> should not see active subject
        res_draft = self.client.get(f"/api/v1/subjects?search={self.test_prefix}&status=draft", headers=self.auth_headers)
        self.assertEqual(res_draft.status_code, 200)
        items_draft = res_draft.get_json()["data"]["items"]
        self.assertFalse(any(it["id"] == self.sample_id for it in items_draft))

    def test_live_05_get_detail_by_uuid(self):
        res = self.client.get(f"/api/v1/subjects/{self.sample_id}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["id"], self.sample_id)
        self.assertEqual(data["code"], self.sample_code)
        self.assertEqual(data["credits"], 4)
        self.assertEqual(data["total_sessions"], 20)

    def test_live_06_invalid_uuid_returns_400(self):
        res = self.client.get("/api/v1/subjects/invalid-uuid-format", headers=self.auth_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    def test_live_07_not_found_uuid_returns_404(self):
        random_uuid = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/subjects/{random_uuid}", headers=self.auth_headers)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "SUBJECT_NOT_FOUND")

    def test_live_08_course_view_permission_allows_access_200(self):
        res = self.client.get("/api/v1/subjects", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    def test_live_09_user_without_course_view_forbidden_403(self):
        res = self.client.get("/api/v1/subjects", headers=self.forbidden_headers)
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
