"""
Bộ kiểm thử SCRUM-129: API nhân bản danh sách buổi học từ môn học khác
(POST /api/v1/subjects/<subject_id>/sessions/clone).

Bao quát các Test Case:
- RBAC: 401 unauthenticated, 403 viewer (course.view), 201 manager (course.manage).
- Validation:
  + TC129-CLONE-06: Target as Source -> 400 INVALID_PARAMS.
  + TC129-CLONE-07: Source không có buổi học -> 400 ("Không có buổi học để nhân bản.").
  + TC129-CLONE-04: Target max = 2, Source = 3 -> BLOCKED (TotalSessionsExceededError / 400), ALL OR NOTHING.
  + TC129-CLONE-05: Target max = 5, Target hiện có = 3, Source = 3 -> 3+3 > 5 -> BLOCKED.
- Functional & Live DB:
  + TC129-CLONE-01: Clone 3 buổi từ QA-S129-SOURCE sang QA-S129-TARGET -> TARGET = 3/3, copy đầy đủ topic, objective.
  + TC129-CLONE-02: Reload TARGET -> Dữ liệu được lưu vĩnh viễn trong MySQL.
  + TC129-CLONE-03: Kiểm tra SOURCE -> SOURCE giữ nguyên vẹn, không bị sửa đổi hay xóa.
  + Append sequential numbers: Môn đích đã có 2 buổi, clone 2 buổi -> trở thành 3, 4.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.subject import Subject
from app.models.subject_session import SubjectSession
from app.repositories import subject_repository, subject_session_repository
from app.routes.subject_session_routes import subject_session_bp
from app.services import subject_session_service


class Scrum129SubjectSessionCloneApiTests(unittest.TestCase):
    """Kiểm thử API và nghiệp vụ nhân bản danh sách buổi học SCRUM-129."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum129-clone-at-least-32-bytes",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_session_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        # Quản lý khóa học (có course.manage)
        self.manager_user_id = "user-auth-course-manage-clone"
        self.manager_session = LoginSession(
            session_id="session-manage-clone-129",
            user_id=self.manager_user_id,
            refresh_jti="ref-manage-clone-129",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        # Quyền xem (chỉ có course.view)
        self.viewer_user_id = "user-only-course-view-clone"
        self.viewer_session = LoginSession(
            session_id="session-view-clone-129",
            user_id=self.viewer_user_id,
            refresh_jti="ref-view-clone-129",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-manage-clone-129"},
            )
            self.viewer_token = create_access_token(
                identity=self.viewer_user_id,
                additional_claims={"sid": "session-view-clone-129"},
            )

        self.manager_headers = {"Authorization": f"Bearer {self.manager_token}"}
        self.viewer_headers = {"Authorization": f"Bearer {self.viewer_token}"}
        self.cleanup_subject_ids: list[str] = []

    def tearDown(self):
        if not self.cleanup_subject_ids:
            return
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                format_strings = ",".join(["%s"] * len(self.cleanup_subject_ids))
                cursor.execute(
                    f"DELETE FROM subject_sessions WHERE subject_id IN ({format_strings})",
                    tuple(self.cleanup_subject_ids),
                )
                cursor.execute(
                    f"DELETE FROM subjects WHERE id IN ({format_strings})",
                    tuple(self.cleanup_subject_ids),
                )
            conn.commit()
        finally:
            conn.close()

    def _create_db_subject(
        self, code: str, name: str, total_sessions: int | None, status: str = "active"
    ) -> Subject:
        subj_id = str(uuid.uuid4())
        subj = Subject(
            id=subj_id,
            code=code,
            name=name,
            credits=3,
            total_sessions=total_sessions,
            status=status,
        )
        subject_repository.insert_subject(subj)
        self.cleanup_subject_ids.append(subj_id)
        return subj

    def _create_db_session(
        self, subject_id: str, session_number: int, topic: str, objective: str
    ) -> SubjectSession:
        sess = SubjectSession(
            id=str(uuid.uuid4()),
            subject_id=subject_id,
            session_number=session_number,
            topic=topic,
            objective=objective,
        )
        return subject_session_repository.insert_subject_session(sess)

    # =========================================================================
    # 1. RBAC & PERMISSION TESTS
    # =========================================================================

    def test_01_unauthenticated_returns_401(self):
        valid_uuid = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{valid_uuid}/sessions/clone",
            json={"source_subject_id": str(uuid.uuid4())},
        )
        self.assertEqual(res.status_code, 401)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_02_forbidden_with_only_course_view_returns_403(
        self, mock_get_sess, mock_has_perm
    ):
        mock_get_sess.return_value = self.viewer_session
        mock_has_perm.return_value = False

        target_id = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{target_id}/sessions/clone",
            json={"source_subject_id": str(uuid.uuid4())},
            headers=self.viewer_headers,
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("code"), "FORBIDDEN")

    # =========================================================================
    # 2. VALIDATION TESTS
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_03_invalid_uuid_returns_400(self, mock_get_sess, mock_has_perm):
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # Invalid target UUID
        res = self.client.post(
            "/api/v1/subjects/not-a-uuid/sessions/clone",
            json={"source_subject_id": str(uuid.uuid4())},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

        # Invalid source UUID
        valid_uuid = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{valid_uuid}/sessions/clone",
            json={"source_subject_id": "invalid-uuid"},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "INVALID_PARAMS")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_04_target_as_source_rejected_tc129_clone_06(
        self, mock_get_sess, mock_has_perm
    ):
        """TC129-CLONE-06: Chọn chính TARGET làm SOURCE -> 400 INVALID_PARAMS."""
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        same_id = str(uuid.uuid4())
        res = self.client.post(
            f"/api/v1/subjects/{same_id}/sessions/clone",
            json={"source_subject_id": same_id},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("chính môn học", res.get_json().get("message", ""))

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_05_source_empty_rejected_tc129_clone_07(
        self, mock_get_sess, mock_has_perm
    ):
        """TC129-CLONE-07: SOURCE không có session -> không tạo dữ liệu."""
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        src = self._create_db_subject("SRC-EMPTY", "Nguồn Rỗng", total_sessions=5)
        tgt = self._create_db_subject("TGT-EMPTY", "Đích Rỗng", total_sessions=5)

        res = self.client.post(
            f"/api/v1/subjects/{tgt.id}/sessions/clone",
            json={"source_subject_id": src.id},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("buổi học để nhân bản", res.get_json().get("message", ""))

        # Đảm bảo target không bị tạo thêm session
        self.assertEqual(subject_session_repository.count_subject_sessions(tgt.id), 0)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_06_target_max_2_source_3_blocked_tc129_clone_04(
        self, mock_get_sess, mock_has_perm
    ):
        """
        TC129-CLONE-04: TARGET max = 2, SOURCE = 3 sessions
        -> BLOCKED, TARGET vẫn = 0/2, không insert một phần.
        """
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        src = self._create_db_subject("SRC-3SESS", "Nguồn 3 buổi", total_sessions=3)
        self._create_db_session(src.id, 1, "Buổi 1", "Mục tiêu 1")
        self._create_db_session(src.id, 2, "Buổi 2", "Mục tiêu 2")
        self._create_db_session(src.id, 3, "Buổi 3", "Mục tiêu 3")

        tgt = self._create_db_subject("TGT-MAX2", "Đích tối đa 2", total_sessions=2)

        res = self.client.post(
            f"/api/v1/subjects/{tgt.id}/sessions/clone",
            json={"source_subject_id": src.id},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "TOTAL_SESSIONS_EXCEEDED")
        self.assertIn("tối đa 2 buổi", res.get_json().get("message", ""))

        # TARGET vẫn = 0/2 (ALL OR NOTHING)
        self.assertEqual(subject_session_repository.count_subject_sessions(tgt.id), 0)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_07_target_max_5_current_3_source_3_blocked_tc129_clone_05(
        self, mock_get_sess, mock_has_perm
    ):
        """
        TC129-CLONE-05: TARGET max = 5, TARGET hiện có = 3, SOURCE = 3
        3 + 3 = 6 > 5 -> BLOCKED, TARGET vẫn giữ đúng 3 buổi cũ.
        """
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        src = self._create_db_subject("SRC-S5", "Nguồn S5", total_sessions=3)
        self._create_db_session(src.id, 1, "Nguồn B1", "MT 1")
        self._create_db_session(src.id, 2, "Nguồn B2", "MT 2")
        self._create_db_session(src.id, 3, "Nguồn B3", "MT 3")

        tgt = self._create_db_subject("TGT-S5", "Đích S5", total_sessions=5)
        self._create_db_session(tgt.id, 1, "Đích Cũ 1", "MT Cũ 1")
        self._create_db_session(tgt.id, 2, "Đích Cũ 2", "MT Cũ 2")
        self._create_db_session(tgt.id, 3, "Đích Cũ 3", "MT Cũ 3")

        res = self.client.post(
            f"/api/v1/subjects/{tgt.id}/sessions/clone",
            json={"source_subject_id": src.id},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json().get("code"), "TOTAL_SESSIONS_EXCEEDED")
        self.assertIn("vượt quá giới hạn của môn học", res.get_json().get("message", ""))

        # TARGET vẫn giữ đúng 3 buổi cũ ban đầu
        tgt_sessions = subject_session_repository.list_subject_sessions_by_subject(tgt.id)
        self.assertEqual(len(tgt_sessions), 3)
        self.assertEqual([s.topic for s in tgt_sessions], ["Đích Cũ 1", "Đích Cũ 2", "Đích Cũ 3"])

    # =========================================================================
    # 3. LIVE FULL WORKFLOW: TC129-CLONE-01, 02, 03
    # =========================================================================

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_08_tc129_clone_01_02_03_full_workflow(
        self, mock_get_sess, mock_has_perm
    ):
        """
        TC129-CLONE-01: TARGET = 0/3, SOURCE = 3 sessions.
        Clone SOURCE -> TARGET:
          TARGET = 3/3
          Buổi 1: Tổng quan môn học
          Buổi 2: Kiến thức nền tảng
          Buổi 3: Thực hành
          Mục tiêu được copy đầy đủ.
        TC129-CLONE-02: Reload TARGET -> 3 sessions vẫn còn trong MySQL.
        TC129-CLONE-03: Kiểm tra SOURCE -> SOURCE vẫn giữ nguyên, không bị move/delete/update.
        """
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        # Tạo SOURCE chính xác theo spec đề bài
        src = self._create_db_subject(
            code=f"QA-S129-SOURCE-{uuid.uuid4().hex[:4]}",
            name="Nguồn buổi học",
            total_sessions=3,
        )
        src_s1 = self._create_db_session(
            src.id, 1, "Tổng quan môn học", "Nắm được nội dung và mục tiêu của môn học"
        )
        src_s2 = self._create_db_session(
            src.id, 2, "Kiến thức nền tảng", "Hiểu các khái niệm cơ bản"
        )
        src_s3 = self._create_db_session(
            src.id, 3, "Thực hành", "Vận dụng kiến thức vào bài thực hành"
        )

        # Tạo TARGET ban đầu: 0 sessions, total_sessions = 3
        tgt = self._create_db_subject(
            code=f"QA-S129-TARGET-{uuid.uuid4().hex[:4]}",
            name="Nhận buổi học",
            total_sessions=3,
        )

        # Thực hiện gọi API Clone
        res = self.client.post(
            f"/api/v1/subjects/{tgt.id}/sessions/clone",
            json={"source_subject_id": src.id},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertEqual(body.get("status"), "success")
        self.assertEqual(body["data"]["cloned_count"], 3)
        self.assertEqual(body["data"]["total_sessions"], 3)

        # -------------------------------------------------------------
        # TC129-CLONE-01: Kiểm tra các buổi học ở TARGET
        # -------------------------------------------------------------
        tgt_sessions = subject_session_repository.list_subject_sessions_by_subject(tgt.id)
        self.assertEqual(len(tgt_sessions), 3)

        self.assertEqual(tgt_sessions[0].session_number, 1)
        self.assertEqual(tgt_sessions[0].topic, "Tổng quan môn học")
        self.assertEqual(
            tgt_sessions[0].objective, "Nắm được nội dung và mục tiêu của môn học"
        )
        self.assertNotEqual(tgt_sessions[0].id, src_s1.id)
        self.assertEqual(tgt_sessions[0].subject_id, tgt.id)

        self.assertEqual(tgt_sessions[1].session_number, 2)
        self.assertEqual(tgt_sessions[1].topic, "Kiến thức nền tảng")
        self.assertEqual(
            tgt_sessions[1].objective, "Hiểu các khái niệm cơ bản"
        )
        self.assertNotEqual(tgt_sessions[1].id, src_s2.id)
        self.assertEqual(tgt_sessions[1].subject_id, tgt.id)

        self.assertEqual(tgt_sessions[2].session_number, 3)
        self.assertEqual(tgt_sessions[2].topic, "Thực hành")
        self.assertEqual(
            tgt_sessions[2].objective, "Vận dụng kiến thức vào bài thực hành"
        )
        self.assertNotEqual(tgt_sessions[2].id, src_s3.id)
        self.assertEqual(tgt_sessions[2].subject_id, tgt.id)

        # -------------------------------------------------------------
        # TC129-CLONE-02: Reload TARGET qua API GET sessions
        # -------------------------------------------------------------
        res_get = self.client.get(
            f"/api/v1/subjects/{tgt.id}/sessions",
            headers=self.manager_headers,
        )
        self.assertEqual(res_get.status_code, 200)
        items = res_get.get_json()["data"]["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["topic"], "Tổng quan môn học")
        self.assertEqual(items[1]["topic"], "Kiến thức nền tảng")
        self.assertEqual(items[2]["topic"], "Thực hành")

        # -------------------------------------------------------------
        # TC129-CLONE-03: Kiểm tra SOURCE vẫn giữ nguyên vẹn
        # -------------------------------------------------------------
        src_sessions_after = subject_session_repository.list_subject_sessions_by_subject(src.id)
        self.assertEqual(len(src_sessions_after), 3)
        self.assertEqual(src_sessions_after[0].id, src_s1.id)
        self.assertEqual(src_sessions_after[0].topic, src_s1.topic)
        self.assertEqual(src_sessions_after[1].id, src_s2.id)
        self.assertEqual(src_sessions_after[1].topic, src_s2.topic)
        self.assertEqual(src_sessions_after[2].id, src_s3.id)
        self.assertEqual(src_sessions_after[2].topic, src_s3.topic)

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    def test_09_clone_append_sequential_session_numbers(
        self, mock_get_sess, mock_has_perm
    ):
        """Môn đích đã có sẵn 2 buổi (1, 2), clone 2 buổi từ nguồn -> trở thành buổi 3, 4."""
        mock_get_sess.return_value = self.manager_session
        mock_has_perm.return_value = True

        src = self._create_db_subject("SRC-SEQ", "Nguồn Seq", total_sessions=2)
        self._create_db_session(src.id, 1, "Thêm Buổi A", "MT A")
        self._create_db_session(src.id, 2, "Thêm Buổi B", "MT B")

        tgt = self._create_db_subject("TGT-SEQ", "Đích Seq", total_sessions=5)
        self._create_db_session(tgt.id, 1, "Đích Có Sẵn 1", "MT 1")
        self._create_db_session(tgt.id, 2, "Đích Có Sẵn 2", "MT 2")

        res = self.client.post(
            f"/api/v1/subjects/{tgt.id}/sessions/clone",
            json={"source_subject_id": src.id},
            headers=self.manager_headers,
        )
        self.assertEqual(res.status_code, 201)

        tgt_sessions = subject_session_repository.list_subject_sessions_by_subject(tgt.id)
        self.assertEqual(len(tgt_sessions), 4)
        self.assertEqual([s.session_number for s in tgt_sessions], [1, 2, 3, 4])
        self.assertEqual(tgt_sessions[2].topic, "Thêm Buổi A")
        self.assertEqual(tgt_sessions[3].topic, "Thêm Buổi B")


if __name__ == "__main__":
    unittest.main()
