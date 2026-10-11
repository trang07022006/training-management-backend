"""
Bộ kiểm thử SCRUM-129 (Activity A2): API xem danh sách và chi tiết các buổi học của môn học (SCRUM-174).
Endpoints:
- GET /api/v1/subjects/<subject_id>/sessions và alias /api/subjects/<subject_id>/sessions
- GET /api/v1/subjects/<subject_id>/sessions/<session_id> và alias /api/subjects/<subject_id>/sessions/<session_id>

Bao quát toàn diện:
1. Authentication (401 unauthenticated, 401 invalid token).
2. RBAC (403 thiếu quyền 'course.view', 200 có quyền 'course.view').
3. Validation (400 INVALID_PARAMS khi subject_id hoặc session_id không đúng định dạng UUID).
4. Resource Lookup (404 SUBJECT_NOT_FOUND khi môn học không tồn tại).
5. Empty List & Multiple Sessions (Trả về subject summary + items được sắp xếp theo session_number ASC).
6. Detail Lookup (404 SUBJECT_SESSION_NOT_FOUND khi session_id không tồn tại hoặc thuộc môn học khác - Chống IDOR).
7. Error Handling (500 DATABASE_ERROR khi xảy ra sự cố cơ sở dữ liệu).
8. Alias routes.
9. Live MySQL integration test với tiền tố SESS-A2- và dọn dẹp sạch sẽ.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mysql.connector import Error as MySQLError

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.subject import Subject
from app.models.subject_session import SubjectSession
from app.repositories import subject_repository, subject_session_repository
from app.routes.subject_session_routes import subject_session_bp
from app.services import subject_session_service


class Scrum129SubjectSessionReadApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API đọc buổi học của môn học."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum129-a2-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_session_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.authorized_user_id = "user-auth-course-view"
        self.authorized_session = LoginSession(
            session_id="session-auth-course-view",
            user_id=self.authorized_user_id,
            refresh_jti="ref-auth-129",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        self.forbidden_user_id = "user-no-course-view"
        self.forbidden_session = LoginSession(
            session_id="session-forbidden-129",
            user_id=self.forbidden_user_id,
            refresh_jti="ref-forbid-129",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.authorized_token = create_access_token(
                identity=self.authorized_user_id,
                additional_claims={"sid": "session-auth-course-view"},
            )
            self.forbidden_token = create_access_token(
                identity=self.forbidden_user_id,
                additional_claims={"sid": "session-forbidden-129"},
            )

        self.auth_headers = {"Authorization": f"Bearer {self.authorized_token}"}
        self.forbidden_headers = {"Authorization": f"Bearer {self.forbidden_token}"}

    def test_01_unauthenticated_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.get(f"/api/v1/subjects/{valid_uuid}/sessions")
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    def test_02_invalid_token_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/subjects/{valid_uuid}/sessions",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get("code"), "UNAUTHORIZED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_forbidden_without_course_view_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.forbidden_session
        mock_has_perm.return_value = False

        valid_uuid = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/subjects/{valid_uuid}/sessions",
            headers=self.forbidden_headers,
        )
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertEqual(data.get("code"), "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_invalid_subject_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        res = self.client.get(
            "/api/v1/subjects/not-a-valid-uuid/sessions",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_05_subject_not_found_returns_404(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_subj.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/subjects/{valid_uuid}/sessions",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("code"), "SUBJECT_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_06_empty_sessions_list_success(self, mock_get_subj, mock_list_sess, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id,
            code="SUBJ-001",
            name="Môn học 1",
            credits=3,
            total_sessions=15,
            status="active",
        )
        mock_list_sess.return_value = []

        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("subject", {}).get("code"), "SUBJ-001")
        self.assertEqual(data.get("subject", {}).get("total_sessions"), 15)
        self.assertEqual(data.get("items"), [])

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_07_multiple_sessions_list_ordering(self, mock_get_subj, mock_list_sess, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id,
            code="SUBJ-002",
            name="Môn học 2",
            credits=2,
            total_sessions=10,
            status="active",
        )
        mock_list_sess.return_value = [
            SubjectSession(
                id=str(uuid.uuid4()),
                subject_id=subj_id,
                session_number=1,
                topic="Buổi 1: Giới thiệu",
                objective="Mục tiêu 1",
            ),
            SubjectSession(
                id=str(uuid.uuid4()),
                subject_id=subj_id,
                session_number=2,
                topic="Buổi 2: Lý thuyết cơ bản",
                objective="Mục tiêu 2",
            ),
        ]

        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        items = data.get("items", [])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["session_number"], 1)
        self.assertEqual(items[1]["session_number"], 2)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_invalid_session_uuid_detail_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions/not-a-valid-session-id",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_09_session_detail_subject_not_found_returns_404(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_subj.return_value = None

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("code"), "SUBJECT_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_10_session_detail_not_found_returns_404(self, mock_get_subj, mock_get_sess_rep, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-003", name="Môn 3", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = None

        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("code"), "SUBJECT_SESSION_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_11_cross_subject_session_access_prevented_idor(self, mock_get_subj, mock_get_sess_rep, mock_get_sess, mock_has_perm):
        """Buổi học thuộc môn A nhưng bị gọi qua URL của môn B phải trả về 404 (chống IDOR)."""
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_b_id = str(uuid.uuid4())
        subj_a_id = str(uuid.uuid4())
        sess_a_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_b_id, code="SUBJ-B", name="Môn B", credits=3, total_sessions=10, status="active"
        )
        # Session A thuộc subject A
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_a_id,
            subject_id=subj_a_id,
            session_number=1,
            topic="Buổi của môn A",
            objective="Mục tiêu của môn A",
        )

        res = self.client.get(
            f"/api/v1/subjects/{subj_b_id}/sessions/{sess_a_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data.get("code"), "SUBJECT_SESSION_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_12_session_detail_success(self, mock_get_subj, mock_get_sess_rep, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-004", name="Môn 4", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_id,
            subject_id=subj_id,
            session_number=3,
            topic="Buổi 3: Cấu trúc điều khiển",
            objective="Nắm vững điều khiển luồng",
        )

        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("data", {}).get("session_number"), 3)
        self.assertEqual(data.get("data", {}).get("topic"), "Buổi 3: Cấu trúc điều khiển")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_13_database_error_returns_500(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True
        mock_get_subj.side_effect = MySQLError("Database connection dropped")

        subj_id = str(uuid.uuid4())
        res = self.client.get(
            f"/api/v1/subjects/{subj_id}/sessions",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertEqual(data.get("code"), "DATABASE_ERROR")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_14_alias_route_works(self, mock_get_subj, mock_list_sess, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.authorized_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-ALIAS", name="Môn Alias", credits=3, total_sessions=5, status="active"
        )
        mock_list_sess.return_value = []

        res = self.client.get(
            f"/api/subjects/{subj_id}/sessions",
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)


class Scrum129SubjectSessionReadApiLiveMySQLTests(unittest.TestCase):
    """Kiểm thử tích hợp MySQL thật cho API đọc buổi học (prefix SESS-A2-)."""

    def setUp(self):
        self.subject_id = str(uuid.uuid4())
        self.subject_code = f"SESS-A2-{uuid.uuid4().hex[:6]}"
        subj = Subject(
            id=self.subject_id,
            code=self.subject_code,
            name="Môn học kiểm thử Live A2",
            credits=3,
            total_sessions=10,
            status="active",
        )
        subject_repository.insert_subject(subj)

        self.session_1_id = str(uuid.uuid4())
        self.session_2_id = str(uuid.uuid4())

        subject_session_repository.insert_subject_session(
            SubjectSession(
                id=self.session_1_id,
                subject_id=self.subject_id,
                session_number=1,
                topic="Buổi 1 Live",
                objective="Mục tiêu 1 Live",
            )
        )
        subject_session_repository.insert_subject_session(
            SubjectSession(
                id=self.session_2_id,
                subject_id=self.subject_id,
                session_number=2,
                topic="Buổi 2 Live",
                objective="Mục tiêu 2 Live",
            )
        )

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM subject_sessions WHERE subject_id = %s", (self.subject_id,))
                cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            conn.commit()
        finally:
            conn.close()

    def test_live_mysql_get_subject_sessions_list_and_detail(self):
        # 1. Test get_subject_sessions_service
        data = subject_session_service.get_subject_sessions_service(self.subject_id)
        self.assertEqual(data["subject"]["code"], self.subject_code)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["session_number"], 1)
        self.assertEqual(data["items"][1]["session_number"], 2)

        # 2. Test get_subject_session_detail_service
        detail_1 = subject_session_service.get_subject_session_detail_service(
            self.subject_id, self.session_1_id
        )
        self.assertEqual(detail_1["topic"], "Buổi 1 Live")

        # 3. Test IDOR protection with different subject
        other_subject_id = str(uuid.uuid4())
        other_subj = Subject(
            id=other_subject_id,
            code=f"SESS-A2-OTHER-{uuid.uuid4().hex[:4]}",
            name="Môn khác",
            credits=2,
            total_sessions=5,
            status="active",
        )
        subject_repository.insert_subject(other_subj)
        try:
            with self.assertRaises(subject_session_service.SubjectSessionNotFoundError):
                subject_session_service.get_subject_session_detail_service(
                    other_subject_id, self.session_1_id
                )
        finally:
            conn = get_db_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM subjects WHERE id = %s", (other_subject_id,))
                conn.commit()
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
