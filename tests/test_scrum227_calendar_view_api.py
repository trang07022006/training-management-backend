"""
Unit tests cho SCRUM-227 - Xem thời khóa biểu dạng lịch theo tuần và theo tháng trong Hệ thống Quản lý Đào tạo ICTU.
- AC 1: Chuyển đổi giữa chế độ tuần và tháng.
- AC 2: Lọc theo lớp, giảng viên hoặc phòng.
- AC 3: Bấm vào một buổi mở được chi tiết buổi học.
- AC 4: Hỗ trợ dữ liệu responsive trên thiết bị di động.
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
        "Authorization": "Bearer fake-token-jwt",
        "Content-Type": "application/json",
    }


def _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm):
    mock_verify.return_value = None
    mock_get_jwt.return_value = {"sid": "sess-test-227"}
    mock_get_identity.return_value = "manager-user-227"
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-227"
    session_mock.user_id = "manager-user-227"
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = True


class TestScheduleCalendarApi:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.list_calendar_schedules")
    def test_get_calendar_schedules_week_view(
        self,
        mock_list_cal,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 1: Lấy danh sách thời khóa biểu dạng lịch theo tuần."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_list_cal.return_value = [
            {
                "id": "sch-1",
                "class_id": "cls-1",
                "class_code": "CNTT-K21A",
                "session_number": 1,
                "topic": "Bài 1: Giới thiệu khóa học",
                "learning_date": "2026-11-02",
                "day_of_week": "Thứ 2",
                "shift": "shift_1",
                "start_time": "07:30:00",
                "end_time": "09:30:00",
                "room_id": "P201",
                "instructor_id": "inst-1",
                "instructor_name": "TS. Nguyễn Văn A",
                "instructor_email": "nguyenvana@ictu.edu.vn",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "cancellation_reason": None,
                "attendance_checked": False,
            },
            {
                "id": "sch-2",
                "class_id": "cls-1",
                "class_code": "CNTT-K21A",
                "session_number": 2,
                "topic": "Bài 2: React & Hooks",
                "learning_date": "2026-11-04",
                "day_of_week": "Thứ 4",
                "shift": "shift_1",
                "start_time": "07:30:00",
                "end_time": "09:30:00",
                "room_id": "P201",
                "instructor_id": "inst-1",
                "instructor_name": "TS. Nguyễn Văn A",
                "instructor_email": "nguyenvana@ictu.edu.vn",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "cancellation_reason": None,
                "attendance_checked": False,
            },
        ]

        resp = client.get(
            "/api/v1/schedules/calendar?date_from=2026-11-02&date_to=2026-11-08&view_mode=week",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == "CALENDAR_SCHEDULES_RETRIEVED"
        assert data["data"]["total"] == 2
        assert data["data"]["view_mode"] == "week"
        assert len(data["data"]["schedules"]) == 2
        assert data["data"]["schedules"][0]["day_of_week"] == "Thứ 2"

        mock_list_cal.assert_called_once_with(
            date_from="2026-11-02",
            date_to="2026-11-08",
            class_id=None,
            instructor_id=None,
            room_id=None,
        )

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.list_calendar_schedules")
    def test_get_calendar_schedules_filter_by_class_and_instructor(
        self,
        mock_list_cal,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 2: Lọc thời khóa biểu theo lớp học và giảng viên."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_list_cal.return_value = []

        resp = client.get(
            "/api/v1/schedules/calendar?class_id=cls-99&instructor_id=inst-88&view_mode=month",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["view_mode"] == "month"
        assert data["data"]["filters"]["class_id"] == "cls-99"
        assert data["data"]["filters"]["instructor_id"] == "inst-88"

        mock_list_cal.assert_called_once_with(
            date_from=None,
            date_to=None,
            class_id="cls-99",
            instructor_id="inst-88",
            room_id=None,
        )

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.list_calendar_schedules")
    def test_get_calendar_schedules_filter_by_room(
        self,
        mock_list_cal,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 2: Lọc thời khóa biểu theo phòng học."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_list_cal.return_value = []

        resp = client.get(
            "/api/v1/schedules/calendar?room_id=UAT-P20",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        mock_list_cal.assert_called_once_with(
            date_from=None,
            date_to=None,
            class_id=None,
            instructor_id=None,
            room_id="UAT-P20",
        )

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_schedule_detail_by_id")
    def test_get_schedule_detail_success(
        self,
        mock_get_detail,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 3: Bấm vào một buổi mở được chi tiết buổi học."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_detail.return_value = {
            "id": "sch-detail-1",
            "class_id": "cls-101",
            "class_code": "KTPM-K22B",
            "session_number": 5,
            "topic": "Bài 5: Kiểm thử phần mềm",
            "learning_date": "2026-11-10",
            "day_of_week": "Thứ 3",
            "shift": "shift_2",
            "start_time": "09:45:00",
            "end_time": "11:45:00",
            "room_id": "Lab 3",
            "instructor_id": "inst-2",
            "instructor_name": "ThS. Trần Thị B",
            "instructor_email": "tranthib@ictu.edu.vn",
            "subject_name": "Kiểm thử phần mềm",
            "subject_code": "TEST201",
            "status": "scheduled",
            "cancellation_reason": None,
            "attendance_checked": False,
        }

        resp = client.get(
            "/api/v1/schedules/sch-detail-1",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == "SCHEDULE_DETAIL_RETRIEVED"
        assert data["data"]["id"] == "sch-detail-1"
        assert data["data"]["topic"] == "Bài 5: Kiểm thử phần mềm"
        assert data["data"]["room_id"] == "Lab 3"
        assert data["data"]["class_code"] == "KTPM-K22B"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_schedule_repository.get_schedule_detail_by_id")
    def test_get_schedule_detail_not_found(
        self,
        mock_get_detail,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Buổi học không tồn tại trả về 404."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_detail.return_value = None

        resp = client.get(
            "/api/v1/schedules/non-existent-id",
            headers=auth_headers,
        )

        assert resp.status_code == 404
        assert resp.get_json()["code"] == "SCHEDULE_NOT_FOUND"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_calendar_permission_denied(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Người dùng không có quyền course.view bị chặn 403."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_has_perm.return_value = False

        resp = client.get(
            "/api/v1/schedules/calendar",
            headers=auth_headers,
        )

        assert resp.status_code == 403
        assert resp.get_json()["code"] == "FORBIDDEN"
