"""
Targeted tests cho SCRUM-258 AC2: Hiển thị cảnh báo khi đang tiến gần ngưỡng vắng.
- Tái sử dụng ngưỡng từ SCRUM-257 (mặc định 20% hoặc theo cấu hình chương trình đào tạo).
- Công thức: A = vắng (excused + unexcused), N = tổng buổi lịch xếp học viên phải tham dự.
- K = floor(T * N / 100).
- R = max(0, K - A) nếu chưa vượt.
- Trường hợp vượt ngưỡng: (A * 100 > T * N).
- Kiểm tra chính xác ví dụ Section 17 & 19:
  + A = 2: normal, còn 2 buổi.
  + A = 3: approaching, còn 1 buổi.
  + A = 4: at_limit (bằng ngưỡng 20%, chưa vượt, vắng thêm 1 buổi sẽ vượt).
  + A = 5: exceeded (25% > 20%).
- N = 0: insufficient_data.
- Buổi tương lai có đơn duyệt nghỉ không được cộng sớm vào A.
"""

from datetime import date, datetime, time, timezone
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


def _generate_20_sessions_setup(absent_count: int, threshold_pct: float = 20.0):
    """Tạo mock data cho 20 buổi học thực tế với absent_count buổi vắng."""
    class_info = {
        "id": "class-test-20",
        "class_code": "LOP-20",
        "program_id": "prog-test",
        "program_name": "CNTT Chuẩn",
        "status": "ongoing",
    }

    # 20 buổi đã kết thúc
    schedules = [
        {
            "id": f"sched-{i}",
            "class_id": "class-test-20",
            "session_number": i,
            "topic": f"Bài học {i}",
            "learning_date": date(2026, 9, 1),
            "shift": "Ca 1",
            "start_time": time(7, 30),
            "end_time": time(11, 30),
            "status": "scheduled",
            "attendance_checked": True,
        }
        for i in range(1, 21)
    ]

    # absent_count buổi đầu là excused/unexcused, các buổi sau là present
    attendances = {}
    for i in range(1, 21):
        if i <= absent_count:
            attendances[f"sched-{i}"] = {"status": "unexcused", "notes": "Vắng"}
        else:
            attendances[f"sched-{i}"] = {"status": "present", "notes": "Có mặt"}

    return class_info, schedules, attendances


class TestScrum258AC2AbsenceWarning:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_example_a2_normal(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_get_program,
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
        """Ví dụ bắt buộc Section 17: N=20, T=20%, A=2 -> K=4, R=2, warning_status='normal'."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "st-1", "student_code": "HV01"}
        mock_get_classes.return_value = [{"class_id": "class-test-20"}]
        mock_is_enrolled.return_value = True

        prog_mock = MagicMock()
        prog_mock.absence_alert_threshold = 20.0
        mock_get_program.return_value = prog_mock

        c_info, scheds, atts = _generate_20_sessions_setup(absent_count=2, threshold_pct=20.0)
        mock_get_class_details.return_value = c_info
        mock_get_schedules.return_value = scheds
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = atts

        res = client.get("/api/v1/me/attendance-history?class_id=class-test-20", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        w = data["absence_warning"]
        assert w["total_sessions_N"] == 20
        assert w["absent_sessions_A"] == 2
        assert w["threshold_T"] == 20.0
        assert w["max_allowed_absences_K"] == 4
        assert w["remaining_absences_R"] == 2
        assert w["warning_status"] == "normal"
        assert w["warning_level"] == "success"
        assert w["is_flagged"] is False
        assert "Bạn đã vắng 2/20 buổi. Theo ngưỡng 20% và lịch hiện tại, bạn có thể vắng thêm 2 buổi mà chưa vượt ngưỡng." in w["warning_message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_example_a3_approaching(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_get_program,
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
        """Ví dụ bắt buộc Section 17: N=20, T=20%, A=3 -> K=4, R=1, warning_status='approaching'."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "st-1", "student_code": "HV01"}
        mock_get_classes.return_value = [{"class_id": "class-test-20"}]
        mock_is_enrolled.return_value = True

        prog_mock = MagicMock()
        prog_mock.absence_alert_threshold = 20.0
        mock_get_program.return_value = prog_mock

        c_info, scheds, atts = _generate_20_sessions_setup(absent_count=3, threshold_pct=20.0)
        mock_get_class_details.return_value = c_info
        mock_get_schedules.return_value = scheds
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = atts

        res = client.get("/api/v1/me/attendance-history?class_id=class-test-20", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        w = data["absence_warning"]
        assert w["total_sessions_N"] == 20
        assert w["absent_sessions_A"] == 3
        assert w["max_allowed_absences_K"] == 4
        assert w["remaining_absences_R"] == 1
        assert w["warning_status"] == "approaching"
        assert w["warning_level"] == "warning"
        assert w["is_flagged"] is False
        assert "Bạn đang gần ngưỡng vắng. Hiện đã vắng 3/20 buổi; còn 1 buổi vắng trước khi chạm mức tối đa chưa vượt ngưỡng." in w["warning_message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_example_a4_at_limit(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_get_program,
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
        Ví dụ bắt buộc Section 17: N=20, T=20%, A=4.
        Quy tắc vượt là >: 4 * 100 = 400 không lớn hơn 20 * 20 = 400.
        -> CHƯA VƯỢT (is_flagged = False), R = 0, warning_status = 'at_limit'.
        Message: 'Bạn đã vắng 4/20 buổi, bằng ngưỡng 20%. Vắng thêm 1 buổi sẽ vượt ngưỡng.'
        """
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "st-1", "student_code": "HV01"}
        mock_get_classes.return_value = [{"class_id": "class-test-20"}]
        mock_is_enrolled.return_value = True

        prog_mock = MagicMock()
        prog_mock.absence_alert_threshold = 20.0
        mock_get_program.return_value = prog_mock

        c_info, scheds, atts = _generate_20_sessions_setup(absent_count=4, threshold_pct=20.0)
        mock_get_class_details.return_value = c_info
        mock_get_schedules.return_value = scheds
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = atts

        res = client.get("/api/v1/me/attendance-history?class_id=class-test-20", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        w = data["absence_warning"]
        assert w["total_sessions_N"] == 20
        assert w["absent_sessions_A"] == 4
        assert w["max_allowed_absences_K"] == 4
        assert w["remaining_absences_R"] == 0
        assert w["is_flagged"] is False
        assert w["warning_status"] == "at_limit"
        assert w["warning_level"] == "warning"
        assert "Bạn đã vắng 4/20 buổi, bằng ngưỡng 20%. Vắng thêm 1 buổi sẽ vượt ngưỡng." in w["warning_message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_example_a5_exceeded(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_get_program,
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
        Ví dụ bắt buộc Section 17: N=20, T=20%, A=5.
        5 * 100 = 500 > 400 -> ĐÃ VƯỢT NGƯỠNG (is_flagged = True), R = 0, warning_status = 'exceeded'.
        Tỷ lệ vắng: 25%.
        """
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "st-1", "student_code": "HV01"}
        mock_get_classes.return_value = [{"class_id": "class-test-20"}]
        mock_is_enrolled.return_value = True

        prog_mock = MagicMock()
        prog_mock.absence_alert_threshold = 20.0
        mock_get_program.return_value = prog_mock

        c_info, scheds, atts = _generate_20_sessions_setup(absent_count=5, threshold_pct=20.0)
        mock_get_class_details.return_value = c_info
        mock_get_schedules.return_value = scheds
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = atts

        res = client.get("/api/v1/me/attendance-history?class_id=class-test-20", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        w = data["absence_warning"]
        assert w["total_sessions_N"] == 20
        assert w["absent_sessions_A"] == 5
        assert w["is_flagged"] is True
        assert w["warning_status"] == "exceeded"
        assert w["warning_level"] == "danger"
        assert "Bạn đã vắng 5/20 buổi, tương đương 25%, vượt ngưỡng 20%. Vui lòng liên hệ giảng viên hoặc Quản lý đào tạo." in w["warning_message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_n_zero_insufficient_data(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_get_program,
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
        """N = 0: Không chia cho 0, trả insufficient_data = True, K=None, R=None."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "st-1", "student_code": "HV01"}
        mock_get_classes.return_value = [{"class_id": "class-empty"}]
        mock_is_enrolled.return_value = True

        mock_get_class_details.return_value = {
            "id": "class-empty",
            "class_code": "LOP-00",
            "program_id": "prog-1",
        }
        mock_get_schedules.return_value = []  # Không có buổi nào
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = {}

        res = client.get("/api/v1/me/attendance-history?class_id=class-empty", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        w = data["absence_warning"]
        assert w["total_sessions_N"] == 0
        assert w["insufficient_data"] is True
        assert w["is_flagged"] is False
        assert w["max_allowed_absences_K"] is None
        assert w["remaining_absences_R"] is None
        assert w["warning_status"] == "insufficient_data"
        assert w["warning_message"] == "Chưa đủ dữ liệu để tính ngưỡng."

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.attendance_history_repository.get_student_by_user_id")
    @patch("app.repositories.attendance_history_repository.get_student_enrolled_classes")
    @patch("app.repositories.attendance_history_repository.is_student_enrolled_in_class")
    @patch("app.repositories.training_program_repository.get_training_program_by_id")
    @patch("app.repositories.attendance_summary_repository.get_class_details")
    @patch("app.repositories.attendance_summary_repository.get_class_schedules_for_summary")
    @patch("app.repositories.attendance_history_repository.get_student_enrollment_lifecycle")
    @patch("app.repositories.attendance_history_repository.get_student_class_attendances")
    def test_future_approved_absence_not_counted_early(
        self,
        mock_get_attendances,
        mock_get_lifecycle,
        mock_get_schedules,
        mock_get_class_details,
        mock_get_program,
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
        """Buổi tương lai đã duyệt nghỉ đơn (excused) không được cộng sớm vào A (SCRUM-258 Mục 20)."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_student.return_value = {"id": "st-1", "student_code": "HV01"}
        mock_get_classes.return_value = [{"class_id": "class-test"}]
        mock_is_enrolled.return_value = True

        prog_mock = MagicMock()
        prog_mock.absence_alert_threshold = 20.0
        mock_get_program.return_value = prog_mock

        mock_get_class_details.return_value = {
            "id": "class-test",
            "class_code": "LOP-TEST",
            "program_id": "prog-1",
        }
        # 1 buổi quá khứ (present), 1 buổi tương lai (excused - đơn duyệt trước)
        mock_get_schedules.return_value = [
            {
                "id": "sched-past",
                "class_id": "class-test",
                "session_number": 1,
                "learning_date": date(2026, 1, 1),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "status": "scheduled",
                "attendance_checked": True,
            },
            {
                "id": "sched-future-excused",
                "class_id": "class-test",
                "session_number": 2,
                "learning_date": date(2099, 1, 1),
                "shift": "Ca 1",
                "start_time": time(7, 30),
                "end_time": time(11, 30),
                "status": "scheduled",
                "attendance_checked": False,
            },
        ]
        mock_get_lifecycle.return_value = None
        mock_get_attendances.return_value = {
            "sched-past": {"status": "present"},
            "sched-future-excused": {"status": "excused", "notes": "Đã duyệt đơn xin nghỉ trước"},
        }

        res = client.get("/api/v1/me/attendance-history?class_id=class-test", headers=auth_headers)
        assert res.status_code == 200
        data = res.get_json()["data"]

        w = data["absence_warning"]
        assert w["total_sessions_N"] == 2
        # A không được cộng buổi tương lai
        assert w["absent_sessions_A"] == 0
        assert w["max_allowed_absences_K"] == 0
        assert w["remaining_absences_R"] == 0
        assert w["is_flagged"] is False
