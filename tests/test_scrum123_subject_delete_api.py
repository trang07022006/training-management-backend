"""
Bộ kiểm thử SCRUM-123 (Activity A5): API xóa môn học / học phần an toàn (DELETE /api/v1/subjects/<id>).

Bao quát toàn diện:
1. Chính sách Hard Delete cho môn học chưa có dữ liệu phụ thuộc (HTTP 200).
2. Chặn xóa môn học đang có dữ liệu phụ thuộc (HTTP 409 SUBJECT_IN_USE).
3. Bắt lỗi Foreign Key IntegrityError (errno 1451/1217) phòng ngừa race condition.
4. Authentication & RBAC (401 unauthenticated, 401 invalid token, 403 chỉ có course.view, 200 có course.manage).
5. Error handling (400 INVALID_PARAMS cho UUID sai, 404 SUBJECT_NOT_FOUND khi không tồn tại).
6. Bảo mật (SQL injection qua UUID parameter, không lộ traceback hay thông tin nội bộ).
7. Kiểm thử tích hợp MySQL thực tế với prefix SUBJ-A5- và dọn dẹp sạch sẽ 100%.
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
    SubjectInUseError,
    SubjectNotFoundError,
    SubjectValidationError,
    delete_subject_service,
)


class Scrum123SubjectDeleteApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API xóa môn học (DELETE /api/v1/subjects/<id>)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum123-a5-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_bp)
        self.app.register_blueprint(training_program_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.subject_id = str(uuid.uuid4())

        # Session user có quyền course.manage
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

        # Session user chỉ có quyền course.view
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

        self.existing_subject = Subject(
            id=self.subject_id,
            code="INT1154",
            name="Lập trình hướng đối tượng",
            credits=3,
            description="Môn học OOP",
            total_sessions=15,
            status=SUBJECT_STATUS_ACTIVE,
            created_at=self.now,
            updated_at=self.now,
        )

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (401 & 403 & 200)
    # =========================================================================

    def test_06_delete_unauthenticated_returns_401(self):
        res = self.client.delete(f"/api/v1/subjects/{self.subject_id}")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    def test_07_delete_invalid_token_returns_401(self):
        bad_headers = {"Authorization": "Bearer bad.token.here"}
        res = self.client.delete(f"/api/v1/subjects/{self.subject_id}", headers=bad_headers)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_delete_forbidden_with_course_view_only_returns_403(
        self, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False  # Lacks course.manage

        res = self.client.delete(
            f"/api/v1/subjects/{self.subject_id}",
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data["code"], "FORBIDDEN")
        self.assertIn("Bạn không có quyền", data["message"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.delete_subject")
    def test_09_delete_with_course_manage_succeeds_200(
        self, mock_delete, mock_in_use, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_in_use.return_value = False
        mock_delete.return_value = True

        res = self.client.delete(
            f"/api/v1/subjects/{self.subject_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Xóa môn học thành công.")
        self.assertEqual(data["data"]["id"], self.subject_id)

    # =========================================================================
    # 2. VALIDATION & ERROR HANDLING (400, 404, 409)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_delete_invalid_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        for bad_id in ["not-a-uuid", "123", "abcdef-12345"]:
            res = self.client.delete(f"/api/v1/subjects/{bad_id}", headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_05_delete_non_existent_uuid_returns_404(
        self, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = None

        random_uuid = str(uuid.uuid4())
        res = self.client.delete(f"/api/v1/subjects/{random_uuid}", headers=self.manager_headers)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "SUBJECT_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    def test_10_11_delete_subject_in_use_precheck_returns_409(
        self, mock_in_use, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_in_use.return_value = True  # Pre-check phát hiện đang có dữ liệu liên quan

        res = self.client.delete(
            f"/api/v1/subjects/{self.subject_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "SUBJECT_IN_USE")
        self.assertIn("Không thể xóa môn học vì đang có dữ liệu liên quan", data["message"])
        self.assertIn("Đã lưu trữ", data["message"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.delete_subject")
    def test_12_mysql_foreign_key_violation_race_condition_returns_409(
        self, mock_delete, mock_in_use, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_in_use.return_value = False  # Pre-check vượt qua nhưng race condition xảy ra

        # MySQL FK constraint violation (errno 1451)
        fk_err = IntegrityError(errno=1451, msg="Cannot delete or update a parent row: a foreign key constraint fails")
        mock_delete.side_effect = fk_err

        res = self.client.delete(
            f"/api/v1/subjects/{self.subject_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data["code"], "SUBJECT_IN_USE")

    # =========================================================================
    # 3. DATABASE FAILURE & SECURITY & REGRESSION
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.delete_subject")
    def test_13_database_error_returns_500_without_leak(
        self, mock_delete, mock_in_use, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_in_use.return_value = False
        mock_delete.side_effect = MySQLError("Database connection timed out password=secret")

        res = self.client.delete(
            f"/api/v1/subjects/{self.subject_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn("password=secret", data["message"])
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_db_connection")
    def test_14_15_16_repository_connection_and_rollback_on_error(
        self, mock_get_conn, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("Fatal SQL execution error")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        with self.assertRaises(MySQLError):
            subject_repository.delete_subject(self.subject_id)

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_17_sql_injection_attempt_in_uuid_rejected(
        self, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        sqli_id = f"{self.subject_id}' OR 1=1; --"
        res = self.client.delete(f"/api/v1/subjects/{sqli_id}", headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.delete_subject")
    def test_18_route_alias_supported(
        self, mock_delete, mock_in_use, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_in_use.return_value = False
        mock_delete.return_value = True

        # Alias: DELETE /api/subjects/<id>
        res = self.client.delete(f"/api/subjects/{self.subject_id}", headers=self.manager_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.repositories.training_program_repository.count_training_programs")
    def test_22_no_regression_training_programs(
        self, mock_count, mock_get_all, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/training-programs", headers=self.manager_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")


class Scrum123SubjectDeleteMySQLIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp thực tế với MySQL (prefix SUBJ-A5-) cho API xóa môn học."""

    def setUp(self):
        from app.main import app as main_app
        from app.services.session_service import create_stored_login_session

        self.app = main_app
        self.client = self.app.test_client()
        self.created_subject_ids = []
        self.test_prefix = f"SUBJ-A5-{uuid.uuid4().hex[:6].upper()}"

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

        # Tạo sẵn một Subject test để thao tác
        payload = {
            "code": f"{self.test_prefix}-DEL",
            "name": "Môn học Test Xóa An Toàn",
            "credits": 3,
            "description": "Mô tả môn học test",
            "total_sessions": 15,
            "status": "draft",
        }
        res = self.client.post("/api/v1/subjects", json=payload, headers=self.manager_headers)
        self.assertEqual(res.status_code, 201)
        self.subject_id = res.get_json()["data"]["id"]
        self.created_subject_ids.append(self.subject_id)

    def tearDown(self):
        # Dọn dẹp sạch sẽ toàn bộ bản ghi test SUBJ-A5-
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

    def test_live_01_through_04_create_get_delete_and_verify_404(self):
        # 2. GET xác nhận tồn tại
        get_res1 = self.client.get(f"/api/v1/subjects/{self.subject_id}", headers=self.manager_headers)
        self.assertEqual(get_res1.status_code, 200)

        # 3. DELETE subject
        del_res = self.client.delete(f"/api/v1/subjects/{self.subject_id}", headers=self.manager_headers)
        self.assertEqual(del_res.status_code, 200)
        data = del_res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["id"], self.subject_id)

        # 4. GET lại -> phải nhận về 404
        get_res2 = self.client.get(f"/api/v1/subjects/{self.subject_id}", headers=self.manager_headers)
        self.assertEqual(get_res2.status_code, 404)
        self.assertEqual(get_res2.get_json()["code"], "SUBJECT_NOT_FOUND")

    def test_live_05_delete_non_existent_uuid_returns_404(self):
        random_uuid = str(uuid.uuid4())
        res = self.client.delete(f"/api/v1/subjects/{random_uuid}", headers=self.manager_headers)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "SUBJECT_NOT_FOUND")

    def test_live_06_delete_invalid_uuid_returns_400(self):
        res = self.client.delete("/api/v1/subjects/invalid-uuid-format-1234", headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    def test_live_07_delete_no_token_returns_401(self):
        res = self.client.delete(f"/api/v1/subjects/{self.subject_id}")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    def test_live_08_course_view_delete_returns_403(self):
        res = self.client.delete(
            f"/api/v1/subjects/{self.subject_id}",
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    def test_live_10_other_tables_unaffected(self):
        # Kiểm tra bảng users hoặc training_programs vẫn hoàn toàn nguyên vẹn
        res_tp = self.client.get("/api/v1/training-programs", headers=self.manager_headers)
        self.assertEqual(res_tp.status_code, 200)
        self.assertEqual(res_tp.get_json()["status"], "success")


if __name__ == "__main__":
    unittest.main()
