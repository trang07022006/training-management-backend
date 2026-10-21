"""
Unit tests cho SCRUM-228 - Thời khóa biểu cá nhân của học viên trong Hệ thống Quản lý Đào tạo ICTU.
- AC 1: Mặc định hiển thị buổi kế tiếp và các buổi trong tuần.
- AC 2: Chỉ thấy buổi của lớp mình tham gia (phạm vi dữ liệu dựa trên ghi danh thực tế).
- Bảo mật: Xác thực học viên từ phiên đăng nhập (JWT identity), không thể đổi ID trong request để xem người khác.
- Hiển thị thông tin phòng hoặc liên kết học trực tuyến khi dữ liệu có sẵn.
- Trạng thái rỗng phù hợp khi chưa có lịch hoặc chưa ghi danh.
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
        "Authorization": "Bearer fake-token-jwt-student",
        "Content-Type": "application/json",
    }


def _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, user_id="student-user-228"):
    mock_verify.return_value = None
    mock_get_jwt.return_value = {"sid": "sess-test-228"}
    mock_get_identity.return_value = user_id
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-228"
    session_mock.user_id = user_id
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = True


class TestStudentPersonalScheduleApi:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    @patch("app.repositories.class_schedule_repository.get_student_next_session")
    @patch("app.repositories.class_schedule_repository.get_student_week_sessions")
    def test_get_my_schedule_success_with_next_and_week_sessions(
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
        """AC 1 & 2: Học viên đã ghi danh xem lịch học cá nhân với buổi kế tiếp và các buổi trong tuần."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, user_id="u-trainee-01")

        mock_get_student.return_value = {
            "id": "stu-101",
            "student_code": "STU000101",
            "user_id": "u-trainee-01",
            "full_name": "Nguyễn Văn Học Viên",
            "email": "hocvien@ictu.edu.vn",
            "phone": "0987654321",
            "program_id": "prog-it",
            "program_name": "Công nghệ thông tin",
        }

        mock_get_enrolled.return_value = [
            {
                "class_id": "cls-cntt-k21",
                "enrollment_status": "enrolled",
                "class_code": "CNTT-K21A",
                "learning_mode": "offline",
                "class_status": "in_progress",
                "program_name": "Công nghệ thông tin",
            }
        ]

        mock_get_next.return_value = {
            "id": "sch-next-1",
            "class_id": "cls-cntt-k21",
            "class_code": "CNTT-K21A",
            "session_number": 3,
            "topic": "Bài 3: CSS Flexbox và Grid",
            "learning_date": "2026-10-15",
            "day_of_week": "Thứ 5",
            "shift": "Ca 1 (07:30 - 09:30)",
            "start_time": "07:30:00",
            "end_time": "09:30:00",
            "room_id": "P201",
            "is_online": False,
            "online_url": None,
            "room_name": "P201",
            "instructor_id": "inst-01",
            "instructor_name": "TS. Nguyễn Văn A",
            "instructor_email": "nguyenvana@ictu.edu.vn",
            "subject_name": "Lập trình Web",
            "subject_code": "WEB101",
            "status": "scheduled",
            "cancellation_reason": None,
            "attendance_checked": False,
        }

        mock_get_week.return_value = [
            {
                "id": "sch-week-1",
                "class_id": "cls-cntt-k21",
                "class_code": "CNTT-K21A",
                "session_number": 2,
                "topic": "Bài 2: Cấu trúc HTML5",
                "learning_date": "2026-10-13",
                "day_of_week": "Thứ 3",
                "shift": "Ca 1 (07:30 - 09:30)",
                "start_time": "07:30:00",
                "end_time": "09:30:00",
                "room_id": "https://meet.google.com/abc-xyz-123",
                "is_online": True,
                "online_url": "https://meet.google.com/abc-xyz-123",
                "room_name": None,
                "instructor_id": "inst-01",
                "instructor_name": "TS. Nguyễn Văn A",
                "instructor_email": "nguyenvana@ictu.edu.vn",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "cancellation_reason": None,
                "attendance_checked": False,
            },
            mock_get_next.return_value,
        ]

        resp = client.get("/api/v1/students/my-schedule", headers=auth_headers)
        assert resp.status_code == 200

        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["code"] == "MY_SCHEDULE_RETRIEVED"
        payload = data["data"]

        # Kiểm tra thông tin học viên
        assert payload["student"]["id"] == "stu-101"
        assert payload["student"]["student_code"] == "STU000101"
        assert len(payload["enrolled_classes"]) == 1

        # Kiểm tra buổi kế tiếp (next_session)
        assert payload["next_session"] is not None
        assert payload["next_session"]["id"] == "sch-next-1"
        assert payload["next_session"]["room_name"] == "P201"
        assert payload["next_session"]["is_online"] is False

        # Kiểm tra danh sách tuần (week_sessions)
        assert len(payload["week_sessions"]) == 2
        assert payload["total_week_sessions"] == 2
        assert payload["week_sessions"][0]["is_online"] is True
        assert payload["week_sessions"][0]["online_url"] == "https://meet.google.com/abc-xyz-123"

        # Kiểm tra repository được gọi đúng class_ids của lớp học viên ghi danh
        mock_get_next.assert_called_once()
        called_class_ids = mock_get_next.call_args[1]["class_ids"]
        assert called_class_ids == ["cls-cntt-k21"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    def test_get_my_schedule_empty_when_no_student_profile(
        self,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trạng thái rỗng: Tài khoản người dùng chưa gắn với hồ sơ học viên nào."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, user_id="u-admin-01")
        mock_get_student.return_value = None

        resp = client.get("/api/v1/students/my-schedule", headers=auth_headers)
        assert resp.status_code == 200

        data = json.loads(resp.data)
        assert data["status"] == "success"
        payload = data["data"]
        assert payload["student"] is None
        assert payload["enrolled_classes"] == []
        assert payload["next_session"] is None
        assert payload["week_sessions"] == []
        assert payload["total_week_sessions"] == 0

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    def test_get_my_schedule_empty_when_not_enrolled_in_any_class(
        self,
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
        """Trạng thái rỗng: Học viên có hồ sơ nhưng chưa ghi danh vào lớp nào."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, user_id="u-trainee-02")
        mock_get_student.return_value = {
            "id": "stu-102",
            "student_code": "STU000102",
            "user_id": "u-trainee-02",
            "full_name": "Lê Thị Mới",
            "email": "lethimoi@ictu.edu.vn",
            "phone": "0912345678",
            "program_id": None,
        }
        mock_get_enrolled.return_value = []

        resp = client.get("/api/v1/students/my-schedule", headers=auth_headers)
        assert resp.status_code == 200

        data = json.loads(resp.data)
        assert data["status"] == "success"
        payload = data["data"]
        assert payload["student"]["id"] == "stu-102"
        assert payload["enrolled_classes"] == []
        assert payload["next_session"] is None
        assert payload["week_sessions"] == []
        assert payload["total_week_sessions"] == 0

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_student_by_user_id")
    @patch("app.repositories.class_schedule_repository.get_enrolled_classes_for_student")
    @patch("app.repositories.class_schedule_repository.get_student_next_session")
    @patch("app.repositories.class_schedule_repository.get_student_week_sessions")
    def test_get_my_schedule_alias_endpoint_and_custom_dates(
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
        """Kiểm tra alias route /api/v1/schedules/my-schedule và tùy chọn khoảng ngày date_from/date_to."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, user_id="u-trainee-03")
        mock_get_student.return_value = {
            "id": "stu-103",
            "student_code": "STU000103",
            "user_id": "u-trainee-03",
            "full_name": "Phạm Văn C",
            "email": "phamvanc@ictu.edu.vn",
            "phone": "0933333333",
            "program_id": None,
        }
        mock_get_enrolled.return_value = [
            {"class_id": "cls-01", "class_code": "L01", "status": "enrolled"}
        ]
        mock_get_next.return_value = None
        mock_get_week.return_value = []

        resp = client.get(
            "/api/v1/schedules/my-schedule?date_from=2026-11-02&date_to=2026-11-08",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["data"]["date_from"] == "2026-11-02"
        assert data["data"]["date_to"] == "2026-11-08"

        mock_get_week.assert_called_once_with(
            class_ids=["cls-01"],
            date_from="2026-11-02",
            date_to="2026-11-08",
        )

    def test_get_my_schedule_unauthenticated(self, client):
        """Chưa đăng nhập -> 401 UNAUTHORIZED."""
        resp = client.get("/api/v1/students/my-schedule")
        assert resp.status_code == 401
