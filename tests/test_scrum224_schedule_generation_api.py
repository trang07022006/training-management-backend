"""
Unit tests cho SCRUM-224 - Sinh thời khóa biểu tự động theo mẫu lặp.
- AC 1: Khai báo mẫu: các thứ trong tuần, ca học, ngày bắt đầu, số buổi.
- AC 2: Hệ thống sinh đủ buổi và tự bỏ qua ngày nghỉ lễ đã khai báo.
- AC 3: Xem trước danh sách buổi trước khi xác nhận lưu (không ghi DB).
- AC 4: Mỗi buổi được gắn với một bài học trong môn.
- Xử lý lỗi lưu và gửi lặp để tránh tạo lịch trùng do thao tác lặp.
"""

from datetime import date, datetime, timezone
import json
from unittest.mock import MagicMock, patch
import pytest

from app.main import app
from app.models.class_entity import ClassEntity
from app.models.class_schedule import ClassSchedule
from app.models.holiday import Holiday
from app.models.subject_session import SubjectSession


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
    mock_get_jwt.return_value = {"sid": "sess-test-123"}
    mock_get_identity.return_value = "user-test-123"
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-123"
    session_mock.user_id = "user-test-123"
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = True


class TestScheduleGenerationApi:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.holiday_repository.list_holidays")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    def test_preview_schedule_skips_holidays_and_binds_lessons(
        self,
        mock_list_lessons,
        mock_list_holidays,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 1, AC 2, AC 3, AC 4: Preview sinh đủ số buổi, bỏ qua ngày lễ, gắn bài học, không ghi DB."""
        _mock_auth(mock_verify, mock_get_jwt, mock_get_identity, mock_get_sess, mock_has_perm)

        # Mock lớp học
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

        # Mock ngày nghỉ lễ: 2026-11-20 (Thứ 6)
        mock_list_holidays.return_value = [
            Holiday(id="h1", holiday_date=date(2026, 11, 20), name="Ngày Nhà giáo Việt Nam"),
        ]

        # Mock các bài học môn học
        mock_list_lessons.return_value = [
            SubjectSession(id="sess-1", subject_id="sub-1", session_number=1, topic="Bài 1: Giới thiệu", objective="Nắm cơ bản"),
            SubjectSession(id="sess-2", subject_id="sub-1", session_number=2, topic="Bài 2: Cài đặt môi trường", objective="Setup dev"),
            SubjectSession(id="sess-3", subject_id="sub-1", session_number=3, topic="Bài 3: Cú pháp cơ bản", objective="Syntax"),
            SubjectSession(id="sess-4", subject_id="sub-1", session_number=4, topic="Bài 4: Hàm và Module", objective="Functions"),
        ]

        # Khai báo mẫu: Thứ 4 và Thứ 6, Ca 1, bắt đầu 2026-11-18 (Thứ 4), tổng 4 buổi
        # Lịch dự kiến:
        # 1. 2026-11-18 (Thứ 4) -> Bài 1
        # [2026-11-20 (Thứ 6) là ngày lễ -> BỎ QUA]
        # 2. 2026-11-25 (Thứ 4) -> Bài 2
        # 3. 2026-11-27 (Thứ 6) -> Bài 3
        # 4. 2026-12-02 (Thứ 4) -> Bài 4
        payload = {
            "days_of_week": [4, 6],  # Thứ 4 và Thứ 6
            "shift": "shift_1",
            "start_date": "2026-11-18",
            "total_sessions": 4,
            "subject_id": "sub-1",
        }

        resp = client.post(
            "/api/v1/classes/class-101/schedules/preview",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["total_generated"] == 4
        assert len(data["schedules"]) == 4

        # Kiểm tra ngày đã sinh
        dates = [s["learning_date"] for s in data["schedules"]]
        assert "2026-11-20" not in dates, "Ngày lễ 2026-11-20 phải được tự động bỏ qua"
        assert dates == ["2026-11-18", "2026-11-25", "2026-11-27", "2026-12-02"]

        # Kiểm tra danh sách ngày nghỉ đã bỏ qua được giải trình
        assert len(data["skipped_holidays"]) == 1
        assert data["skipped_holidays"][0]["date"] == "2026-11-20"
        assert data["skipped_holidays"][0]["holiday_name"] == "Ngày Nhà giáo Việt Nam"

        # Kiểm tra gắn bài học tương ứng (AC 4)
        assert data["schedules"][0]["session_number"] == 1
        assert data["schedules"][0]["subject_session_id"] == "sess-1"
        assert "Bài 1: Giới thiệu" in data["schedules"][0]["topic"]

        assert data["schedules"][1]["session_number"] == 2
        assert data["schedules"][1]["subject_session_id"] == "sess-2"
        assert "Bài 2: Cài đặt môi trường" in data["schedules"][1]["topic"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    def test_generate_schedule_blocks_duplicate_without_overwrite(
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
        """Xử lý chống gửi lặp: nếu lớp đã có lịch mà overwrite=False thì trả về lỗi 409."""
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
        mock_count.return_value = 10  # Đã có 10 buổi trong DB

        payload = {
            "days_of_week": [2, 4, 6],
            "shift": "shift_1",
            "start_date": "2026-11-18",
            "total_sessions": 10,
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

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.delete_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.insert_schedules_batch")
    @patch("app.repositories.holiday_repository.list_holidays")
    @patch("app.repositories.subject_session_repository.list_subject_sessions_by_subject")
    def test_generate_schedule_saves_when_overwrite_true(
        self,
        mock_list_lessons,
        mock_list_holidays,
        mock_insert_batch,
        mock_delete,
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
        """Xác nhận lưu khi overwrite=True thì xoá lịch cũ và lưu batch thành công."""
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
        mock_count.return_value = 5
        mock_list_holidays.return_value = []
        mock_list_lessons.return_value = []

        def fake_insert(schedules):
            return schedules
        mock_insert_batch.side_effect = fake_insert

        payload = {
            "days_of_week": [2, 4, 6],
            "shift": "shift_2",
            "start_date": "2026-11-02",
            "total_sessions": 3,
            "overwrite": True,
        }

        resp = client.post(
            "/api/v1/classes/class-101/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["total_saved"] == 3
        mock_delete.assert_called_once_with("class-101")
        mock_insert_batch.assert_called_once()

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.list_schedules_by_class_id")
    def test_get_class_schedules_returns_ordered_list(
        self,
        mock_list_schedules,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """Lấy danh sách thời khóa biểu của lớp học."""
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
        mock_list_schedules.return_value = [
            ClassSchedule(
                id="s-1",
                class_id="class-101",
                session_number=1,
                topic="Buổi 1",
                learning_date=date(2026, 11, 2),
                start_time="09:45:00",
                end_time="11:45:00",
                shift="Ca 2 (09:45 - 11:45)",
            )
        ]

        resp = client.get(
            "/api/v1/classes/class-101/schedules",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["total"] == 1
        assert data["schedules"][0]["session_number"] == 1
        assert data["schedules"][0]["learning_date"] == "2026-11-02"

    def test_unauthorized_access_returns_401(self, client):
        """Chưa đăng nhập -> 401."""
        resp = client.get("/api/v1/classes/class-101/schedules")
        assert resp.status_code == 401
