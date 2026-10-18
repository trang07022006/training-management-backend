"""
Backend RBAC Authorization Matrix Test Suite for Schedules (SCRUM-228).
Kiểm thử ma trận phân quyền lịch hệ thống:
1. Admin chỉ có vai trò quản trị:
   - Gọi API lịch cá nhân /api/v1/schedules/my-schedule hoặc /api/v1/students/my-schedule -> 403 Forbidden.
   - Gọi API thời khóa biểu tổng thể /api/v1/schedules/calendar -> 200 OK.
   - Gọi API quản lý xem lịch học viên /api/v1/students/<student_id>/schedule -> 200 OK.
2. Quản lý đào tạo (training_manager):
   - Gọi API lịch cá nhân -> 403 Forbidden.
   - Gọi API thời khóa biểu /api/v1/schedules/calendar -> 200 OK.
3. Giảng viên (trainer):
   - Gọi API lịch cá nhân /api/v1/schedules/my-schedule -> 200 OK với user_type="trainer".
   - Chỉ xem được lịch phân công của mình (instructor_id), không lẫn với giảng viên khác.
4. Học viên (trainee):
   - Học viên có lịch -> 200 OK với thông tin lớp và lịch học.
   - Học viên chưa ghi danh -> 200 OK với enrolled_classes=[].
   - Học viên chưa liên kết hồ sơ -> 200 OK với profile_linked=False.
5. Tài khoản nhiều vai trò (Multi-role: Admin + Trainee):
   - Được phép xem lịch học cá nhân 200 OK vì có vai trò trainee hợp lệ.
6. Bảo mật danh tính và cách ly dữ liệu:
   - Client cố tình truyền ?student_id=B hoặc ?user_id=B vào API cá nhân: API bỏ qua và chỉ trả dữ liệu của JWT identity.
   - Học viên A cố tình gọi endpoint quản lý /api/v1/students/<B_id>/schedule -> 403 Forbidden vì thiếu quyền schedule.view.
"""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, patch
import pytest

from app.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_headers():
    return {
        "Authorization": "Bearer fake-token-matrix",
        "Content-Type": "application/json",
    }


def _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-matrix-user"):
    mock_verify.return_value = None
    mock_get_jwt.return_value = {"sid": f"sess-{user_id}"}
    mock_get_identity.return_value = user_id
    session_mock = MagicMock()
    session_mock.session_id = f"sess-{user_id}"
    session_mock.user_id = user_id
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock


class TestScheduleRBACMatrix:

    # -------------------------------------------------------------
    # 1. Admin chỉ có vai trò quản trị
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    def test_pure_admin_forbidden_on_personal_schedule_api(
        self,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Admin thuần túy không có quyền xem API lịch cá nhân học viên/giảng viên -> 403 Forbidden."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-pure-admin")
        mock_has_perm.return_value = False  # Admin không có quyền schedule.personal_view
        mock_get_roles.return_value = ["admin"]

        # Gọi endpoint /api/v1/schedules/my-schedule
        resp1 = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp1.status_code == 403
        data1 = json.loads(resp1.data)
        assert "PERMISSION_DENIED" in data1.get("code", "") or resp1.status_code == 403

        # Gọi endpoint /api/v1/students/my-schedule
        resp2 = client.get("/api/v1/students/my-schedule", headers=auth_headers)
        assert resp2.status_code == 403

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.schedule_service.get_calendar_schedules_service")
    def test_pure_admin_allowed_on_schedules_calendar(
        self,
        mock_get_calendar,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Admin có quyền schedule.view để xem Thời khóa biểu tổng thể của trường."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-pure-admin")
        mock_has_perm.return_value = True  # Admin có schedule.view
        mock_get_calendar.return_value = {"schedules": [], "total": 0}

        resp = client.get("/api/v1/schedules/calendar?from=2026-10-12&to=2026-10-18", headers=auth_headers)
        assert resp.status_code == 200

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_student_by_student_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    @patch("app.repositories.class_schedule_repository.get_student_next_session")
    @patch("app.repositories.class_schedule_repository.get_student_week_sessions")
    def test_pure_admin_allowed_to_view_student_schedule_via_management_endpoint(
        self,
        mock_get_week,
        mock_get_next,
        mock_get_enrolled,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Admin/Quản lý xem lịch của học viên cụ thể qua route quản lý /students/<student_id>/schedule."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-pure-admin")
        mock_has_perm.return_value = True  # Admin có schedule.view

        mock_get_student.return_value = {
            "id": "stu-target-01",
            "student_code": "STU999",
            "user_id": "u-trainee-99",
            "full_name": "Trần Thị B",
            "email": "tranthib@ictu.edu.vn",
        }
        mock_get_enrolled.return_value = [{"class_id": "cls-01", "class_code": "CNTT-A"}]
        mock_get_next.return_value = None
        mock_get_week.return_value = []

        resp = client.get("/api/v1/students/stu-target-01/schedule", headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["data"]["student"]["id"] == "stu-target-01"

    # -------------------------------------------------------------
    # 2. Quản lý đào tạo (training_manager)
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    def test_training_manager_forbidden_on_personal_schedule(
        self,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Quản lý đào tạo không có vai trò trainee/trainer -> 403 Forbidden trên API lịch cá nhân."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-training-manager")
        mock_has_perm.return_value = False
        mock_get_roles.return_value = ["training_manager"]

        resp = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp.status_code == 403

    # -------------------------------------------------------------
    # 3. Giảng viên (trainer) - Lịch giảng dạy được phân công
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.class_schedule_repository.get_trainer_assigned_classes")
    @patch("app.repositories.class_schedule_repository.get_trainer_next_session")
    @patch("app.repositories.class_schedule_repository.get_trainer_week_sessions")
    def test_trainer_personal_schedule_isolated_to_own_teaching_sessions(
        self,
        mock_trainer_week,
        mock_trainer_next,
        mock_assigned_classes,
        mock_get_user,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Giảng viên xem lịch cá nhân: Trả về user_type='trainer' và chỉ lấy các buổi phân công cho instructor_id của mình."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainer-01")
        mock_has_perm.return_value = True  # trainer có schedule.personal_view
        mock_get_roles.return_value = ["trainer"]

        user_mock = MagicMock()
        user_mock.id = "u-trainer-01"
        user_mock.name = "TS. Giảng Viên A"
        user_mock.email = "gva@ictu.edu.vn"
        user_mock.must_change_password = False
        mock_get_user.return_value = user_mock

        mock_assigned_classes.return_value = [
            {"class_id": "cls-01", "class_code": "CNTT-K21A", "class_status": "in_progress"}
        ]
        mock_trainer_next.return_value = {
            "id": "sch-gv-next",
            "class_code": "CNTT-K21A",
            "instructor_id": "u-trainer-01",
            "topic": "Bài giảng Lập trình nâng cao",
        }
        mock_trainer_week.return_value = [
            {
                "id": "sch-gv-next",
                "class_code": "CNTT-K21A",
                "instructor_id": "u-trainer-01",
                "topic": "Bài giảng Lập trình nâng cao",
            }
        ]

        resp = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        payload = data["data"]

        assert payload["user_type"] == "trainer"
        assert payload["instructor"]["id"] == "u-trainer-01"
        assert payload["next_session"]["instructor_id"] == "u-trainer-01"
        assert len(payload["week_sessions"]) == 1

        # Xác minh gọi repository đúng instructor_id của chính giảng viên
        mock_trainer_next.assert_called_once()
        assert mock_trainer_next.call_args[0][0] == "u-trainer-01"

    # -------------------------------------------------------------
    # 4. Học viên (trainee) - Các trạng thái hồ sơ
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    def test_trainee_unlinked_profile(
        self,
        mock_get_student,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Học viên có tài khoản nhưng chưa liên kết hồ sơ sinh viên -> profile_linked=False, student=None."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainee-unlinked")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["trainee"]
        mock_get_student.return_value = None

        resp = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        payload = data["data"]
        assert payload["user_type"] == "trainee"
        assert payload["profile_linked"] is False
        assert payload["student"] is None

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    def test_trainee_unenrolled_in_any_class(
        self,
        mock_get_enrolled,
        mock_get_student,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Học viên đã liên kết hồ sơ nhưng chưa ghi danh lớp nào -> enrolled_classes=[] và không có lịch."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainee-unenrolled")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["trainee"]
        mock_get_student.return_value = {
            "id": "stu-unenrolled",
            "student_code": "STU100",
            "user_id": "u-trainee-unenrolled",
            "full_name": "Học Viên Mới",
        }
        mock_get_enrolled.return_value = []

        resp = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        payload = data["data"]
        assert payload["profile_linked"] is True
        assert len(payload["enrolled_classes"]) == 0
        assert payload["next_session"] is None
        assert payload["week_sessions"] == []

    # -------------------------------------------------------------
    # 5. Tài khoản nhiều vai trò (Multi-role: Admin + Trainee)
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    @patch("app.repositories.class_schedule_repository.get_student_next_session")
    @patch("app.repositories.class_schedule_repository.get_student_week_sessions")
    def test_multi_role_admin_and_trainee_can_view_personal_student_schedule(
        self,
        mock_get_week,
        mock_get_next,
        mock_get_enrolled,
        mock_get_student,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Tài khoản có cả role ['admin', 'trainee'] được phép xem lịch học cá nhân với vai trò học viên."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-dual-role")
        mock_has_perm.return_value = True  # Có schedule.personal_view qua role trainee
        mock_get_roles.return_value = ["admin", "trainee"]

        mock_get_student.return_value = {
            "id": "stu-dual-01",
            "student_code": "STU_DUAL",
            "user_id": "u-dual-role",
            "full_name": "Admin Kiêm Học Viên",
        }
        mock_get_enrolled.return_value = [{"class_id": "cls-01", "class_code": "CNTT-DUAL"}]
        mock_get_next.return_value = {"id": "sch-01", "class_code": "CNTT-DUAL"}
        mock_get_week.return_value = [{"id": "sch-01", "class_code": "CNTT-DUAL"}]

        resp = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["data"]["user_type"] == "trainee"
        assert data["data"]["student"]["student_code"] == "STU_DUAL"

    # -------------------------------------------------------------
    # 6. Bảo mật danh tính: Không thể đổi student_id/user_id & Cách ly dữ liệu
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    @patch("app.repositories.class_schedule_repository.get_student_next_session")
    @patch("app.repositories.class_schedule_repository.get_student_week_sessions")
    def test_student_cannot_spoof_another_student_via_query_params(
        self,
        mock_get_week,
        mock_get_next,
        mock_get_enrolled,
        mock_get_student,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Học viên A truyền ?student_id=stu-B hoặc ?user_id=u-B: Backend bỏ qua và chỉ truy xuất hồ sơ của A (từ JWT)."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-student-A")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["trainee"]

        mock_get_student.return_value = {
            "id": "stu-A",
            "student_code": "STU_A",
            "user_id": "u-student-A",
            "full_name": "Học Viên A",
        }
        mock_get_enrolled.return_value = []
        mock_get_next.return_value = None
        mock_get_week.return_value = []

        # Client cố tình gửi param giả mạo học viên B
        resp = client.get(
            "/api/v1/students/my-schedule?student_id=stu-B&user_id=u-student-B",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["data"]["student"]["id"] == "stu-A"

        # Đảm bảo get_student_by_user_id được gọi với JWT identity của A, KHÔNG phải 'u-student-B'
        mock_get_student.assert_called_once_with("u-student-A")

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_student_cannot_call_management_endpoint_to_view_other_student(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Học viên A cố tình gọi endpoint quản lý /api/v1/students/<stu_b_id>/schedule -> 403 Forbidden vì không có schedule.manage."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-student-A")
        mock_has_perm.return_value = False

        resp = client.get("/api/v1/students/stu-B/schedule", headers=auth_headers)
        assert resp.status_code == 403

    # -------------------------------------------------------------
    # 7. Giảng viên bị chặn xem lịch học viên qua endpoint quản lý
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_trainer_forbidden_to_view_student_schedule_via_management_endpoint(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Giảng viên có schedule.view nhưng KHÔNG có schedule.manage -> 403 Forbidden trên /students/<id>/schedule."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainer-01")
        # Giả lập trainer có schedule.view và schedule.personal_view, nhưng KHÔNG có schedule.manage
        def fake_has_perm(uid, perm):
            return perm in ["schedule.view", "schedule.personal_view"]

        mock_has_perm.side_effect = fake_has_perm

        resp = client.get("/api/v1/students/stu-target-01/schedule", headers=auth_headers)
        assert resp.status_code == 403
        data = json.loads(resp.data)
        assert "FORBIDDEN" in data.get("code", "") or "PERMISSION_DENIED" in data.get("code", "")

    # -------------------------------------------------------------
    # 8. Giới hạn phạm vi /calendar cho Giảng viên
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.services.schedule_service.get_calendar_schedules_service")
    def test_trainer_calendar_scoped_to_assigned_sessions_only(
        self,
        mock_get_calendar,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Giảng viên gọi /calendar: Backend tự động áp đặt trainer_scope_user_id=user_id và bỏ qua tham số instructor_id khác."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainer-01")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["trainer"]  # Pure trainer
        mock_get_calendar.return_value = {"schedules": [], "total": 0}

        # Giảng viên cố tình truyền instructor_id của giảng viên khác
        resp = client.get("/api/v1/schedules/calendar?instructor_id=other-trainer-99", headers=auth_headers)
        assert resp.status_code == 200

        # Kiểm tra service nhận đúng trainer_scope_user_id là của chính giảng viên
        mock_get_calendar.assert_called_once()
        called_params = mock_get_calendar.call_args[0][0]
        assert called_params["trainer_scope_user_id"] == "u-trainer-01"
        assert called_params["instructor_id"] is None

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.services.schedule_service.get_calendar_schedules_service")
    def test_admin_calendar_has_unrestricted_scope(
        self,
        mock_get_calendar,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Admin/Quản lý gọi /calendar: Không bị ép trainer_scope_user_id và có thể xem bất kỳ giảng viên nào."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-admin-01")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["admin"]
        mock_get_calendar.return_value = {"schedules": [], "total": 0}

        resp = client.get("/api/v1/schedules/calendar?instructor_id=any-trainer-55", headers=auth_headers)
        assert resp.status_code == 200

        mock_get_calendar.assert_called_once()
        called_params = mock_get_calendar.call_args[0][0]
        assert called_params["trainer_scope_user_id"] is None
        assert called_params["instructor_id"] == "any-trainer-55"

    # -------------------------------------------------------------
    # 9. Vai trò giảng dạy: Trợ giảng, Dạy thay, Giảng viên chính
    # -------------------------------------------------------------
    def test_teaching_role_annotations(self):
        """Kiểm tra nhãn vai trò giảng dạy: Trợ giảng, Dạy thay, Giảng viên chính, Phân công người khác dạy thay."""
        from app.repositories.class_schedule_repository import _annotate_teaching_role

        # 1. Trợ giảng
        fmt1 = {}
        raw1 = {"instructor_name": "TS. Chính", "instructor_id": "u-assistant", "assigned_role_type": "assistant"}
        _annotate_teaching_role(fmt1, raw1, "u-assistant")
        assert fmt1["teaching_role"] == "assistant"
        assert fmt1["teaching_role_label"] == "Trợ giảng"

        # 2. Giảng viên dạy thay (buổi học gán u-substitute nhưng trong môn không đăng ký)
        fmt2 = {}
        raw2 = {"instructor_name": "TS. Thay", "instructor_id": "u-substitute", "assigned_role_type": None}
        _annotate_teaching_role(fmt2, raw2, "u-substitute")
        assert fmt2["teaching_role"] == "substitute"
        assert fmt2["teaching_role_label"] == "Giảng viên dạy thay"

        # 3. Giảng viên chính
        fmt3 = {}
        raw3 = {"instructor_name": "TS. Chính", "instructor_id": "u-main", "assigned_role_type": "main"}
        _annotate_teaching_role(fmt3, raw3, "u-main")
        assert fmt3["teaching_role"] == "main"
        assert fmt3["teaching_role_label"] == "Giảng viên chính"

        # 4. Giảng viên môn có người khác dạy thay
        fmt4 = {}
        raw4 = {"instructor_name": "ThS. Dạy Hộ", "instructor_id": "u-other", "assigned_role_type": "main"}
        _annotate_teaching_role(fmt4, raw4, "u-main")
        assert fmt4["teaching_role"] == "main_delegated"
        assert "Dạy thay bởi ThS. Dạy Hộ" in fmt4["teaching_role_label"]

    # -------------------------------------------------------------
    # 10. Phân biệt chưa phân công vs đã phân công nhưng chưa có lịch
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.class_schedule_repository.get_trainer_assigned_classes")
    @patch("app.repositories.class_schedule_repository.get_trainer_next_session")
    @patch("app.repositories.class_schedule_repository.get_trainer_week_sessions")
    def test_trainer_assignment_status_distinction(
        self,
        mock_trainer_week,
        mock_trainer_next,
        mock_assigned_classes,
        mock_get_user,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Kiểm tra phân biệt assignment_status: 'not_assigned' vs 'assigned_no_schedule'."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainer-status")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["trainer"]

        user_mock = MagicMock()
        user_mock.id = "u-trainer-status"
        user_mock.name = "Giảng Viên Kiểm Thử"
        user_mock.email = "gvkt@ictu.edu.vn"
        user_mock.must_change_password = False
        mock_get_user.return_value = user_mock

        # TH1: Chưa được phân công lớp nào
        mock_assigned_classes.return_value = []
        mock_trainer_next.return_value = None
        mock_trainer_week.return_value = []

        resp1 = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp1.status_code == 200, f"resp1 failed with {resp1.status_code}: {resp1.data.decode('utf-8')}"
        data1 = json.loads(resp1.data)
        assert data1["data"]["assignment_status"] == "not_assigned"

        # TH2: Đã phân công lớp nhưng chưa có lịch buổi học
        mock_assigned_classes.return_value = [{"class_id": "cls-01", "class_code": "CNTT-01"}]
        mock_trainer_next.return_value = None
        mock_trainer_week.return_value = []

        resp2 = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp2.status_code == 200
        data2 = json.loads(resp2.data)
        assert data2["data"]["assignment_status"] == "assigned_no_schedule"

    # -------------------------------------------------------------
    # 11. Đa vai trò Trainer + Trainee với ngữ cảnh rõ ràng
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.authorization_service.get_user_role_codes")
    @patch("app.repositories.user_repository.get_user_by_id")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    @patch("app.repositories.class_schedule_repository.get_student_next_session")
    @patch("app.repositories.class_schedule_repository.get_student_week_sessions")
    @patch("app.repositories.class_schedule_repository.get_trainer_assigned_classes")
    @patch("app.repositories.class_schedule_repository.get_trainer_next_session")
    @patch("app.repositories.class_schedule_repository.get_trainer_week_sessions")
    def test_multi_role_trainer_and_trainee_switching_context(
        self,
        mock_trainer_week,
        mock_trainer_next,
        mock_assigned_classes,
        mock_student_week,
        mock_student_next,
        mock_enrolled_classes,
        mock_get_student,
        mock_get_user,
        mock_get_roles,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Tài khoản có cả trainer và trainee chuyển đổi context giữa teaching và learning mà không mất lịch."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-dual-trainer-trainee")
        mock_has_perm.return_value = True
        mock_get_roles.return_value = ["trainer", "trainee"]

        user_mock = MagicMock()
        user_mock.id = "u-dual-trainer-trainee"
        user_mock.name = "Nguyễn Văn Đa Năng"
        user_mock.email = "danang@ictu.edu.vn"
        user_mock.must_change_password = False
        mock_get_user.return_value = user_mock

        mock_get_student.return_value = {
            "id": "stu-dual",
            "student_code": "STU_DUAL",
            "user_id": "u-dual-trainer-trainee",
            "full_name": "Nguyễn Văn Đa Năng",
        }
        mock_enrolled_classes.return_value = [{"class_id": "cls-learn-01", "class_code": "HOC-01"}]
        mock_student_next.return_value = {"id": "sch-learn-01", "topic": "Bài học sinh viên"}
        mock_student_week.return_value = [{"id": "sch-learn-01", "topic": "Bài học sinh viên"}]

        mock_assigned_classes.return_value = [{"class_id": "cls-teach-01", "class_code": "DAY-01"}]
        mock_trainer_next.return_value = {"id": "sch-teach-01", "topic": "Bài giảng viên"}
        mock_trainer_week.return_value = [{"id": "sch-teach-01", "topic": "Bài giảng viên"}]

        # 1. Truy vấn không truyền context -> mặc định learning
        resp_def = client.get("/api/v1/schedules/my-schedule", headers=auth_headers)
        assert resp_def.status_code == 200
        data_def = json.loads(resp_def.data)["data"]
        assert data_def["active_context"] == "learning"
        assert "learning" in data_def["available_contexts"]
        assert "teaching" in data_def["available_contexts"]
        assert data_def["student"]["student_code"] == "STU_DUAL"

        # 2. Chuyển context=teaching -> trả về lịch giảng dạy
        resp_teach = client.get("/api/v1/schedules/my-schedule?context=teaching", headers=auth_headers)
        assert resp_teach.status_code == 200
        data_teach = json.loads(resp_teach.data)["data"]
        assert data_teach["active_context"] == "teaching"
        assert data_teach["user_type"] == "trainer"
        assert data_teach["assigned_classes"][0]["class_code"] == "DAY-01"

        # 3. Chuyển context=learning -> trả về lịch học viên
        resp_learn = client.get("/api/v1/schedules/my-schedule?context=learning", headers=auth_headers)
        assert resp_learn.status_code == 200
        data_learn = json.loads(resp_learn.data)["data"]
        assert data_learn["active_context"] == "learning"
        assert data_learn["user_type"] == "trainee"
        assert data_learn["enrolled_classes"][0]["class_code"] == "HOC-01"

    # -------------------------------------------------------------
    # 12. Xác minh mọi API sinh/sửa/hủy/xóa lịch yêu cầu schedule.manage
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_management_endpoints_reject_users_without_schedule_manage(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Người dùng chỉ có schedule.view (hoặc trainer) bị từ chối 403 trên mọi endpoint quản lý lịch."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-trainer-view-only")
        # Chỉ cấp schedule.view, KHÔNG cấp schedule.manage
        mock_has_perm.side_effect = lambda uid, perm: perm == "schedule.view"

        # 1. Preview
        r1 = client.post("/api/v1/classes/cls-01/schedules/preview", json={}, headers=auth_headers)
        assert r1.status_code == 403

        # 2. Generate
        r2 = client.post("/api/v1/classes/cls-01/schedules/generate", json={}, headers=auth_headers)
        assert r2.status_code == 403

        # 3. Delete class schedules
        r3 = client.delete("/api/v1/classes/cls-01/schedules", headers=auth_headers)
        assert r3.status_code == 403

        # 4. Update single schedule
        r4 = client.put("/api/v1/classes/cls-01/schedules/sch-01", json={}, headers=auth_headers)
        assert r4.status_code == 403

        # 5. Cancel single schedule
        r5 = client.post("/api/v1/classes/cls-01/schedules/sch-01/cancel", json={"reason": "Test"}, headers=auth_headers)
        assert r5.status_code == 403

        # 6. Notifications management endpoint
        r6 = client.get("/api/v1/classes/cls-01/schedules/sch-01/notifications", headers=auth_headers)
        assert r6.status_code == 403

    # -------------------------------------------------------------
    # 13. Kiểm thử 3 trường hợp: admin thuần túy, training_manager và admin + training_manager
    # -------------------------------------------------------------
    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_pure_admin_forbidden_on_session_management_endpoints(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Tài khoản admin thuần túy không có schedule.manage bị chặn 403 trên API quản lý buổi học, nhưng xem được Thời khóa biểu."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-pure-admin-sessions")
        # Admin chỉ có schedule.view và user.manage, KHÔNG có schedule.manage
        admin_perms = {"schedule.view", "user.manage", "user.view"}
        mock_has_perm.side_effect = lambda uid, perm: perm in admin_perms

        # Bị chặn trên các API quản lý buổi học
        r_update = client.put("/api/v1/classes/cls-01/schedules/sch-01", json={}, headers=auth_headers)
        assert r_update.status_code == 403

        r_cancel = client.post("/api/v1/classes/cls-01/schedules/sch-01/cancel", json={"cancellation_reason": "Lý do"}, headers=auth_headers)
        assert r_cancel.status_code == 403

        r_preview = client.post("/api/v1/classes/cls-01/schedules/preview", json={}, headers=auth_headers)
        assert r_preview.status_code == 403

        # Nhưng vẫn được xem Thời khóa biểu
        with patch("app.services.schedule_service.get_calendar_schedules_service", return_value={"schedules": [], "total": 0}):
            r_calendar = client.get("/api/v1/schedules/calendar", headers=auth_headers)
            assert r_calendar.status_code == 200

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_training_manager_allowed_on_session_management_and_calendar(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Tài khoản training_manager có schedule.manage và schedule.view: được sử dụng quản lý buổi học và xem thời khóa biểu."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-tm-sessions")
        tm_perms = {"schedule.manage", "schedule.view", "course.view"}
        mock_has_perm.side_effect = lambda uid, perm: perm in tm_perms

        with patch("app.services.schedule_service.cancel_single_schedule_service", return_value={"id": "sch-01", "status": "cancelled"}):
            r_cancel = client.post("/api/v1/classes/cls-01/schedules/sch-01/cancel", json={"cancellation_reason": "Dời lịch thi"}, headers=auth_headers)
            assert r_cancel.status_code == 200

        with patch("app.services.schedule_service.get_calendar_schedules_service", return_value={"schedules": [], "total": 0}):
            r_calendar = client.get("/api/v1/schedules/calendar", headers=auth_headers)
            assert r_calendar.status_code == 200

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_dual_admin_and_training_manager_allowed_on_both_domains(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Tài khoản có cả admin và training_manager: có union permissions, được sử dụng cả quản lý buổi học và chức năng quản trị."""
        _mock_user_session(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, user_id="u-dual-admin-tm")
        dual_perms = {"schedule.manage", "schedule.view", "user.manage", "user.view"}
        mock_has_perm.side_effect = lambda uid, perm: perm in dual_perms

        with patch("app.services.schedule_service.cancel_single_schedule_service", return_value={"id": "sch-01", "status": "cancelled"}):
            r_cancel = client.post("/api/v1/classes/cls-01/schedules/sch-01/cancel", json={"cancellation_reason": "Dời lịch"}, headers=auth_headers)
            assert r_cancel.status_code == 200

        with patch("app.services.schedule_service.get_calendar_schedules_service", return_value={"schedules": [], "total": 0}):
            r_calendar = client.get("/api/v1/schedules/calendar", headers=auth_headers)
            assert r_calendar.status_code == 200

