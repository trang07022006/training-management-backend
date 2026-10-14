"""
Bộ kiểm thử SCRUM-123 (Activity A4): API cập nhật môn học / học phần (PUT và PATCH /api/v1/subjects/<id>).

Bao quát toàn diện:
1. Semantics PUT (thay thế toàn bộ các trường nghiệp vụ có thể chỉnh sửa; reset optional fields nếu thiếu).
2. Semantics PATCH (chỉ cập nhật các trường được gửi; giữ nguyên các trường khác; từ chối payload rỗng).
3. System fields (id và created_at giữ nguyên; updated_at do server tự cập nhật theo UTC; client không điều khiển).
4. Validation (code, name, credits, description, total_sessions, status; tái sử dụng helper).
5. Duplicate code protection (bảo vệ 2 tầng: service pre-check với exclude_id, giữ nguyên code không lỗi, DB race condition IntegrityError 1062).
6. Authentication & RBAC (401 unauthenticated, 401 invalid token, 403 thiếu course.manage, 200 có course.manage).
7. Error handling & An toàn SQL (400, 404, 409, 500 không rò rỉ nội bộ, dynamic whitelist cho PATCH).
8. Live MySQL Integration (tiền tố SUBJ-A4-, dọn dẹp sạch sẽ 100% dữ liệu test).
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
    SUBJECT_STATUS_ARCHIVED,
    SUBJECT_STATUS_DRAFT,
    Subject,
)
from app.repositories import subject_repository
from app.routes.subject_routes import subject_bp
from app.routes.training_program_routes import training_program_bp
from app.services import subject_service
from app.services.subject_service import (
    DuplicateSubjectCodeError,
    SubjectNotFoundError,
    SubjectValidationError,
)


class Scrum123SubjectUpdateApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API cập nhật môn học (PUT và PATCH)."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum123-a4-at-least-32-bytes-long",
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

        # Bản ghi Subject mẫu tồn tại sẵn
        self.existing_subject = Subject(
            id=self.subject_id,
            code="INT1154",
            name="Lập trình hướng đối tượng",
            credits=3,
            description="Môn học OOP ban đầu",
            total_sessions=15,
            status=SUBJECT_STATUS_ACTIVE,
            created_at=self.now - timedelta(days=10),
            updated_at=self.now - timedelta(days=5),
        )

        self.valid_put_payload = {
            "code": "INT1154-UPDATED",
            "name": "Lập trình hướng đối tượng nâng cao",
            "credits": 4,
            "description": "Nội dung cập nhật toàn bộ",
            "total_sessions": 20,
            "status": "active",
        }

    # =========================================================================
    # 1. AUTHENTICATION & RBAC (401 & 403 & 200)
    # =========================================================================

    def test_38_update_unauthenticated_returns_401(self):
        for method, endpoint in [
            (self.client.put, f"/api/v1/subjects/{self.subject_id}"),
            (self.client.patch, f"/api/v1/subjects/{self.subject_id}"),
        ]:
            res = method(endpoint, json=self.valid_put_payload)
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    def test_39_update_invalid_token_returns_401(self):
        bad_headers = {"Authorization": "Bearer bad.token.here"}
        for method, endpoint in [
            (self.client.put, f"/api/v1/subjects/{self.subject_id}"),
            (self.client.patch, f"/api/v1/subjects/{self.subject_id}"),
        ]:
            res = method(endpoint, json=self.valid_put_payload, headers=bad_headers)
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.get_json()["code"], "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_40_update_with_course_view_only_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False  # Lacks course.manage

        for method, endpoint in [
            (self.client.put, f"/api/v1/subjects/{self.subject_id}"),
            (self.client.patch, f"/api/v1/subjects/{self.subject_id}"),
        ]:
            res = method(endpoint, json=self.valid_put_payload, headers=self.viewer_headers)
            self.assertEqual(res.status_code, 403)
            data = res.get_json()
            self.assertEqual(data["code"], "FORBIDDEN")
            self.assertIn("Bạn không có quyền", data["message"])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_41_update_with_course_manage_returns_200(
        self, mock_exists, mock_update, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = False
        mock_update.return_value = True

        res = self.client.put(
            f"/api/v1/subjects/{self.subject_id}",
            json=self.valid_put_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

    # =========================================================================
    # 2. PUT FUNCTIONALITY & SYSTEM FIELDS & OPTIONAL RESET
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_01_put_success_and_preserves_system_fields(
        self, mock_exists, mock_update, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = False
        mock_update.return_value = True

        client_tampered_payload = dict(self.valid_put_payload)
        client_tampered_payload["id"] = "hacked-id-12345"
        client_tampered_payload["created_at"] = "1999-01-01T00:00:00Z"
        client_tampered_payload["updated_at"] = "1999-01-01T00:00:00Z"

        res = self.client.put(
            f"/api/v1/subjects/{self.subject_id}",
            json=client_tampered_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Cập nhật môn học thành công.")
        res_subj = data["data"]

        # 11. id không đổi
        self.assertEqual(res_subj["id"], self.subject_id)
        # 12. created_at không đổi
        self.assertEqual(res_subj["created_at"], self.existing_subject.created_at.isoformat())
        # 13. updated_at do server tạo mới
        self.assertNotEqual(res_subj["updated_at"], "1999-01-01T00:00:00Z")
        self.assertEqual(res_subj["code"], "INT1154-UPDATED")
        self.assertEqual(res_subj["name"], "Lập trình hướng đối tượng nâng cao")
        self.assertEqual(res_subj["credits"], 4)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_10_put_resets_optional_fields_when_omitted(
        self, mock_exists, mock_update, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = False
        mock_update.return_value = True

        # Chỉ gửi code, name, credits -> description/total_sessions = None, status = 'draft'
        minimal_put_payload = {
            "code": "INT1154",
            "name": "Lập trình OOP Mới",
            "credits": 3,
        }
        res = self.client.put(
            f"/api/v1/subjects/{self.subject_id}",
            json=minimal_put_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsNone(data["description"])
        self.assertIsNone(data["total_sessions"])
        self.assertEqual(data["status"], "draft")

    # =========================================================================
    # 3. PATCH FUNCTIONALITY & PARTIAL UPDATES
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject_fields")
    def test_02_03_patch_only_name(
        self, mock_update_fields, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        updated_sample = Subject(
            id=self.subject_id,
            code=self.existing_subject.code,
            name="Tên Mới Chỉ Đổi Qua PATCH",
            credits=self.existing_subject.credits,
            description=self.existing_subject.description,
            total_sessions=self.existing_subject.total_sessions,
            status=self.existing_subject.status,
            created_at=self.existing_subject.created_at,
            updated_at=self.now,
        )
        mock_update_fields.return_value = updated_sample

        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"name": "Tên Mới Chỉ Đổi Qua PATCH"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["data"]["name"], "Tên Mới Chỉ Đổi Qua PATCH")
        self.assertEqual(data["data"]["code"], self.existing_subject.code)
        self.assertEqual(data["data"]["credits"], self.existing_subject.credits)
        mock_update_fields.assert_called_once_with(
            self.subject_id, {"name": "Tên Mới Chỉ Đổi Qua PATCH"}
        )

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject_fields")
    def test_04_patch_only_credits(
        self, mock_update_fields, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        updated_sample = Subject(
            id=self.subject_id,
            code=self.existing_subject.code,
            name=self.existing_subject.name,
            credits=5,
            description=self.existing_subject.description,
            total_sessions=self.existing_subject.total_sessions,
            status=self.existing_subject.status,
            created_at=self.existing_subject.created_at,
            updated_at=self.now,
        )
        mock_update_fields.return_value = updated_sample

        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"credits": 5},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["credits"], 5)
        mock_update_fields.assert_called_once_with(self.subject_id, {"credits": 5})

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject_fields")
    def test_05_patch_only_status(
        self, mock_update_fields, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        updated_sample = Subject(
            id=self.subject_id,
            code=self.existing_subject.code,
            name=self.existing_subject.name,
            credits=self.existing_subject.credits,
            description=self.existing_subject.description,
            total_sessions=self.existing_subject.total_sessions,
            status=SUBJECT_STATUS_ARCHIVED,
            created_at=self.existing_subject.created_at,
            updated_at=self.now,
        )
        mock_update_fields.return_value = updated_sample

        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"status": "archived"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["status"], "archived")
        mock_update_fields.assert_called_once_with(self.subject_id, {"status": "archived"})

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject_fields")
    def test_06_07_08_09_patch_null_and_multiple_fields(
        self, mock_update_fields, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        updated_sample = Subject(
            id=self.subject_id,
            code=self.existing_subject.code,
            name=self.existing_subject.name,
            credits=self.existing_subject.credits,
            description=None,
            total_sessions=None,
            status=self.existing_subject.status,
            created_at=self.existing_subject.created_at,
            updated_at=self.now,
        )
        mock_update_fields.return_value = updated_sample

        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"description": None, "total_sessions": None},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        mock_update_fields.assert_called_once_with(
            self.subject_id, {"description": None, "total_sessions": None}
        )

    # =========================================================================
    # 4. VALIDATION & ERROR HANDLING (400, 404)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_14_invalid_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        for bad_id in ["not-a-uuid", "123", "abcdefg-1234"]:
            res_put = self.client.put(f"/api/v1/subjects/{bad_id}", json=self.valid_put_payload, headers=self.manager_headers)
            self.assertEqual(res_put.status_code, 400)
            self.assertEqual(res_put.get_json()["code"], "INVALID_PARAMS")

            res_patch = self.client.patch(f"/api/v1/subjects/{bad_id}", json={"name": "A"}, headers=self.manager_headers)
            self.assertEqual(res_patch.status_code, 400)
            self.assertEqual(res_patch.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_15_not_found_uuid_returns_404(self, mock_get_by_id, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = None

        res_put = self.client.put(f"/api/v1/subjects/{self.subject_id}", json=self.valid_put_payload, headers=self.manager_headers)
        self.assertEqual(res_put.status_code, 404)
        self.assertEqual(res_put.get_json()["code"], "SUBJECT_NOT_FOUND")

        res_patch = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"name": "New"}, headers=self.manager_headers)
        self.assertEqual(res_patch.status_code, 404)
        self.assertEqual(res_patch.get_json()["code"], "SUBJECT_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_16_invalid_json_body_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        res = self.client.put(
            f"/api/v1/subjects/{self.subject_id}",
            data="invalid-json",
            content_type="text/plain",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_JSON")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_17_patch_empty_payload_or_system_only_returns_400(
        self, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        # 1. Payload rỗng {}
        res1 = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={}, headers=self.manager_headers)
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "INVALID_PARAMS")

        # 2. Payload chỉ chứa trường hệ thống (id, created_at, updated_at)
        res2 = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"id": str(uuid.uuid4()), "created_at": "2020-01-01T00:00:00Z"},
            headers=self.manager_headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_18_19_20_put_missing_required_fields_returns_400(
        self, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        # 18. Thiếu code
        res1 = self.client.put(f"/api/v1/subjects/{self.subject_id}", json={"name": "A", "credits": 3}, headers=self.manager_headers)
        self.assertEqual(res1.status_code, 400)
        self.assertEqual(res1.get_json()["code"], "CODE_REQUIRED")

        # 19. Thiếu name
        res2 = self.client.put(f"/api/v1/subjects/{self.subject_id}", json={"code": "INT101", "credits": 3}, headers=self.manager_headers)
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json()["code"], "NAME_REQUIRED")

        # 20. Thiếu credits
        res3 = self.client.put(f"/api/v1/subjects/{self.subject_id}", json={"code": "INT101", "name": "A"}, headers=self.manager_headers)
        self.assertEqual(res3.status_code, 400)
        self.assertEqual(res3.get_json()["code"], "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_21_through_34_field_validation_cases(
        self, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject

        # 21, 22: Code rỗng / quá dài
        res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"code": "   "}, headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "CODE_REQUIRED")

        res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"code": "A" * 51}, headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "CODE_TOO_LONG")

        # 23, 24: Name rỗng / quá dài
        res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"name": ""}, headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NAME_REQUIRED")

        res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"name": "A" * 256}, headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "NAME_TOO_LONG")

        # 25-29: Credits invalid
        for bad_c in [0, 31, True, 3.5, "3", -1]:
            res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"credits": bad_c}, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

        # 30-32: total_sessions invalid
        for bad_s in [-1, 70000, True, 15.5]:
            res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"total_sessions": bad_s}, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

        # 33: description sai type
        res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"description": 123}, headers=self.manager_headers)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

        # 34: status sai
        for bad_st in ["deleted", "pending", 123, True, None, ""]:
            res = self.client.patch(f"/api/v1/subjects/{self.subject_id}", json={"status": bad_st}, headers=self.manager_headers)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    # =========================================================================
    # 5. DUPLICATE CODE HANDLING & RACE CONDITIONS (409)
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_35_update_duplicate_code_returns_409(
        self, mock_exists, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = True  # Trùng mã của môn học khác

        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"code": "OTHER-CODE"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_CODE")
        mock_exists.assert_called_once_with("OTHER-CODE", exclude_id=self.subject_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject_fields")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_36_update_keep_same_code_succeeds_200(
        self, mock_exists, mock_update_fields, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_update_fields.return_value = self.existing_subject

        # Giữ nguyên code hiện tại ("INT1154")
        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json={"code": "INT1154", "name": "Đổi Tên Giữ Code"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        mock_exists.assert_not_called()  # Không cần check duplicate khi giữ nguyên code

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_37_database_integrity_error_race_condition_returns_409(
        self, mock_exists, mock_update, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = False

        # Database ném lỗi 1062 duplicate key do race condition
        mock_update.side_effect = IntegrityError(errno=1062, msg="Duplicate entry 'INT1154' for key 'uq_subjects_code'")

        res = self.client.put(
            f"/api/v1/subjects/{self.subject_id}",
            json=self.valid_put_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_CODE")

    # =========================================================================
    # 6. DATABASE FAILURE & SECURITY & REGRESSION
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_42_database_error_returns_500_without_leak(
        self, mock_exists, mock_update, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = False
        mock_update.side_effect = MySQLError("Database connection timed out secret_db_pass=xxx")

        res = self.client.put(
            f"/api/v1/subjects/{self.subject_id}",
            json=self.valid_put_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data["code"], "DATABASE_ERROR")
        self.assertNotIn("secret_db_pass", data["message"])
        self.assertNotIn("Traceback", res.get_data(as_text=True))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject_fields")
    def test_44_sql_injection_safe_parameterized(
        self, mock_update_fields, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_update_fields.return_value = self.existing_subject

        sqli_payload = {"name": "Test'; DROP TABLE subjects; --"}
        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_id}",
            json=sqli_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        mock_update_fields.assert_called_once_with(self.subject_id, sqli_payload)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.update_subject")
    @patch("app.repositories.subject_repository.update_subject_fields")
    @patch("app.repositories.subject_repository.exists_by_code")
    def test_45_route_aliases_supported(
        self, mock_exists, mock_update_fields, mock_update, mock_get_by_id, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_by_id.return_value = self.existing_subject
        mock_exists.return_value = False
        mock_update.return_value = True
        mock_update_fields.return_value = self.existing_subject

        # PUT alias: /api/subjects/<id>
        res_put = self.client.put(
            f"/api/subjects/{self.subject_id}",
            json=self.valid_put_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res_put.status_code, 200)

        # PATCH alias: /api/subjects/<id>
        res_patch = self.client.patch(
            f"/api/subjects/{self.subject_id}",
            json={"name": "Alias Test"},
            headers=self.manager_headers,
        )
        self.assertEqual(res_patch.status_code, 200)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.training_program_repository.get_all_training_programs")
    @patch("app.repositories.training_program_repository.count_training_programs")
    def test_48_no_regression_training_programs(
        self, mock_count, mock_get_all, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_all.return_value = []
        mock_count.return_value = 0

        res = self.client.get("/api/v1/training-programs", headers=self.manager_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")


class Scrum123SubjectUpdateMySQLIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp trực tiếp MySQL (SUBJ-A4-) cho API cập nhật môn học."""

    def setUp(self):
        from app.main import app as main_app
        from app.services.session_service import create_stored_login_session

        self.app = main_app
        self.client = self.app.test_client()
        self.created_subject_ids = []
        self.test_prefix = f"SUBJ-A4-{uuid.uuid4().hex[:6].upper()}"

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

        # 1. POST tạo subject A
        payload_a = {
            "code": f"{self.test_prefix}-SUBJA",
            "name": "Môn học A Ban đầu",
            "description": "Mô tả A ban đầu",
            "credits": 3,
            "total_sessions": 15,
            "status": "draft",
        }
        res_a = self.client.post("/api/v1/subjects", json=payload_a, headers=self.manager_headers)
        self.assertEqual(res_a.status_code, 201)
        self.subject_a_id = res_a.get_json()["data"]["id"]
        self.subject_a_code = payload_a["code"]
        self.created_subject_ids.append(self.subject_a_id)

        # 2. POST tạo subject B
        payload_b = {
            "code": f"{self.test_prefix}-SUBJB",
            "name": "Môn học B Ban đầu",
            "description": "Mô tả B ban đầu",
            "credits": 2,
            "total_sessions": 10,
            "status": "active",
        }
        res_b = self.client.post("/api/v1/subjects", json=payload_b, headers=self.manager_headers)
        self.assertEqual(res_b.status_code, 201)
        self.subject_b_id = res_b.get_json()["data"]["id"]
        self.subject_b_code = payload_b["code"]
        self.created_subject_ids.append(self.subject_b_id)

    def tearDown(self):
        # Dọn dẹp sạch sẽ 100% dữ liệu test SUBJ-A4-
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

    def test_live_01_through_12_patch_and_put_lifecycle(self):
        # 3. PATCH A đổi name
        patch_res = self.client.patch(
            f"/api/v1/subjects/{self.subject_a_id}",
            json={"name": "Môn học A Đã Đổi Tên"},
            headers=self.manager_headers,
        )
        self.assertEqual(patch_res.status_code, 200)

        # 4. GET xác nhận name đổi
        get_res1 = self.client.get(f"/api/v1/subjects/{self.subject_a_id}", headers=self.manager_headers)
        self.assertEqual(get_res1.status_code, 200)
        data1 = get_res1.get_json()["data"]
        self.assertEqual(data1["name"], "Môn học A Đã Đổi Tên")

        # 5. Xác nhận credits/status không đổi
        self.assertEqual(data1["credits"], 3)
        self.assertEqual(data1["status"], "draft")

        # 6. PATCH credits
        res_c = self.client.patch(
            f"/api/v1/subjects/{self.subject_a_id}",
            json={"credits": 5},
            headers=self.manager_headers,
        )
        self.assertEqual(res_c.status_code, 200)
        self.assertEqual(res_c.get_json()["data"]["credits"], 5)

        # 7. PATCH status
        res_s = self.client.patch(
            f"/api/v1/subjects/{self.subject_a_id}",
            json={"status": "active"},
            headers=self.manager_headers,
        )
        self.assertEqual(res_s.status_code, 200)
        self.assertEqual(res_s.get_json()["data"]["status"], "active")

        # 8. PATCH description null
        res_d = self.client.patch(
            f"/api/v1/subjects/{self.subject_a_id}",
            json={"description": None},
            headers=self.manager_headers,
        )
        self.assertEqual(res_d.status_code, 200)
        self.assertIsNone(res_d.get_json()["data"]["description"])

        # 9. PUT toàn bộ subject A
        put_payload = {
            "code": f"{self.test_prefix}-SUBJA-PUT",
            "name": "Môn học A Hoàn Toàn Mới",
            "credits": 4,
            "description": "Mô tả PUT mới",
            "total_sessions": 25,
            "status": "archived",
        }
        res_put = self.client.put(
            f"/api/v1/subjects/{self.subject_a_id}",
            json=put_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res_put.status_code, 200)

        # 10. GET kiểm tra dữ liệu sau PUT
        get_res2 = self.client.get(f"/api/v1/subjects/{self.subject_a_id}", headers=self.manager_headers)
        self.assertEqual(get_res2.status_code, 200)
        data2 = get_res2.get_json()["data"]
        self.assertEqual(data2["code"], f"{self.test_prefix}-SUBJA-PUT")
        self.assertEqual(data2["name"], "Môn học A Hoàn Toàn Mới")
        self.assertEqual(data2["credits"], 4)
        self.assertEqual(data2["description"], "Mô tả PUT mới")
        self.assertEqual(data2["total_sessions"], 25)
        self.assertEqual(data2["status"], "archived")

        # 11. Xác nhận created_at giữ nguyên
        self.assertEqual(data2["created_at"], data1["created_at"])
        # 12. Xác nhận updated_at được cập nhật
        self.assertIsNotNone(data2["updated_at"])

    def test_live_13_duplicate_code_conflict_returns_409(self):
        # 13. Thử đổi code A trùng code B -> 409 DUPLICATE_CODE
        dup_payload = {"code": self.subject_b_code}
        res = self.client.patch(
            f"/api/v1/subjects/{self.subject_a_id}",
            json=dup_payload,
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_CODE")

    def test_live_14_course_view_forbidden_403(self):
        # 14. Thử user có course.view gọi PUT và PATCH -> 403 FORBIDDEN
        res_put = self.client.put(
            f"/api/v1/subjects/{self.subject_a_id}",
            json={"code": "CODE", "name": "Name", "credits": 3},
            headers=self.viewer_headers,
        )
        self.assertEqual(res_put.status_code, 403)
        self.assertEqual(res_put.get_json()["code"], "FORBIDDEN")

        res_patch = self.client.patch(
            f"/api/v1/subjects/{self.subject_a_id}",
            json={"name": "New Name"},
            headers=self.viewer_headers,
        )
        self.assertEqual(res_patch.status_code, 403)
        self.assertEqual(res_patch.get_json()["code"], "FORBIDDEN")

    def test_live_15_invalid_uuid_returns_400(self):
        # 15. Invalid UUID -> 400
        res = self.client.patch(
            "/api/v1/subjects/invalid-uuid-format-1234",
            json={"name": "A"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_PARAMS")

    def test_live_16_missing_uuid_returns_404(self):
        # 16. Missing UUID hợp lệ -> 404
        non_existent_uuid = str(uuid.uuid4())
        res = self.client.patch(
            f"/api/v1/subjects/{non_existent_uuid}",
            json={"name": "A"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "SUBJECT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
