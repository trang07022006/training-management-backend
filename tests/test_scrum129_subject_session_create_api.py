"""
Bộ kiểm thử SCRUM-129 (Activity A3): API thêm buổi học mới (POST /api/v1/subjects/<subject_id>/sessions).
Endpoints:
- POST /api/v1/subjects/<subject_id>/sessions và alias /api/subjects/<subject_id>/sessions

Bao quát toàn diện:
1. Authentication (401 unauthenticated, 401 invalid token).
2. RBAC (403 chỉ có 'course.view', 201 có 'course.manage').
3. Validation subject (400 INVALID_PARAMS khi UUID sai, 404 SUBJECT_NOT_FOUND khi không tồn tại, 400 SUBJECT_ARCHIVED khi môn đã lưu trữ).
4. Validation session_number (bắt buộc, số nguyên, không bool, không float, không string, >= 1).
5. Validation total_sessions (nếu total_sessions != None thì session_number <= total_sessions; nếu total_sessions == None thì không giới hạn; nếu total_sessions == 0 thì chặn).
6. Validation topic & objective (bắt buộc, không rỗng, giới hạn độ dài 255 và 5000 ký tự).
7. Duplicate check (409 DUPLICATE_SESSION_NUMBER cùng môn học; khác môn học cùng số thứ tự cho phép).
8. Server-controlled fields (id, created_at, updated_at do server quản lý, không bị client ghi đè).
9. Race condition DB error 1062 chuyển thành 409 DUPLICATE_SESSION_NUMBER.
10. Database error 500.
11. Header Location trong phản hồi 201 Created.
12. Live MySQL integration test với prefix SESS-A3-.
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
from app.models.subject import Subject
from app.models.subject_session import SubjectSession
from app.repositories import subject_repository, subject_session_repository
from app.routes.subject_session_routes import subject_session_bp
from app.services import subject_session_service


class Scrum129SubjectSessionCreateApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API thêm buổi học."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum129-a3-at-least-32-bytes-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_session_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Quản lý khóa học (có course.manage)
        self.manager_user_id = "user-auth-course-manage"
        self.manager_session = LoginSession(
            session_id="session-auth-course-manage",
            user_id=self.manager_user_id,
            refresh_jti="ref-manage-129",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Chỉ có quyền xem (course.view)
        self.viewer_user_id = "user-only-course-view"
        self.viewer_session = LoginSession(
            session_id="session-viewer-129",
            user_id=self.viewer_user_id,
            refresh_jti="ref-view-129",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-auth-course-manage"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-viewer-129"},
            )

        self.manager_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.viewer_headers = {"Authorization": f"Bearer {self.viewer_token}"}

    def test_01_unauthenticated_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{valid_uuid}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
        )
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_forbidden_with_only_course_view_returns_403(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False

        valid_uuid = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{valid_uuid}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("code"), "FORBIDDEN")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_invalid_subject_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        res = self.client.post(
            "/api/v1/subjects/not-a-valid-uuid/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_04_subject_not_found_returns_404(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True
        mock_get_subj.return_value = None

        valid_uuid = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{valid_uuid}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json().get("code"), "SUBJECT_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_05_archived_subject_returns_400(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-ARCHIVED", name="Môn lưu trữ", credits=3, total_sessions=10, status="archived"
        )

        res = self.client.post(
            f"/api/v1/subjects/{subj_id}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "SUBJECT_ARCHIVED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_06_session_number_validation_types_and_ranges(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-ACTIVE", name="Môn hoạt động", credits=3, total_sessions=10, status="active"
        )

        invalid_numbers = [
            0,             # < 1
            -1,            # âm
            1.5,           # float
            True,          # bool
            False,         # bool
            "1",           # string
            None,          # None
        ]

        for num in invalid_numbers:
            res = self.client.post(
                f"/api/v1/subjects/{subj_id}/sessions",
                json={"session_number": num, "topic": "Chủ đề", "objective": "Mục tiêu"},
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400, f"Expected 400 for session_number={num}")
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_07_session_number_exceeds_total_sessions(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-LIMIT", name="Môn giới hạn", credits=3, total_sessions=5, status="active"
        )

        res = self.client.post(
            f"/api/v1/subjects/{subj_id}/sessions",
            json={"session_number": 6, "topic": "Chủ đề 6", "objective": "Mục tiêu 6"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "TOTAL_SESSIONS_EXCEEDED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_08_total_sessions_zero_rejects_session(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-ZERO", name="Môn 0 buổi", credits=3, total_sessions=0, status="active"
        )

        res = self.client.post(
            f"/api/v1/subjects/{subj_id}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "TOTAL_SESSIONS_EXCEEDED")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_09_topic_and_objective_validations(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-VALIDATE", name="Môn kiểm tra", credits=3, total_sessions=10, status="active"
        )

        # Topic trống / None / quá dài
        invalid_topics = ["", "   ", None, "A" * 256]
        for t in invalid_topics:
            res = self.client.post(
                f"/api/v1/subjects/{subj_id}/sessions",
                json={"session_number": 1, "topic": t, "objective": "Mục tiêu hợp lệ"},
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

        # Objective trống / None / quá dài
        invalid_objs = ["", "   ", None, "B" * 5001]
        for obj in invalid_objs:
            res = self.client.post(
                f"/api/v1/subjects/{subj_id}/sessions",
                json={"session_number": 1, "topic": "Chủ đề hợp lệ", "objective": obj},
                headers=self.manager_headers,
            )
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.exists_session_number")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_10_duplicate_session_number_returns_409(self, mock_get_subj, mock_exists, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-DUP", name="Môn trùng", credits=3, total_sessions=10, status="active"
        )
        mock_exists.return_value = True

        res = self.client.post(
            f"/api/v1/subjects/{subj_id}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "DUPLICATE_SESSION_NUMBER")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.insert_subject_session")
    @patch("app.repositories.subject_session_repository.exists_session_number")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_11_create_session_success_and_location_header(
        self, mock_get_subj, mock_exists, mock_insert, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-OK", name="Môn thành công", credits=3, total_sessions=None, status="active"
        )
        mock_exists.return_value = False

        created_id = str(uuid.uuid4())
        mock_insert.side_effect = lambda s: SubjectSession(
            id=created_id,
            subject_id=subj_id,
            session_number=s.session_number,
            topic=s.topic,
            objective=s.objective,
        )

        res = self.client.post(
            f"/api/v1/subjects/{subj_id}/sessions",
            json={
                "id": "malicious-id",
                "subject_id": "malicious-subject",
                "session_number": 1,
                "topic": "  Giới thiệu môn học  ",
                "objective": "  Nắm mục tiêu môn  ",
            },
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("data", {}).get("session_number"), 1)
        self.assertEqual(data.get("data", {}).get("topic"), "Giới thiệu môn học")
        self.assertEqual(data.get("data", {}).get("objective"), "Nắm mục tiêu môn")
        self.assertNotEqual(data.get("data", {}).get("id"), "malicious-id")
        self.assertEqual(data.get("data", {}).get("subject_id"), subj_id)

        # Location header
        location = res.headers.get("Location")
        self.assertIsNotNone(location)
        self.assertTrue(location.endswith(f"/sessions/{created_id}"))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.insert_subject_session")
    @patch("app.repositories.subject_session_repository.exists_session_number")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_12_db_race_duplicate_key_returns_409(
        self, mock_get_subj, mock_exists, mock_insert, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-RACE", name="Môn race", credits=3, total_sessions=10, status="active"
        )
        mock_exists.return_value = False
        mock_insert.side_effect = IntegrityError(1062, "Duplicate entry 'x-1' for key 'uq_subject_sessions_number'")

        res = self.client.post(
            f"/api/v1/subjects/{subj_id}/sessions",
            json={"session_number": 1, "topic": "Chủ đề", "objective": "Mục tiêu"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json().get("code"), "DUPLICATE_SESSION_NUMBER")


class Scrum129SubjectSessionCreateApiLiveMySQLTests(unittest.TestCase):
    """Kiểm thử tích hợp MySQL thật cho API thêm buổi học (prefix SESS-A3-)."""

    def setUp(self):
        self.subject_a_id = str(uuid.uuid4())
        self.subject_b_id = str(uuid.uuid4())

        subj_a = Subject(
            id=self.subject_a_id,
            code=f"SESS-A3-A-{uuid.uuid4().hex[:6]}",
            name="Môn Live A3 A",
            credits=3,
            total_sessions=3,
            status="active",
        )
        subj_b = Subject(
            id=self.subject_b_id,
            code=f"SESS-A3-B-{uuid.uuid4().hex[:6]}",
            name="Môn Live A3 B",
            credits=3,
            total_sessions=None,
            status="active",
        )
        subject_repository.insert_subject(subj_a)
        subject_repository.insert_subject(subj_b)

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM subject_sessions WHERE subject_id IN (%s, %s)", (self.subject_a_id, self.subject_b_id))
                cursor.execute("DELETE FROM subjects WHERE id IN (%s, %s)", (self.subject_a_id, self.subject_b_id))
            conn.commit()
        finally:
            conn.close()

    def test_live_create_and_constraints(self):
        # 1. Tạo session 1 cho môn A
        sess1 = subject_session_service.create_subject_session_service(
            self.subject_a_id,
            {"session_number": 1, "topic": "Live Buổi 1", "objective": "Mục tiêu Live 1"},
        )
        self.assertEqual(sess1["session_number"], 1)

        # 2. Tạo session 1 cho môn B (cùng số thứ tự khác môn học -> Cho phép)
        sess_b1 = subject_session_service.create_subject_session_service(
            self.subject_b_id,
            {"session_number": 1, "topic": "Live B Buổi 1", "objective": "Mục tiêu B Live 1"},
        )
        self.assertEqual(sess_b1["session_number"], 1)

        # 3. Trùng session 1 trong môn A -> 409 DUPLICATE_SESSION_NUMBER
        with self.assertRaises(subject_session_service.DuplicateSessionNumberError):
            subject_session_service.create_subject_session_service(
                self.subject_a_id,
                {"session_number": 1, "topic": "Live Buổi 1 Trùng", "objective": "Mục tiêu"},
            )

        # 4. Session 4 vượt quá total_sessions=3 của môn A -> 400 TOTAL_SESSIONS_EXCEEDED
        with self.assertRaises(subject_session_service.TotalSessionsExceededError):
            subject_session_service.create_subject_session_service(
                self.subject_a_id,
                {"session_number": 4, "topic": "Live Buổi 4", "objective": "Mục tiêu"},
            )

        # 5. Môn B có total_sessions=None nên session 10 được phép
        sess_b10 = subject_session_service.create_subject_session_service(
            self.subject_b_id,
            {"session_number": 10, "topic": "Live B Buổi 10", "objective": "Mục tiêu B Live 10"},
        )
        self.assertEqual(sess_b10["session_number"], 10)


if __name__ == "__main__":
    unittest.main()
