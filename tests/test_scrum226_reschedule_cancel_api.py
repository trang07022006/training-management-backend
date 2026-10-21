"""
Unit tests cho SCRUM-226 - Sửa, dời, hủy buổi học đơn lẻ trong Hệ thống Quản lý Đào tạo ICTU.
- AC 1: Đổi được ngày, giờ, phòng, giảng viên dạy thay.
- AC 2: Hủy buổi bắt buộc nhập lý do.
- AC 3: Học viên và giảng viên của lớp nhận được thông báo thay đổi.
- AC 4: Không sửa được buổi đã điểm danh.
"""

from datetime import date, datetime, timezone
import json
from unittest.mock import MagicMock, patch
import pytest

from app.main import app
from app.models.class_entity import ClassEntity
from app.models.class_schedule import ClassSchedule


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
    mock_get_jwt.return_value = {"sid": "sess-test-226"}
    mock_get_identity.return_value = "manager-user-226"
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-226"
    session_mock.user_id = "manager-user-226"
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = True


class TestScheduleRescheduleCancelApi:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.get_schedule_by_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    @patch("app.repositories.class_schedule_repository.update_schedule_item")
    @patch("app.repositories.class_schedule_repository.get_class_enrollment_recipients")
    @patch("app.repositories.class_schedule_repository.get_user_info_by_id")
    @patch("app.repositories.class_schedule_repository.insert_schedule_notifications_batch")
    def test_reschedule_session_success_with_notifications(
        self,
        mock_insert_notifs,
        mock_get_user,
        mock_get_students,
        mock_update_item,
        mock_find_conflicts,
        mock_get_schedule,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 1 & AC 3: Đổi ngày, giờ, phòng, giảng viên thành công và gửi thông báo tới GV và HV."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_class.return_value = ClassEntity(
            id="class-226",
            class_code="L01-JAVA",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="active",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        existing_sched = ClassSchedule(
            id="sched-item-1",
            class_id="class-226",
            session_number=1,
            topic="Cú pháp cơ bản",
            learning_date=date(2026, 11, 2),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P101",
            instructor_id="inst-1",
            status="scheduled",
            attendance_checked=False,
        )
        mock_get_schedule.return_value = existing_sched
        mock_find_conflicts.return_value = []  # Không có xung đột
        mock_update_item.side_effect = lambda s: s
        mock_get_students.return_value = [
            {"id": "st-1", "user_id": "u-st1", "full_name": "Nguyễn Văn Học", "email": "hocvien1@ictu.vn"},
            {"id": "st-2", "user_id": "u-st2", "full_name": "Trần Thị Mai", "email": "hocvien2@ictu.vn"},
        ]
        mock_get_user.return_value = {"id": "inst-2", "name": "TS. Lê Dạy Thay", "email": "gv_thay@ictu.vn"}
        mock_insert_notifs.side_effect = lambda notifs: notifs

        # Payload đổi ngày sang 2026-11-03, đổi phòng sang P202, đổi giảng viên sang inst-2
        payload = {
            "learning_date": "2026-11-03",
            "start_time": "09:45:00",
            "end_time": "11:45:00",
            "shift": "Ca 2",
            "room_id": "P202",
            "instructor_id": "inst-2",
        }

        resp = client.put(
            "/api/v1/classes/class-226/schedules/sched-item-1",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["schedule"]["learning_date"] == "2026-11-03"
        assert data["schedule"]["room_id"] == "P202"
        assert data["schedule"]["instructor_id"] == "inst-2"
        assert data["schedule"]["status"] == "rescheduled"
        # Thông báo gửi cho 2 học viên + giảng viên mới + giảng viên cũ = 4
        assert data["notifications_sent"] >= 3
        mock_insert_notifs.assert_called_once()

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.get_schedule_by_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    def test_reschedule_blocked_when_conflict_detected_without_override(
        self,
        mock_find_conflicts,
        mock_get_schedule,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 1 & SCRUM-225: Dời lịch phát hiện xung đột và chặn lưu khi chưa ghi đè."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_class.return_value = ClassEntity(
            id="class-226",
            class_code="L01-JAVA",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="active",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        mock_get_schedule.return_value = ClassSchedule(
            id="sched-item-1",
            class_id="class-226",
            session_number=1,
            topic="Cú pháp cơ bản",
            learning_date=date(2026, 11, 2),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P101",
            instructor_id="inst-1",
            status="scheduled",
            attendance_checked=False,
        )

        # Giả lập phát hiện xung đột phòng học P202 với lớp L02
        mock_find_conflicts.return_value = [
            {
                "id": "sched-other",
                "class_code": "L02-PYTHON",
                "session_number": 2,
                "room_id": "P202",
                "learning_date": "2026-11-03",
                "start_time": "09:45:00",
                "end_time": "11:45:00",
                "message": "Phòng học P202 đã được sử dụng bởi lớp L02-PYTHON",
            }
        ]

        payload = {
            "learning_date": "2026-11-03",
            "start_time": "09:45:00",
            "end_time": "11:45:00",
            "room_id": "P202",
            "allow_conflict_override": False,
        }

        resp = client.put(
            "/api/v1/classes/class-226/schedules/sched-item-1",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body["code"] == "SCHEDULE_CONFLICT_DETECTED"
        assert len(body["data"]["conflicts"]) == 1

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.get_schedule_by_id")
    def test_update_blocked_when_attendance_already_checked(
        self,
        mock_get_schedule,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 4: Chặn sửa buổi học đã được điểm danh."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_class.return_value = ClassEntity(
            id="class-226",
            class_code="L01-JAVA",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="active",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        # Buổi học đã điểm danh (attendance_checked = True)
        mock_get_schedule.return_value = ClassSchedule(
            id="sched-checked",
            class_id="class-226",
            session_number=1,
            topic="Cú pháp cơ bản",
            learning_date=date(2026, 11, 2),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P101",
            instructor_id="inst-1",
            status="scheduled",
            attendance_checked=True,
        )

        payload = {"learning_date": "2026-11-03"}

        resp = client.put(
            "/api/v1/classes/class-226/schedules/sched-checked",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == "SCHEDULE_ATTENDANCE_ALREADY_CHECKED"
        assert "điểm danh" in body["message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.get_schedule_by_id")
    def test_cancel_session_requires_reason(
        self,
        mock_get_schedule,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 2: Hủy buổi học bắt buộc nhập lý do, thiếu lý do trả về HTTP 400."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_class.return_value = ClassEntity(
            id="class-226",
            class_code="L01-JAVA",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="active",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        mock_get_schedule.return_value = ClassSchedule(
            id="sched-cancel-1",
            class_id="class-226",
            session_number=2,
            topic="Vòng lặp",
            learning_date=date(2026, 11, 4),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P101",
            instructor_id="inst-1",
            status="scheduled",
            attendance_checked=False,
        )

        # Gửi payload không có reason
        resp = client.post(
            "/api/v1/classes/class-226/schedules/sched-cancel-1/cancel",
            data=json.dumps({"reason": "   "}),
            headers=auth_headers,
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == "MISSING_CANCELLATION_REASON"
        assert "Lý do hủy" in body["message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.get_schedule_by_id")
    @patch("app.repositories.class_schedule_repository.update_schedule_item")
    @patch("app.repositories.class_schedule_repository.get_class_enrollment_recipients")
    @patch("app.repositories.class_schedule_repository.get_user_info_by_id")
    @patch("app.repositories.class_schedule_repository.insert_schedule_notifications_batch")
    def test_cancel_session_success_updates_status_and_notifies(
        self,
        mock_insert_notifs,
        mock_get_user,
        mock_get_students,
        mock_update_item,
        mock_get_schedule,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 2 & AC 3: Hủy buổi học thành công, lưu lý do và phát thông báo tới HV và GV."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_class.return_value = ClassEntity(
            id="class-226",
            class_code="L01-JAVA",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="active",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        mock_get_schedule.return_value = ClassSchedule(
            id="sched-cancel-1",
            class_id="class-226",
            session_number=2,
            topic="Vòng lặp",
            learning_date=date(2026, 11, 4),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P101",
            instructor_id="inst-1",
            status="scheduled",
            attendance_checked=False,
        )
        mock_update_item.side_effect = lambda s: s
        mock_get_students.return_value = [
            {"id": "st-1", "user_id": "u-st1", "full_name": "Nguyễn Văn Học", "email": "hocvien1@ictu.vn"},
        ]
        mock_get_user.return_value = {"id": "inst-1", "name": "TS. Giảng Viên A", "email": "gvA@ictu.vn"}
        mock_insert_notifs.side_effect = lambda notifs: notifs

        resp = client.post(
            "/api/v1/classes/class-226/schedules/sched-cancel-1/cancel",
            data=json.dumps({"reason": "Giảng viên báo ốm đột xuất"}),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["schedule"]["status"] == "cancelled"
        assert data["schedule"]["cancellation_reason"] == "Giảng viên báo ốm đột xuất"
        assert data["notifications_sent"] >= 2
        mock_insert_notifs.assert_called_once()

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.get_schedule_by_id")
    @patch("app.repositories.class_schedule_repository.update_schedule_item")
    @patch("app.repositories.class_schedule_repository.get_class_enrollment_recipients")
    @patch("app.repositories.class_schedule_repository.get_user_info_by_id")
    @patch("app.repositories.class_schedule_repository.insert_schedule_notifications_batch")
    def test_unlinked_students_do_not_get_in_app_notifications(
        self,
        mock_insert_notifs,
        mock_get_user,
        mock_get_students,
        mock_update_item,
        mock_get_schedule,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Học viên chưa liên kết tài khoản (user_id=None) không được cấp recipient_id bằng student.id và không tạo thông báo giao diện."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        mock_get_class.return_value = ClassEntity(
            id="class-226",
            class_code="L01-JAVA",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="active",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        mock_get_schedule.return_value = ClassSchedule(
            id="sched-cancel-2",
            class_id="class-226",
            session_number=3,
            topic="OOP",
            learning_date=date(2026, 11, 6),
            shift="Ca 1",
            start_time="07:30:00",
            end_time="09:30:00",
            room_id="P101",
            instructor_id=None,
            status="scheduled",
            attendance_checked=False,
        )
        mock_update_item.side_effect = lambda s: s
        # 1 học viên có tài khoản, 1 học viên chưa liên kết (user_id=None)
        mock_get_students.return_value = [
            {"id": "st-linked", "user_id": "usr-st-linked-01", "full_name": "HV Đã Liên Kết", "email": "hv1@ictu.vn"},
            {"id": "st-unlinked", "user_id": None, "full_name": "HV Chưa Tài Khoản", "email": "hv2@ictu.vn"},
        ]
        mock_get_user.return_value = None
        mock_insert_notifs.side_effect = lambda notifs: notifs

        resp = client.post(
            "/api/v1/classes/class-226/schedules/sched-cancel-2/cancel",
            data=json.dumps({"reason": "Hủy buổi học bảo trì"}),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        mock_insert_notifs.assert_called_once()
        saved_notifs = mock_insert_notifs.call_args[0][0]
        # Chỉ có đúng 1 thông báo cho học viên có tài khoản
        assert len(saved_notifs) == 1
        assert saved_notifs[0]["recipient_id"] == "usr-st-linked-01"
        assert saved_notifs[0]["recipient_type"] == "student"
        # Tuyệt đối không dùng student.id làm recipient_id
        for n in saved_notifs:
            assert n["recipient_id"] != "st-unlinked"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.schedule_service.list_my_notifications_service")
    def test_get_my_notifications_strictly_filters_by_current_user(
        self,
        mock_list_my_notifs,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """API /api/v1/schedules/notifications/my chỉ cho phép đọc thông báo của chính actor_user_id từ token, không để lộ thông báo người khác."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_identity.return_value = "student-logged-in-user-999"
        mock_get_sess.return_value.user_id = "student-logged-in-user-999"
        mock_list_my_notifs.return_value = [
            {
                "id": "notif-999",
                "recipient_id": "student-logged-in-user-999",
                "title": "Thông báo cá nhân",
                "message": "Nội dung chỉ của bạn",
            }
        ]

        resp = client.get(
            "/api/v1/schedules/notifications/my",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert len(data) == 1
        assert data[0]["recipient_id"] == "student-logged-in-user-999"
        # Khẳng định service được gọi chính xác với ID của người gọi trong token
        mock_list_my_notifs.assert_called_once_with("student-logged-in-user-999")
