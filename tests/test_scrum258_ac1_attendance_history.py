"""
Targeted tests cho SCRUM-258 AC1: Học viên xem lịch sử điểm danh cá nhân và tỷ lệ chuyên cần.
- AC1: Danh sách buổi kèm trạng thái, tỷ lệ chuyên cần hiện tại.
- Bảo mật: Xác thực danh tính từ JWT (g.user_id), không tin cậy student_id client gửi lên.
- Quyền sở hữu: Không thể xem điểm danh của lớp mình không ghi danh (403 FORBIDDEN_CLASS_ACCESS).
- Tài khoản chưa liên kết hồ sơ học viên trả 404 STUDENT_PROFILE_NOT_FOUND.
- Hai buổi cùng ngày là hai dòng riêng biệt theo schedule_id.
- Công thức chuyên cần: D = P + L + E + U, tỷ lệ = (P + L) / D * 100%. D = 0 trả null ("Chưa có dữ liệu").
- Thống kê toàn lớp độc lập với bộ lọc và phân trang hiển thị.
"""

from datetime import date, datetime, time, timezone
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
        "Authorization": "Bearer fake-token-jwt-student-258",
        "Content-Type": "application/json",
    }


def _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, user_id="user-student-258"):
    mock_verify.return_value = None
    mock_get_jwt.return_value = {"sid": "sess-test-258"}
    mock_get_identity.return_value = user_id
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-258"
    session_mock.user_id = user_id
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = True


class TestScrum258AC1StudentAttendanceHistory:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    def test_unlinked_account_returns_404(
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
        """Tài khoản chưa liên kết hồ sơ học viên trả 404 STUDENT_PROFILE_NOT_FOUND."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = None

        res = client.get("/api/v1/me/attendance-history", headers=auth_headers)
        assert res.status_code == 404
        data = res.get_json()
        assert data["code"] == "STUDENT_PROFILE_NOT_FOUND"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    def test_access_unenrolled_class_returns_403(
        self,
        mock_is_enrolled,
        mock_get_classes,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Học viên không được xem lớp mà mình không tham gia (403 FORBIDDEN_CLASS_ACCESS)."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {
            "id": "student-1",
            "student_code": "HV001",
            "full_name": "Nguyễn Văn A",
            "email": "nva@ictu.edu.vn",
        }
        mock_get_classes.return_value = [{"class_id": "class-legit", "class_code": "LOP-01"}]
        mock_is_enrolled.return_value = False

        res = client.get("/api/v1/me/attendance-history?class_id=class-other", headers=auth_headers)
        assert res.status_code == 403
        data = res.get_json()
        assert data["code"] == "FORBIDDEN_CLASS_ACCESS"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_attendance_history_and_rate_calculation(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_is_enrolled,
        mock_get_classes,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """
        Kiểm tra tính toán chuyên cần:
        P = 3, L = 1, E = 1, U = 1 -> D = 6.
        Tỷ lệ = (3 + 1) / 6 * 100% = 66.67%.
        Hai buổi cùng ngày 2026-10-10 là hai dòng riêng biệt theo schedule_id.
        """
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {
            "id": "student-1",
            "student_code": "HV001",
            "full_name": "Nguyễn Văn A",
            "email": "nva@ictu.edu.vn",
        }
        mock_get_classes.return_value = [{"class_id": "class-1", "class_code": "LOP-01"}]
        mock_is_enrolled.return_value = True

        mock_get_class_details.return_value = {
            "id": "class-1",
            "class_code": "LOP-01",
            "program_id": "prog-1",
            "program_name": "CNTT",
            "status": "ongoing",
        }

        # 6 buổi đã kết thúc trong quá khứ:
        # sched-1: 2026-10-10 Ca 1 -> present
        # sched-2: 2026-10-10 Ca 2 -> late (cùng ngày 2026-10-10)
        # sched-3: 2026-10-11 -> present
        # sched-4: 2026-10-12 -> present
        # sched-5: 2026-10-13 -> excused
        # sched-6: 2026-10-14 -> unexcused
        mock_get_schedules.return_value = [
            {
                "id": "sched-1",
                "class_id": "class-1",
                "session_number": 1,
                "topic": "Nhập môn",
                "learning_date": date(2026, 10, 10),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "subject_id": "sub-1",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-2",
                "class_id": "class-1",
                "session_number": 2,
                "topic": "HTML & CSS",
                "learning_date": date(2026, 10, 10),
                "shift": "Ca 2",
                "start_time": time(13, 30),
                "end_time": time(17, 30),
                "subject_id": "sub-1",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-3",
                "class_id": "class-1",
                "session_number": 3,
                "topic": "JavaScript Cơ bản",
                "learning_date": date(2026, 10, 11),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "subject_id": "sub-1",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-4",
                "class_id": "class-1",
                "session_number": 4,
                "topic": "DOM & Events",
                "learning_date": date(2026, 10, 12),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "subject_id": "sub-1",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-5",
                "class_id": "class-1",
                "session_number": 5,
                "topic": "Async & Fetch",
                "learning_date": date(2026, 10, 13),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "subject_id": "sub-1",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-6",
                "class_id": "class-1",
                "session_number": 6,
                "topic": "React Overview",
                "learning_date": date(2026, 10, 14),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "subject_id": "sub-1",
                "subject_name": "Lập trình Web",
                "subject_code": "WEB101",
                "status": "scheduled",
                "attendance_checked": True,
            },
        ]

        mock_get_lifecycle.return_value = {
            "enrolled_at": date(2026, 10, 1),
            "status": "studying",
            "lifecycle_status": "studying",
            "effective_date": None,
        }

        mock_get_attendances.return_value = {
            "sched-1": {"status": "present", "notes": "Đúng giờ"},
            "sched-2": {"status": "late", "notes": "Muộn 10p"},
            "sched-3": {"status": "present", "notes": None},
            "sched-4": {"status": "present", "notes": None},
            "sched-5": {"status": "excused", "notes": "Nghỉ ốm có đơn"},
            "sched-6": {"status": "unexcused", "notes": "Không phép"},
        }

        res = client.get("/api/v1/me/attendance-history?class_id=class-1", headers=auth_headers)
        assert res.status_code == 200
        body = res.get_json()
        assert body["status"] == "success"
        data = body["data"]

        # Kiểm tra summary
        summary = data["summary"]
        assert summary["present_count"] == 3
        assert summary["late_count"] == 1
        assert summary["excused_count"] == 1
        assert summary["unexcused_count"] == 1
        assert summary["valid_sessions_count"] == 6
        assert summary["attendance_rate"] == 66.67
        assert summary["attendance_rate_formatted"] == "66.67%"

        # Kiểm tra hai buổi cùng ngày không bị gộp
        sessions = data["sessions"]
        assert len(sessions) == 6
        same_day_sessions = [s for s in sessions if s["learning_date"] == "2026-10-10"]
        assert len(same_day_sessions) == 2
        sched_ids = {s["schedule_id"] for s in same_day_sessions}
        assert sched_ids == {"sched-1", "sched-2"}

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_zero_valid_sessions_returns_null_attendance_rate(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_is_enrolled,
        mock_get_classes,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """D = 0: attendance_rate trả về null, attendance_rate_formatted trả 'Chưa có dữ liệu'."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "student-1", "student_code": "HV001"}
        mock_get_classes.return_value = [{"class_id": "class-1"}]
        mock_is_enrolled.return_value = True

        mock_get_class_details.return_value = {"id": "class-1", "program_id": "prog-1"}
        # Buổi trong tương lai năm 2099
        mock_get_schedules.return_value = [
            {
                "id": "sched-future",
                "class_id": "class-1",
                "session_number": 1,
                "learning_date": date(2099, 1, 1),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "status": "scheduled",
                "attendance_checked": False,
            }
        ]
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = {}

        res = client.get("/api/v1/me/attendance-history?class_id=class-1", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]
        assert data["summary"]["valid_sessions_count"] == 0
        assert data["summary"]["attendance_rate"] is None
        assert data["summary"]["attendance_rate_formatted"] == "Chưa có dữ liệu"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_filter_and_pagination_keep_class_wide_summary_intact(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_is_enrolled,
        mock_get_classes,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Lọc và phân trang chỉ ảnh hưởng tới mảng sessions, summary toàn lớp vẫn giữ nguyên."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "student-1", "student_code": "HV001"}
        mock_get_classes.return_value = [{"class_id": "class-1"}]
        mock_is_enrolled.return_value = True
        mock_get_class_details.return_value = {"id": "class-1", "program_id": "prog-1"}

        mock_get_schedules.return_value = [
            {
                "id": f"sched-{i}",
                "class_id": "class-1",
                "session_number": i,
                "learning_date": date(2026, 10, i),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "status": "scheduled",
                "attendance_checked": True,
            }
            for i in range(1, 6)
        ]
        mock_get_lifecycle.return_value = None
        # 3 present, 2 unexcused
        mock_get_attendances.return_value = {
            "sched-1": {"status": "present"},
            "sched-2": {"status": "present"},
            "sched-3": {"status": "present"},
            "sched-4": {"status": "unexcused"},
            "sched-5": {"status": "unexcused"},
        }

        # Filter: chỉ lấy 'unexcused', page_size=1
        res = client.get("/api/v1/me/attendance-history?class_id=class-1&status=unexcused&page_size=1", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        # sessions chỉ có 1 phần tử do page_size=1
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["status"] == "unexcused"
        assert data["pagination"]["total_items"] == 2
        assert data["pagination"]["total_pages"] == 2

        # Nhưng summary vẫn là 3 present, 2 unexcused (tổng lớp)
        summary = data["summary"]
        assert summary["present_count"] == 3
        assert summary["unexcused_count"] == 2
        assert summary["valid_sessions_count"] == 5
        assert summary["attendance_rate"] == 60.0

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_alias_endpoint_and_descending_sort(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_is_enrolled,
        mock_get_classes,
        mock_get_student,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Endpoint alias /api/v1/students/my-attendance-history hoạt động chuẩn và sắp xếp mặc định giảm dần (buổi gần nhất trước)."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "student-1", "student_code": "HV001"}
        mock_get_classes.return_value = [{"class_id": "class-1"}]
        mock_is_enrolled.return_value = True
        mock_get_class_details.return_value = {"id": "class-1", "program_id": "prog-1"}

        mock_get_schedules.return_value = [
            {
                "id": "sched-old",
                "class_id": "class-1",
                "session_number": 1,
                "learning_date": date(2026, 10, 1),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-new",
                "class_id": "class-1",
                "session_number": 2,
                "learning_date": date(2026, 10, 15),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "status": "scheduled",
                "attendance_checked": True,
            },
        ]
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = {}

        res = client.get("/api/v1/students/my-attendance-history?class_id=class-1", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]
        sessions = data["sessions"]
        assert len(sessions) == 2
        # Mặc định buổi gần nhất trước (desc): sched-new (15/10) đứng trước sched-old (01/10)
        assert sessions[0]["schedule_id"] == "sched-new"
        assert sessions[1]["schedule_id"] == "sched-old"
