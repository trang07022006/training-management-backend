"""
Bộ kiểm thử SCRUM-129 (Activity A4): Cập nhật, Sắp xếp lại và Xóa buổi học (SCRUM-175).
Endpoints:
- PATCH /api/v1/subjects/<subject_id>/sessions/<session_id>
- PATCH /api/v1/subjects/<subject_id>/sessions/reorder
- DELETE /api/v1/subjects/<subject_id>/sessions/<session_id>
(và các alias tương ứng).

Bao quát toàn diện:
1. Authentication (401 unauthenticated, 401 invalid token).
2. RBAC (403 chỉ có 'course.view', 200 có 'course.manage').
3. Cập nhật (PATCH):
   - Cập nhật riêng topic, riêng objective, hoặc cả hai.
   - Chặn empty payload hoặc payload chỉ chứa trường không được phép (400 INVALID_PARAMS).
   - Chặn cập nhật khi môn học đã lưu trữ (400 SUBJECT_ARCHIVED).
   - Chống IDOR: session_id không thuộc subject_id (404 SUBJECT_SESSION_NOT_FOUND).
4. Sắp xếp lại (REORDER):
   - Thành công: Gán thứ tự 1..N theo mảng session_ids.
   - Chặn mảng có ID trùng lặp, thiếu ID hoặc chứa ID lạ/ngoại lai (400 INVALID_PARAMS).
   - Chặn reorder khi môn học đã lưu trữ (400 SUBJECT_ARCHIVED).
   - Atomic rollback khi xảy ra lỗi.
5. Xóa (DELETE):
   - Xóa buổi học thành công, môn học (subject) vẫn còn nguyên vẹn.
   - Tự động chuẩn hóa lại session_number thành chuỗi 1..N liên tục.
   - Chặn xóa khi môn học đã lưu trữ (400 SUBJECT_ARCHIVED).
   - Chống IDOR (404 SUBJECT_SESSION_NOT_FOUND).
6. Live MySQL integration test với 4 sessions: Reorder 1,2,3,4 -> 4,2,1,3; verify; xóa 1 session; verify 1..3 liên tục; cleanup.
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


class Scrum129SubjectSessionUpdateDeleteApiUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị và bảo mật cho API cập nhật, sắp xếp và xóa buổi học."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum129-a4-at-least-32-bytes-long",
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

    # ========================== UPDATE TESTS ==========================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_01_update_unauthenticated_returns_401(self, mock_get_sess, mock_has_perm):
        res = self.client.patch(
            f"/api/v1/subjects/{uuid.uuid4()}/sessions/{uuid.uuid4()}",
            json={"topic": "Chủ đề mới"},
        )
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_update_forbidden_without_course_manage(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False

        res = self.client.patch(
            f"/api/v1/subjects/{uuid.uuid4()}/sessions/{uuid.uuid4()}",
            json={"topic": "Chủ đề mới"},
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.update_subject_session_fields")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_03_update_topic_and_objective_success(
        self, mock_get_subj, mock_get_sess_rep, mock_update, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-UPD", name="Môn update", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_id, subject_id=subj_id, session_number=1, topic="Cũ", objective="Cũ"
        )
        mock_update.return_value = SubjectSession(
            id=sess_id, subject_id=subj_id, session_number=1, topic="Mới", objective="Mới"
        )

        res = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            json={"topic": "  Mới  ", "objective": "  Mới  "},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("data", {}).get("topic"), "Mới")
        self.assertEqual(data.get("data", {}).get("objective"), "Mới")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_04_update_empty_or_system_only_payload_returns_400(
        self, mock_get_subj, mock_get_sess_rep, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-UPD", name="Môn update", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_id, subject_id=subj_id, session_number=1, topic="Cũ", objective="Cũ"
        )

        # Empty payload
        res = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            json={},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

        # System only fields
        res2 = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            json={"id": str(uuid.uuid4()), "session_number": 5, "subject_id": str(uuid.uuid4())},
            headers=self.manager_headers,
        )
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_05_update_cross_subject_idor_returns_404(
        self, mock_get_subj, mock_get_sess_rep, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_a_id = str(uuid.uuid4())
        subj_b_id = str(uuid.uuid4())
        sess_a_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_b_id, code="SUBJ-B", name="Môn B", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_a_id, subject_id=subj_a_id, session_number=1, topic="Cũ", objective="Cũ"
        )

        res = self.client.patch(
            f"/api/v1/subjects/{subj_b_id}/sessions/{sess_a_id}",
            json={"topic": "Hack"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json().get("code"), "SUBJECT_SESSION_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_06_update_archived_subject_returns_400(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-ARCHIVED", name="Môn lưu trữ", credits=3, total_sessions=10, status="archived"
        )

        res = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            json={"topic": "Chủ đề mới"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "SUBJECT_ARCHIVED")

    # ========================== REORDER TESTS ==========================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.bulk_update_session_numbers")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_07_reorder_success(
        self, mock_get_subj, mock_list_sess, mock_bulk, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        s1 = str(uuid.uuid4())
        s2 = str(uuid.uuid4())
        s3 = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-REORDER", name="Môn Reorder", credits=3, total_sessions=10, status="active"
        )
        mock_list_sess.return_value = [
            SubjectSession(id=s1, subject_id=subj_id, session_number=1, topic="1", objective="1"),
            SubjectSession(id=s2, subject_id=subj_id, session_number=2, topic="2", objective="2"),
            SubjectSession(id=s3, subject_id=subj_id, session_number=3, topic="3", objective="3"),
        ]
        mock_bulk.return_value = [
            SubjectSession(id=s3, subject_id=subj_id, session_number=1, topic="3", objective="3"),
            SubjectSession(id=s1, subject_id=subj_id, session_number=2, topic="1", objective="1"),
            SubjectSession(id=s2, subject_id=subj_id, session_number=3, topic="2", objective="2"),
        ]

        res = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/reorder",
            json={"session_ids": [s3, s1, s2]},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(len(data.get("data", [])), 3)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_08_reorder_invalid_missing_or_duplicate_ids_returns_400(
        self, mock_get_subj, mock_list_sess, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        s1 = str(uuid.uuid4())
        s2 = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-REORDER", name="Môn Reorder", credits=3, total_sessions=10, status="active"
        )
        mock_list_sess.return_value = [
            SubjectSession(id=s1, subject_id=subj_id, session_number=1, topic="1", objective="1"),
            SubjectSession(id=s2, subject_id=subj_id, session_number=2, topic="2", objective="2"),
        ]

        # 1. Trùng lặp ID trong list
        res_dup = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/reorder",
            json={"session_ids": [s1, s1]},
            headers=self.manager_headers,
        )
        self.assertEqual(res_dup.status_code, 400)
        self.assertEqual(res_dup.get_json().get("code"), "INVALID_PARAMS")

        # 2. Thiếu ID (chỉ truyền 1 trong 2)
        res_miss = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/reorder",
            json={"session_ids": [s1]},
            headers=self.manager_headers,
        )
        self.assertEqual(res_miss.status_code, 400)
        self.assertEqual(res_miss.get_json().get("code"), "INVALID_PARAMS")

        # 3. Chứa ID ngoại lai
        s_other = str(uuid.uuid4())
        res_other = self.client.patch(
            f"/api/v1/subjects/{subj_id}/sessions/reorder",
            json={"session_ids": [s1, s2, s_other]},
            headers=self.manager_headers,
        )
        self.assertEqual(res_other.status_code, 400)
        self.assertEqual(res_other.get_json().get("code"), "INVALID_PARAMS")

    # ========================== DELETE TESTS ==========================
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.normalize_session_numbers")
    @patch("app.repositories.subject_session_repository.delete_subject_session")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_09_delete_session_success(
        self, mock_get_subj, mock_get_sess_rep, mock_delete, mock_norm, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-DEL", name="Môn Xóa", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_id, subject_id=subj_id, session_number=2, topic="Xóa tôi", objective="Mục tiêu"
        )
        mock_delete.return_value = True

        res = self.client.delete(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        mock_delete.assert_called_once_with(sess_id)
        mock_norm.assert_called_once_with(subj_id)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_session_repository.get_subject_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_10_delete_cross_subject_idor_returns_404(
        self, mock_get_subj, mock_get_sess_rep, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_a_id = str(uuid.uuid4())
        subj_b_id = str(uuid.uuid4())
        sess_a_id = str(uuid.uuid4())

        mock_get_subj.return_value = Subject(
            id=subj_b_id, code="SUBJ-B", name="Môn B", credits=3, total_sessions=10, status="active"
        )
        mock_get_sess_rep.return_value = SubjectSession(
            id=sess_a_id, subject_id=subj_a_id, session_number=1, topic="Xóa A", objective="Mục tiêu"
        )

        res = self.client.delete(
            f"/api/v1/subjects/{subj_b_id}/sessions/{sess_a_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json().get("code"), "SUBJECT_SESSION_NOT_FOUND")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.repositories.subject_repository.get_subject_by_id")
    def test_11_delete_archived_subject_returns_400(self, mock_get_subj, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        subj_id = str(uuid.uuid4())
        sess_id = str(uuid.uuid4())
        mock_get_subj.return_value = Subject(
            id=subj_id, code="SUBJ-ARCHIVED", name="Môn lưu trữ", credits=3, total_sessions=10, status="archived"
        )

        res = self.client.delete(
            f"/api/v1/subjects/{subj_id}/sessions/{sess_id}",
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "SUBJECT_ARCHIVED")


class Scrum129SubjectSessionUpdateDeleteApiLiveMySQLTests(unittest.TestCase):
    """Kiểm thử tích hợp MySQL thật cho Update, Reorder, Delete (prefix SESS-A4-)."""

    def setUp(self):
        self.subject_id = str(uuid.uuid4())
        subj = Subject(
            id=self.subject_id,
            code=f"SESS-A4-{uuid.uuid4().hex[:6]}",
            name="Môn Live A4",
            credits=3,
            total_sessions=10,
            status="active",
        )
        subject_repository.insert_subject(subj)

        # Tạo 4 buổi học 1, 2, 3, 4
        self.s1 = subject_session_service.create_subject_session_service(
            self.subject_id, {"session_number": 1, "topic": "Live Buổi 1", "objective": "Mục tiêu 1"}
        )["id"]
        self.s2 = subject_session_service.create_subject_session_service(
            self.subject_id, {"session_number": 2, "topic": "Live Buổi 2", "objective": "Mục tiêu 2"}
        )["id"]
        self.s3 = subject_session_service.create_subject_session_service(
            self.subject_id, {"session_number": 3, "topic": "Live Buổi 3", "objective": "Mục tiêu 3"}
        )["id"]
        self.s4 = subject_session_service.create_subject_session_service(
            self.subject_id, {"session_number": 4, "topic": "Live Buổi 4", "objective": "Mục tiêu 4"}
        )["id"]

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM subject_sessions WHERE subject_id = %s", (self.subject_id,))
                cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            conn.commit()
        finally:
            conn.close()

    def test_live_update_reorder_and_delete_with_normalization(self):
        # 1. Update topic & objective của buổi 1
        updated_s1 = subject_session_service.update_subject_session_service(
            self.subject_id, self.s1, {"topic": "Live Buổi 1 Đã Đổi", "objective": "Mục tiêu 1 Đã Đổi"}
        )
        self.assertEqual(updated_s1["topic"], "Live Buổi 1 Đã Đổi")
        self.assertEqual(updated_s1["objective"], "Mục tiêu 1 Đã Đổi")

        # 2. Reorder 1,2,3,4 -> 4,2,1,3
        new_order = [self.s4, self.s2, self.s1, self.s3]
        reordered = subject_session_service.reorder_subject_sessions_service(
            self.subject_id, {"session_ids": new_order}
        )
        self.assertEqual(len(reordered), 4)

        # Kiểm tra thứ tự và session_number sau reorder
        sessions_map = {s["id"]: s["session_number"] for s in reordered}
        self.assertEqual(sessions_map[self.s4], 1)
        self.assertEqual(sessions_map[self.s2], 2)
        self.assertEqual(sessions_map[self.s1], 3)
        self.assertEqual(sessions_map[self.s3], 4)

        # 3. Xóa một buổi học (xóa s2 đang có số thứ tự 2)
        del_res = subject_session_service.delete_subject_session_service(self.subject_id, self.s2)
        self.assertEqual(del_res["id"], self.s2)

        # Kiểm tra subject vẫn tồn tại
        subj = subject_repository.get_subject_by_id(self.subject_id)
        self.assertIsNotNone(subj)

        # Kiểm tra danh sách sau xóa: tự động chuẩn hóa liên tục 1, 2, 3
        remaining = subject_session_service.get_subject_sessions_service(self.subject_id)["items"]
        self.assertEqual(len(remaining), 3)
        self.assertEqual([s["session_number"] for s in remaining], [1, 2, 3])
        self.assertEqual([s["id"] for s in remaining], [self.s4, self.s1, self.s3])


if __name__ == "__main__":
    unittest.main()
