"""
Unit tests kiểm thử thông báo lỗi chi tiết khi hệ thống từ chối lưu thời khóa biểu (SCRUM-224 / SCRUM-225).
Kiểm thử 8 trường hợp thực tế:
1. Thiếu quyền: Trả mã 403 FORBIDDEN kèm "Bạn không có quyền tạo thời khóa biểu cho lớp này."
2. Môn không thuộc lớp: Trả mã 400 SUBJECT_NOT_IN_CLASS kèm "Môn học đã chọn không thuộc lớp này. Vui lòng chọn lại." và field="subject_id".
3. Trùng giảng viên: Trả mã 409 SCHEDULE_CONFLICT_DETECTED kèm tên giảng viên, ngày, giờ, lớp bị trùng.
4. Trùng phòng: Trả mã 409 SCHEDULE_CONFLICT_DETECTED kèm phòng, ngày, giờ, lớp bị trùng.
5. Lịch đã tồn tại: Trả mã 409 SCHEDULE_ALREADY_EXISTS kèm phạm vi lịch (số buổi, khoảng ngày) và hướng xử lý ghi đè.
6. Thiếu dữ liệu bắt buộc:
   - Thiếu days_of_week -> DAYS_OF_WEEK_REQUIRED kèm field="days_of_week"
   - Thiếu start_date -> START_DATE_REQUIRED kèm field="start_date"
   - Thiếu total_sessions -> TOTAL_SESSIONS_REQUIRED kèm field="total_sessions"
   - Sai ca học -> INVALID_SHIFT_TIME kèm field="shift"
7. Lỗi máy chủ không xác định (500): Trả mã INTERNAL_SERVER_ERROR kèm mã tra cứu lỗi (error_ref), không lộ SQL, stack trace.
"""

from datetime import date, datetime, timezone
import json
from unittest.mock import MagicMock, patch
import pytest

from app.main import app
from app.models.class_entity import ClassEntity, ClassSubject
from app.models.class_schedule import ClassSchedule
from mysql.connector import Error as MySQLError


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


def _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, allowed=True):
    mock_verify.return_value = None
    mock_get_jwt.return_value = {"sid": "sess-test-123"}
    mock_get_identity.return_value = "user-test-123"
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-123"
    session_mock.user_id = "user-test-123"
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = allowed


class TestScheduleSaveErrorMessages:
    """Kiểm thử chi tiết từng mã lỗi và thông điệp nghiệp vụ cụ thể khi từ chối lưu thời khóa biểu."""

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    def test_forbidden_returns_custom_schedule_permission_message(
        self,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 1: Thiếu quyền -> 403 'Bạn không có quyền tạo thời khóa biểu cho lớp này.'"""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm, allowed=False)

        resp = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps({"start_date": "2026-11-01", "total_sessions": 5, "days_of_week": [2]}),
            headers=auth_headers,
        )

        assert resp.status_code == 403
        body = resp.get_json()
        assert body["code"] == "FORBIDDEN"
        assert body["message"] == "Bạn không có quyền tạo thời khóa biểu cho lớp này."

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_repository.get_class_subjects")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    def test_subject_not_in_class_returns_specific_error(
        self,
        mock_count,
        mock_get_subjects,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 2: Môn học đã chọn không thuộc lớp -> 400 SUBJECT_NOT_IN_CLASS."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_class.return_value = ClassEntity(
            id="class-101",
            class_code="L01-2026",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 1),
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        mock_count.return_value = 0
        now = datetime.now(timezone.utc)
        mock_get_subjects.return_value = [
            ClassSubject(id="cs-1", class_id="class-101", subject_id="sub-math", semester=1, is_mandatory=True, order_index=1, created_at=now, updated_at=now),
            ClassSubject(id="cs-2", class_id="class-101", subject_id="sub-physics", semester=1, is_mandatory=True, order_index=2, created_at=now, updated_at=now),
        ]

        payload = {
            "days_of_week": [2, 4],
            "shift": "shift_1",
            "start_date": "2026-11-02",
            "total_sessions": 2,
            "subject_id": "sub-chemistry",
        }

        resp = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == "SUBJECT_NOT_IN_CLASS"
        assert body["message"] == "Môn học đã chọn không thuộc lớp này. Vui lòng chọn lại."
        assert body["field"] == "subject_id"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    def test_instructor_conflict_states_instructor_date_time_and_class(
        self,
        mock_find_conflicts,
        mock_count,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 3: Trùng giảng viên -> Nêu rõ tên giảng viên, ngày, giờ và lớp bị trùng."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_class.return_value = ClassEntity(
            id="class-new",
            class_code="L02-PYTHON",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        mock_count.return_value = 0
        mock_find_conflicts.return_value = [
            {
                "id": "existing-sched-1",
                "class_id": "class-other",
                "class_code": "L01-JAVA",
                "session_number": 2,
                "topic": "Bài 2",
                "learning_date": "2026-11-02",
                "start_time": "07:30:00",
                "end_time": "09:30:00",
                "room_id": "P101",
                "instructor_id": "inst-101",
                "instructor_name": "ThS. Lê Văn B",
                "status": "scheduled",
            }
        ]

        payload = {
            "days_of_week": [2],
            "shift": "shift_1",
            "start_date": "2026-11-02",
            "total_sessions": 1,
            "instructor_id": "inst-101",
            "allow_conflict_override": False,
        }

        resp = client.post(
            "/api/v1/classes/class-new/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body["code"] == "SCHEDULE_CONFLICT_DETECTED"
        assert "ThS. Lê Văn B" in body["message"]
        assert "2026-11-02" in body["message"]
        assert "07:30:00" in body["message"]
        assert "L01-JAVA" in body["message"]
        assert len(body["data"]["conflicts"]) == 1

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    def test_room_conflict_states_room_date_time_and_class(
        self,
        mock_find_conflicts,
        mock_count,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 4: Trùng phòng -> Nêu rõ phòng, ngày, giờ và lớp bị trùng."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_class.return_value = ClassEntity(
            id="class-new",
            class_code="L02-PYTHON",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 2),
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        mock_count.return_value = 0
        mock_find_conflicts.return_value = [
            {
                "id": "existing-sched-1",
                "class_id": "class-other",
                "class_code": "L01-JAVA",
                "session_number": 2,
                "topic": "Bài 2",
                "learning_date": "2026-11-02",
                "start_time": "07:30:00",
                "end_time": "09:30:00",
                "room_id": "P.301",
                "instructor_id": "inst-different",
                "status": "scheduled",
            }
        ]

        payload = {
            "days_of_week": [2],
            "shift": "shift_1",
            "start_date": "2026-11-02",
            "total_sessions": 1,
            "room_id": "P.301",
            "allow_conflict_override": False,
        }

        resp = client.post(
            "/api/v1/classes/class-new/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body["code"] == "SCHEDULE_CONFLICT_DETECTED"
        assert "P.301" in body["message"]
        assert "2026-11-02" in body["message"]
        assert "07:30:00" in body["message"]
        assert "L01-JAVA" in body["message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.list_schedules_by_class_id")
    def test_existing_schedule_explains_scope_and_resolution(
        self,
        mock_list_schedules,
        mock_count,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 5: Lịch đã tồn tại -> Giải thích phạm vi (số buổi, từ ngày... đến ngày...) và hướng dẫn ghi đè."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_class.return_value = ClassEntity(
            id="class-101",
            class_code="L01-2026",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 1),
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        mock_count.return_value = 8
        mock_list_schedules.return_value = [
            ClassSchedule(id="s1", class_id="class-101", session_number=1, topic="Buổi 1", learning_date=date(2026, 11, 2), shift="Ca 1", start_time="07:30:00", end_time="09:30:00"),
            ClassSchedule(id="s8", class_id="class-101", session_number=8, topic="Buổi 8", learning_date=date(2026, 11, 27), shift="Ca 1", start_time="07:30:00", end_time="09:30:00"),
        ]

        payload = {
            "days_of_week": [2, 4],
            "shift": "shift_1",
            "start_date": "2026-11-02",
            "total_sessions": 8,
            "overwrite": False,
        }

        resp = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body["code"] == "SCHEDULE_ALREADY_EXISTS"
        assert "8 buổi học" in body["message"]
        assert "02/11/2026" in body["message"]
        assert "27/11/2026" in body["message"]
        assert "Ghi đè lịch đã có" in body["message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    def test_missing_required_fields_points_to_exact_field(
        self,
        mock_count,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 6: Thiếu dữ liệu bắt buộc -> Chỉ rõ trường cần bổ sung và field key tương ứng."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        mock_get_class.return_value = ClassEntity(
            id="class-101",
            class_code="L01-2026",
            program_id="prog-1",
            expected_start_date=date(2026, 11, 1),
            max_capacity=30,
            learning_mode="offline",
            status="preparing",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        mock_count.return_value = 0

        # 6a. Thiếu days_of_week
        resp1 = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps({"shift": "shift_1", "start_date": "2026-11-02", "total_sessions": 5}),
            headers=auth_headers,
        )
        assert resp1.status_code == 400
        assert resp1.get_json()["code"] == "DAYS_OF_WEEK_REQUIRED"
        assert resp1.get_json()["field"] == "days_of_week"

        # 6b. Thiếu start_date
        resp2 = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps({"days_of_week": [2], "shift": "shift_1", "total_sessions": 5}),
            headers=auth_headers,
        )
        assert resp2.status_code == 400
        assert resp2.get_json()["code"] == "START_DATE_REQUIRED"
        assert resp2.get_json()["field"] == "start_date"

        # 6c. Thiếu total_sessions
        resp3 = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps({"days_of_week": [2], "shift": "shift_1", "start_date": "2026-11-02"}),
            headers=auth_headers,
        )
        assert resp3.status_code == 400
        assert resp3.get_json()["code"] == "TOTAL_SESSIONS_REQUIRED"
        assert resp3.get_json()["field"] == "total_sessions"

        # 6d. Ca học không hợp lệ
        resp4 = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps({"days_of_week": [2], "shift": "custom", "start_date": "2026-11-02", "total_sessions": 5}),
            headers=auth_headers,
        )
        assert resp4.status_code == 400
        assert resp4.get_json()["code"] == "INVALID_SHIFT_TIME"
        assert resp4.get_json()["field"] == "shift"

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.services.schedule_service.generate_schedule_service")
    def test_unexpected_server_error_returns_safe_lookup_code_without_sql_leak(
        self,
        mock_generate,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Trường hợp 7 & 8: Lỗi máy chủ không xác định -> Trả mã tra cứu error_ref, không lộ SQL hay stack trace."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)
        # Giả lập lỗi DB chứa thông tin nhạy cảm (SQL query, password, stack trace)
        mock_generate.side_effect = MySQLError(1064, "You have an error in your SQL syntax near 'SELECT * FROM secret_table'")

        payload = {
            "days_of_week": [2],
            "shift": "shift_1",
            "start_date": "2026-11-02",
            "total_sessions": 2,
        }

        resp = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 500
        body = resp.get_json()
        assert body["status"] == "error"
        assert body["code"] == "INTERNAL_SERVER_ERROR"
        assert "error_ref" in body
        assert body["error_ref"].startswith("ERR-")
        assert body["error_ref"] in body["message"]

        # Bảo mật: Tuyệt đối không để lộ thông tin nhạy cảm
        resp_text = resp.get_data(as_text=True)
        assert "SELECT * FROM secret_table" not in resp_text
        assert "MySQLError" not in resp_text
        assert "Traceback" not in resp_text
