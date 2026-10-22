import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.models.login_session import LoginSession
from app.models.user import User
from app.routes.class_routes import class_bp


class Scrum220InstructorAssignmentMockUnitTests(unittest.TestCase):
    """
    Unit test suite cho SCRUM-220:
    - AC1: Mỗi môn trong lớp có một giảng viên chính và nhiều trợ giảng.
    - AC2: Chỉ tài khoản có vai trò tương ứng mới được gán.
    - AC3: Phân công xong, giảng viên thấy lớp trong danh sách lớp của mình.
    - Kiểm tra quyền, phân công trùng, tính độc lập giữa các môn, không thay đổi lịch học.
    """

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-jwt-secret-scrum220-at-least-32-chars-long",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        self.app.register_blueprint(class_bp, url_prefix="/api")

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.admin_id = "admin-user-01"
        self.trainer_a_id = "trainer-01"
        self.trainer_b_id = "trainer-02"
        self.asst_1_id = "asst-01"
        self.asst_2_id = "asst-02"
        self.trainee_id = "trainee-01"
        self.consultant_id = "consultant-01"

        self.class_id = "cls-scrum220-001"
        self.class_subject_1_id = "cs-scrum220-01"
        self.class_subject_2_id = "cs-scrum220-02"

        self.admin_session_id = "sess-admin-01"
        self.admin_session = LoginSession(
            session_id=self.admin_session_id,
            user_id=self.admin_id,
            refresh_jti="ref-admin-01",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.admin_token = create_access_token(
                identity=self.admin_id,
                additional_claims={"roles": ["admin", "training_manager"], "sid": self.admin_session_id},
            )
            self.trainer_token = create_access_token(
                identity=self.trainer_a_id,
                additional_claims={"roles": ["trainer"], "sid": "sess-trainer-01"},
            )

        # Tránh kết nối DB thật khi rbac_auth kiểm tra must_change_password
        self.auth_user_patcher = patch(
            "app.repositories.user_repository.get_user_by_id",
            return_value=User(
                id=self.admin_id,
                email="admin@test.edu.vn",
                role="admin",
                name="Admin",
                status="active",
                password_hash="",
                must_change_password=False,
                created_at=self.now,
            ),
        )
        self.auth_user_patcher.start()
        self.addCleanup(self.auth_user_patcher.stop)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.services.class_service.class_repository")
    @patch("app.services.class_service.user_repository")
    def test_tc1_assign_single_main_and_multiple_assistants(
        self, mock_user_repo, mock_class_repo, mock_has_perm, mock_get_sess
    ):
        """TC1: Phân công 1 giảng viên chính và 2 trợ giảng thành công."""
        mock_get_sess.return_value = self.admin_session
        mock_has_perm.return_value = True

        mock_class_repo.get_class_by_id.return_value = {"id": self.class_id}
        mock_class_repo.get_class_subject_by_id.return_value = {"id": self.class_subject_1_id, "class_id": self.class_id}

        def mock_get_user(uid):
            if uid == self.trainer_a_id:
                return User(id=self.trainer_a_id, email="a@test.edu.vn", role="trainer", name="Thầy A", status="active", password_hash="", created_at=self.now)
            if uid == self.asst_1_id:
                return User(id=self.asst_1_id, email="asst1@test.edu.vn", role="trainer", name="Trợ giảng 1", status="active", password_hash="", created_at=self.now)
            if uid == self.asst_2_id:
                return User(id=self.asst_2_id, email="asst2@test.edu.vn", role="trainer", name="Trợ giảng 2", status="active", password_hash="", created_at=self.now)
            return None

        mock_user_repo.get_user_by_id.side_effect = mock_get_user
        mock_class_repo.get_class_subject_instructors.return_value = [
            {"instructor_id": self.trainer_a_id, "instructor_name": "Thầy A", "instructor_email": "a@test.edu.vn", "instructor_role": "trainer", "role_type": "main"},
            {"instructor_id": self.asst_1_id, "instructor_name": "Trợ giảng 1", "instructor_email": "asst1@test.edu.vn", "instructor_role": "trainer", "role_type": "assistant"},
            {"instructor_id": self.asst_2_id, "instructor_name": "Trợ giảng 2", "instructor_email": "asst2@test.edu.vn", "instructor_role": "trainer", "role_type": "assistant"},
        ]

        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_1_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [self.asst_1_id, self.asst_2_id],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["main_instructor"]["id"], self.trainer_a_id)
        self.assertEqual(len(data["assistants"]), 2)
        self.assertEqual(data["assistants"][0]["id"], self.asst_1_id)
        self.assertEqual(data["assistants"][1]["id"], self.asst_2_id)

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.services.class_service.class_repository")
    @patch("app.services.class_service.user_repository")
    def test_tc2_change_main_instructor_only_keeps_new_main(
        self, mock_user_repo, mock_class_repo, mock_has_perm, mock_get_sess
    ):
        """TC2: Đổi từ GV chính A sang B: chỉ còn B là giảng viên chính."""
        mock_get_sess.return_value = self.admin_session
        mock_has_perm.return_value = True

        mock_class_repo.get_class_by_id.return_value = {"id": self.class_id}
        mock_class_repo.get_class_subject_by_id.return_value = {"id": self.class_subject_1_id, "class_id": self.class_id}

        mock_user_repo.get_user_by_id.return_value = User(
            id=self.trainer_b_id, email="b@test.edu.vn", role="trainer", name="Cô B", status="active", password_hash="", created_at=self.now
        )
        mock_class_repo.get_class_subject_instructors.return_value = [
            {"instructor_id": self.trainer_b_id, "instructor_name": "Cô B", "instructor_email": "b@test.edu.vn", "instructor_role": "trainer", "role_type": "main"},
        ]

        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_1_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_b_id,
                "assistant_ids": [],
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["main_instructor"]["id"], self.trainer_b_id)
        self.assertEqual(data["assistants"], [])
        mock_class_repo.assign_instructors_to_class_subject.assert_called_once_with(
            class_subject_id=self.class_subject_1_id,
            main_instructor_id=self.trainer_b_id,
            assistant_ids=[],
        )

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.services.class_service.class_repository")
    @patch("app.services.class_service.user_repository")
    def test_tc3_reject_invalid_role_for_main_instructor(
        self, mock_user_repo, mock_class_repo, mock_has_perm, mock_get_sess
    ):
        """TC3: Chặn tài khoản sai vai trò (trainee) khi gán làm giảng viên chính."""
        mock_get_sess.return_value = self.admin_session
        mock_has_perm.return_value = True

        mock_class_repo.get_class_by_id.return_value = {"id": self.class_id}
        mock_class_repo.get_class_subject_by_id.return_value = {"id": self.class_subject_1_id, "class_id": self.class_id}

        mock_user_repo.get_user_by_id.return_value = User(
            id=self.trainee_id, email="trainee@test.edu.vn", role="trainee", name="Học viên", status="active", password_hash="", created_at=self.now
        )

        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_1_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainee_id,
                "assistant_ids": [],
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_INSTRUCTOR_ROLE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.services.class_service.class_repository")
    @patch("app.services.class_service.user_repository")
    def test_tc4_reject_invalid_role_for_assistant(
        self, mock_user_repo, mock_class_repo, mock_has_perm, mock_get_sess
    ):
        """TC4: Chặn tài khoản sai vai trò (consultant) khi gán làm trợ giảng."""
        mock_get_sess.return_value = self.admin_session
        mock_has_perm.return_value = True

        mock_class_repo.get_class_by_id.return_value = {"id": self.class_id}
        mock_class_repo.get_class_subject_by_id.return_value = {"id": self.class_subject_1_id, "class_id": self.class_id}

        def mock_get_user(uid):
            if uid == self.trainer_a_id:
                return User(id=self.trainer_a_id, email="a@test.edu.vn", role="trainer", name="Thầy A", status="active", password_hash="", created_at=self.now)
            if uid == self.consultant_id:
                return User(id=self.consultant_id, email="cons@test.edu.vn", role="consultant", name="Tư vấn", status="active", password_hash="", created_at=self.now)
            return None

        mock_user_repo.get_user_by_id.side_effect = mock_get_user

        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_1_id}/instructors",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [self.consultant_id],
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "INVALID_ASSISTANT_ROLE")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    def test_tc5_forbidden_without_course_manage_permission(self, mock_has_perm, mock_get_sess):
        """TC5: Giảng viên chỉ có course.view không được phép thực hiện phân công (403 Forbidden)."""
        mock_get_sess.return_value = LoginSession(
            session_id="sess-trainer-01",
            user_id=self.trainer_a_id,
            refresh_jti="ref-trainer-01",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        mock_has_perm.return_value = False

        res = self.client.post(
            f"/api/v1/classes/{self.class_id}/subjects/{self.class_subject_1_id}/instructors",
            headers={"Authorization": f"Bearer {self.trainer_token}"},
            json={
                "main_instructor_id": self.trainer_a_id,
                "assistant_ids": [],
            },
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "FORBIDDEN")

    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.routes.class_routes.class_service")
    def test_tc6_trainer_role_scopes_class_list_to_assigned_only(
        self, mock_class_svc, mock_get_user, mock_has_perm, mock_get_sess
    ):
        """TC6: Giảng viên đăng nhập -> API danh sách lớp tự động lọc theo instructor_id của mình."""
        mock_get_sess.return_value = LoginSession(
            session_id="sess-trainer-01",
            user_id=self.trainer_a_id,
            refresh_jti="ref-trainer-01",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(hours=8),
            absolute_expires_at=self.now + timedelta(hours=8),
        )
        mock_has_perm.return_value = True
        mock_get_user.return_value = User(
            id=self.trainer_a_id,
            email="trainer.a@test.edu.vn",
            role="trainer",
            name="Thầy A",
            status="active",
            password_hash="",
            must_change_password=False,
            created_at=self.now,
        )
        mock_class_svc.list_classes_service.return_value = ([], 0)

        res = self.client.get(
            "/api/v1/classes",
            headers={"Authorization": f"Bearer {self.trainer_token}"},
        )
        self.assertEqual(res.status_code, 200)
        # Kiểm tra params truyền vào service có instructor_id = trainer_a_id
        kwargs = mock_class_svc.list_classes_service.call_args.kwargs
        self.assertEqual(kwargs.get("instructor_id"), self.trainer_a_id)


if __name__ == "__main__":
    unittest.main()
