"""
Bộ kiểm thử SCRUM-123 (Activity A3): API tạo mới môn học / học phần (POST /api/v1/subjects).

Bao quát toàn diện:
1. Authentication & RBAC (401 không token, 401 token sai, 403 chỉ có course.view, 201 có course.manage).
2. Validation contract (code, name, credits, description, total_sessions, status, invalid types, bounds).
3. Two-tier duplicate code protection (service pre-check & DB IntegrityError 1062 race condition).
4. System fields protection (id, created_at, updated_at do server tự sinh, không tin client).
5. Success response (201, Location header, UTC timestamps, schema).
6. Security (SQL injection parameterized, no database leak).
7. Live MySQL Integration (SUBJ-A3- prefix, clean up toàn bộ dữ liệu).
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError, IntegrityError

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.subject import (
    SUBJECT_STATUS_ACTIVE,
    SUBJECT_STATUS_DRAFT,
    Subject,
)
from app.repositories import subject_repository
from app.routes.subject_routes import subject_bp
from app.routes.training_program_routes import training_program_bp
from app.services.subject_service import (
    DuplicateSubjectCodeError,
    SubjectValidationError,
    create_subject_service,
)


class Scrum123SubjectCreateApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật RBAC cho API tạo mới môn học (POST /api/v1/subjects)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum123-a3-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_bp)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # 1. User có quyền course.manage (Admin / Manager)
        self.manager_user_id = "user-course-manage-uuid"
        self.manager_session = LoginSession(
            session_id="session-manager-123",
            user_id=self.manager_user_id,
            refresh_jti="ref-manager-123",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # 2. User chỉ có quyền course.view (Trainee / Viewer)
        self.viewer_user_id = "user-course-view-uuid"
        self.viewer_session = LoginSession(
            session_id="session-viewer-123",
            user_id=self.viewer_user_id,
            refresh_jti="ref-viewer-123",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-manager-123"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-viewer-123"},
            )

        self.manager_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.viewer_headers = {"Authorization": f"Bearer {self.viewer_token}"}

        self.valid_payload = {
            "code": "INT1154",
            "name": "Lập trình hướng đối tượng",
            "description": "Học phần về lập trình hướng đối tượng",
            "credits": 3,
            "total_sessions": 15,
            "status": "draft",
        }

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (401, 403, 201)
    # =========================================================================

    def test_32_create_unauthenticated_returns_401(self):
        res = self.client.post("/api/v1/subjects", json=self.valid_payload)
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    def test_33_create_invalid_token_returns_401(self):
        headers = {"Authorization": "Bearer not.a.valid.jwt.token"}
        res = self.client.post("/api/v1/subjects", json=self.valid_payload, headers=headers)
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_34_create_forbidden_with_only_course_view_returns_403(
        self, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False  # Lacks course.manage

        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")
        self.assertIn("Bạn không có quyền", data.get("message"))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_35_create_with_course_manage_returns_201(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

    # =========================================================================
    # 2. SUCCESS RESPONSE & LOCATION HEADER & SYSTEM FIELDS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_01_02_03_create_success_and_location_header(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Tạo môn học thành công.")
        subject_data = data["data"]

        # 04. UUID v4 hợp lệ
        self.assertEqual(len(subject_data["id"]), 36)
        parsed_uuid = uuid.UUID(subject_data["id"])
        self.assertEqual(str(parsed_uuid), subject_data["id"])

        # 03. Location header đúng
        self.assertEqual(res.headers.get("Location"), f"/api/v1/subjects/{subject_data['id']}")

        # 05. UTC timestamps do server sinh
        self.assertIsNotNone(subject_data["created_at"])
        self.assertIsNotNone(subject_data["updated_at"])
        self.assertEqual(subject_data["code"], "INT1154")
        self.assertEqual(subject_data["name"], "Lập trình hướng đối tượng")
        self.assertEqual(subject_data["credits"], 3)
        self.assertEqual(subject_data["total_sessions"], 15)
        self.assertEqual(subject_data["status"], "draft")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_06_default_status_draft_when_omitted(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        payload = {
            "code": "MATH101",
            "name": "Giải tích 1",
            "credits": 4,
        }
        res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertEqual(data["status"], "draft")
        self.assertIsNone(data["description"])
        self.assertIsNone(data["total_sessions"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_07_08_09_10_optional_and_null_description_and_total_sessions(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        payload = {
            "code": "PHY101",
            "name": "Vật lý đại cương",
            "credits": 3,
            "description": None,
            "total_sessions": None,
        }
        res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertIsNone(data["description"])
        self.assertIsNone(data["total_sessions"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_39_40_41_client_system_fields_ignored(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        client_id = "client-injected-id-0000-000000000000"
        payload = {
            "id": client_id,
            "code": "SYS101",
            "name": "Hệ điều hành",
            "credits": 3,
            "created_at": "1999-01-01T00:00:00Z",
            "updated_at": "1999-01-01T00:00:00Z",
        }
        res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.assertNotEqual(data["id"], client_id)
        self.assertNotEqual(data["created_at"], "1999-01-01T00:00:00Z")

    # =========================================================================
    # 3. VALIDATION RULES (400)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_invalid_json_body(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        res = self.client.post(
            "/api/v1/subjects",
            data="not a json",
            content_type="text/plain",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_JSON")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_11_12_13_code_validation(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # 11. Thiếu code
        res1 = self.client.post("/api/v1/subjects", json={"name": "A", "credits": 3}, headers=self.manager_headers)
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "CODE_REQUIRED")

        # 12. Code rỗng / khoảng trắng
        for bad_code in ["", "   ", None, 12345]:
            res = self.client.post("/api/v1/subjects", json={"code": bad_code, "name": "A", "credits": 3}, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "CODE_REQUIRED")

        # 13. Code quá dài (> 50 ký tự)
        res3 = self.client.post("/api/v1/subjects", json={"code": "A" * 51, "name": "A", "credits": 3}, headers=self.manager_headers)
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "CODE_TOO_LONG")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_15_16_name_validation(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # 14. Thiếu name
        res1 = self.client.post("/api/v1/subjects", json={"code": "INT101", "credits": 3}, headers=self.manager_headers)
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "NAME_REQUIRED")

        # 15. Name rỗng / khoảng trắng
        for bad_name in ["", "   ", None, ["List", "Name"]]:
            res = self.client.post("/api/v1/subjects", json={"code": "INT101", "name": bad_name, "credits": 3}, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "NAME_REQUIRED")

        # 16. Name quá dài (> 255 ký tự)
        res3 = self.client.post("/api/v1/subjects", json={"code": "INT101", "name": "B" * 256, "credits": 3}, headers=self.manager_headers)
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "NAME_TOO_LONG")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_17_through_23_credits_validation(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # 17. Thiếu credits
        res = self.client.post("/api/v1/subjects", json={"code": "INT101", "name": "OOP"}, headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

        # 18. credits = 0
        # 19. credits > 30
        # 20. credits âm
        # 21. credits bool
        # 22. credits float
        # 23. credits string
        invalid_credits = [0, 31, 100, -1, -5, True, False, 3.5, "3", "three", None, []]
        for bad_c in invalid_credits:
            payload = {"code": "INT101", "name": "OOP", "credits": bad_c}
            res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400, f"credits {bad_c} should be rejected with 400")
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_24_through_27_total_sessions_validation(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # 24. total_sessions âm
        # 25. total_sessions > 65535
        # 26. total_sessions bool
        # 27. total_sessions float
        invalid_sessions = [-1, -10, 65536, 100000, True, False, 15.5, "15"]
        for bad_s in invalid_sessions:
            payload = {"code": "INT101", "name": "OOP", "credits": 3, "total_sessions": bad_s}
            res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400, f"total_sessions {bad_s} should be rejected with 400")
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_28_description_type_validation(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # 28. description sai kiểu (int, list, dict, bool)
        invalid_desc = [123, True, False, ["Mô tả"], {"desc": "test"}]
        for bad_d in invalid_desc:
            payload = {"code": "INT101", "name": "OOP", "credits": 3, "description": bad_d}
            res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_29_status_validation(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # 29. status sai
        invalid_status = ["deleted", "pending", "unknown", 123, True, False]
        for bad_st in invalid_status:
            payload = {"code": "INT101", "name": "OOP", "credits": 3, "status": bad_st}
            res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    # =========================================================================
    # 4. DUPLICATE CODE PROTECTION (409)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_30_duplicate_code_service_check_returns_409(
        self, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = True  # Code already exists

        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "DUPLICATE_CODE")
        self.assertIn("đã tồn tại", data["message"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_31_duplicate_code_race_condition_integrity_error_returns_409(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False  # Service check passed

        # DB raises IntegrityError 1062
        integ_err = IntegrityError(errno=1062, msg="Duplicate entry 'INT1154' for key 'subjects.uq_subjects_code'")
        mock_insert.side_effect = integ_err

        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "DUPLICATE_CODE")

    # =========================================================================
    # 5. ERROR HANDLING & SECURITY & ALIASES
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_36_database_error_returns_500_without_leak(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = MySQLError("Database connection timed out secret_pass=123")

        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn("secret_pass", data["message"])
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_38_sql_injection_safe_parameterized(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        payload = {
            "code": "SQLI'; DROP TABLE subjects; --",
            "name": "SQL Injection Test ' OR 1=1 --",
            "credits": 3,
        }
        res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        # Code is uppercased and trimmed safely
        self.assertEqual(data["code"], "SQLI'; DROP TABLE SUBJECTS; --")
        self.assertEqual(data["name"], "SQL Injection Test ' OR 1=1 --")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    @patch("app.repositories.subject_repository.insert_subject")
    def test_43_route_alias_supported(
        self, mock_insert, mock_exists, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_exists.return_value = False
        mock_insert.side_effect = lambda subj: subj

        # Alias: POST /api/subjects
        res = self.client.post(
            "/api/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()["status"], "success")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.repositories.training_program_repository.count_training_programs")
    def test_44_no_regression_training_programs(
        self, mock_count, mock_get_all, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/training-programs", headers=self.manager_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")


class Scrum123SubjectCreateMySQLIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp thực tế với MySQL (prefix SUBJ-A3-) cho API tạo mới môn học."""

    def setUp(self):
        from app.main import app as main_app
        from app.services.session_service import create_stored_login_session

        self.app = main_app
        self.client = self.app.test_client()
        self.created_subject_ids = []
        self.test_prefix = f"SUBJ-A3-{uuid.uuid4().hex[:6].upper()}"

        with self.app.app_context():
            # 1. User có quyền course.manage (demo-user-admin)
            _, tokens_admin = create_stored_login_session("demo-user-admin")
            self.manager_headers = {
                "Authorization": f"Bearer {tokens_admin['access_token']}",
                "Content-Type": "application/json",
            }

            # 2. User có course.view nhưng KHÔNG có course.manage (trainee: 551f6416-567b-48e4-bae4-e5f11e20da32)
            _, tokens_trainee = create_stored_login_session("551f6416-567b-48e4-bae4-e5f11e20da32")
            self.viewer_headers = {
                "Authorization": f"Bearer {tokens_trainee['access_token']}",
                "Content-Type": "application/json",
            }

        self.valid_payload = {
            "code": f"{self.test_prefix}-NET",
            "name": "Mạng máy tính nâng cao",
            "description": "Môn học mạng máy tính và truyền thông dữ liệu",
            "credits": 3,
            "total_sessions": 15,
            "status": "draft",
        }

    def tearDown(self):
        # Dọn dẹp an toàn toàn bộ dữ liệu test SUBJ-A3-
        if self.created_subject_ids:
            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    format_strings = ",".join(["%s"] * len(self.created_subject_ids))
                    cur.execute(
                        f"DELETE FROM subjects WHERE id IN ({format_strings})",
                        tuple(self.created_subject_ids),
                    )
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_live_01_no_token_post_returns_401(self):
        res = self.client.post("/api/v1/subjects", json=self.valid_payload)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    def test_live_02_course_view_post_returns_403(self):
        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    def test_live_03_04_05_course_manage_post_valid_returns_201_and_checks(self):
        res = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        subj = data["data"]
        new_id = subj["id"]
        self.created_subject_ids.append(new_id)

        # 4. Kiểm tra UUID hợp lệ
        self.assertEqual(len(new_id), 36)
        parsed_uuid = uuid.UUID(new_id)
        self.assertEqual(str(parsed_uuid), new_id)

        # 5. Kiểm tra status draft
        self.assertEqual(subj["status"], "draft")
        self.assertEqual(subj["code"], self.valid_payload["code"].upper())
        self.assertEqual(subj["credits"], 3)
        self.assertEqual(subj["total_sessions"], 15)

    def test_live_06_07_get_list_and_detail_sees_created_subject(self):
        # 1. Tạo môn học qua POST
        res_post = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res_post.status_code, 201)
        subj_id = res_post.get_json()["data"]["id"]
        self.created_subject_ids.append(subj_id)

        # 6. GET list thấy subject
        res_list = self.client.get(
            f"/api/v1/subjects?search={self.test_prefix}",
            headers=self.manager_headers,
        )
        self.assertEqual(res_list.status_code, 200)
        items = res_list.get_json()["data"]["items"]
        self.assertTrue(any(it["id"] == subj_id for it in items))

        # 7. GET detail thấy subject
        res_detail = self.client.get(
            f"/api/v1/subjects/{subj_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res_detail.status_code, 200)
        detail_data = res_detail.get_json()["data"]
        self.assertEqual(detail_data["id"], subj_id)
        self.assertEqual(detail_data["code"], self.valid_payload["code"].upper())

    def test_live_08_post_duplicate_code_returns_409(self):
        # Tạo môn học lần 1
        res1 = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res1.status_code, 201)
        self.created_subject_ids.append(res1.get_json()["data"]["id"])

        # Tạo lại với cùng mã code -> 409 DUPLICATE_CODE
        res2 = self.client.post(
            "/api/v1/subjects",
            json=self.valid_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.get_json()["code"], "DUPLICATE_CODE")

    def test_live_09_create_unicode_name_success(self):
        unicode_payload = {
            "code": f"{self.test_prefix}-VN",
            "name": "Cấu trúc dữ liệu và giải thuật tiếng Việt có dấu",
            "description": "Mô tả tiếng Việt UTF-8 đầy đủ ký tự đặc biệt: Đ, Ê, Ô, Ơ, Ư",
            "credits": 4,
            "total_sessions": 20,
            "status": "active",
        }
        res = self.client.post(
            "/api/v1/subjects",
            json=unicode_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]
        self.created_subject_ids.append(data["id"])
        self.assertEqual(data["name"], unicode_payload["name"])
        self.assertEqual(data["description"], unicode_payload["description"])
        self.assertEqual(data["status"], "active")

    def test_live_10_invalid_credits_returns_400(self):
        bad_payload = {
            "code": f"{self.test_prefix}-BAD",
            "name": "Môn học sai tín chỉ",
            "credits": 0,  # Invalid
        }
        res = self.client.post(
            "/api/v1/subjects",
            json=bad_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")


if __name__ == "__main__":
    unittest.main()
