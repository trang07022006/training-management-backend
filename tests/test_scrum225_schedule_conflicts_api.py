"""
Unit tests cho SCRUM-225 - Cảnh báo và kiểm tra xung đột lịch giảng viên và phòng học.
- AC 1: Kiểm tra trùng theo giảng viên và theo phòng trong cùng khung giờ.
- AC 2: Hiển thị rõ buổi nào đang xung đột với buổi nào (mã lớp, buổi số, giờ học, tên GV/phòng).
- AC 3: Trùng là lỗi chặn, không cho lưu, trừ khi Quản lý đào tạo xác nhận ghi đè.
- Kiểm tra khoảng thời gian thực tế giao nhau (time overlap), không chỉ so giờ bắt đầu.
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
    mock_get_jwt.return_value = {"sid": "sess-test-225"}
    mock_get_identity.return_value = "manager-user-225"
    session_mock = MagicMock()
    session_mock.session_id = "sess-test-225"
    session_mock.user_id = "manager-user-225"
    session_mock.revoked_at = None
    session_mock.idle_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    session_mock.absolute_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_get_sess.return_value = session_mock
    mock_has_perm.return_value = True


class TestScheduleConflictsApi:

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    def test_preview_detects_instructor_and_room_conflicts_with_db(
        self,
        mock_find_conflicts,
        mock_get_class,
        mock_verify,
        mock_get_jwt,
        mock_get_identity,
        mock_get_sess,
        mock_has_perm,
        client,
        auth_headers,
    ):
        """AC 1, AC 2: Preview phát hiện trùng giảng viên và phòng học từ DB và giải trình rõ ràng."""
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

        # Giả lập DB trả về xung đột cho buổi đầu tiên
        # Buổi này trùng Giảng viên với Lớp L01-JAVA Buổi #5
        def fake_find_conflicts(learning_date, start_time, end_time, instructor_id, room_id, exclude_class_id=None, exclude_schedule_id=None):
            if str(learning_date) == "2026-11-02":
                return [
                    {
                        "id": "existing-sched-1",
                        "class_id": "class-other",
                        "class_code": "L01-JAVA",
                        "session_number": 5,
                        "topic": "Lập trình hướng đối tượng",
                        "learning_date": "2026-11-02",
                        "shift": "Ca 1",
                        "start_time": "07:30:00",
                        "end_time": "09:30:00",
                        "room_id": "P201",
                        "instructor_id": "inst-101",
                        "instructor_name": "TS. Nguyễn Văn A",
                        "status": "scheduled",
                    }
                ]
            return []

        mock_find_conflicts.side_effect = fake_find_conflicts

        payload = {
            "days_of_week": [2],  # Thứ 2
            "shift": "shift_1",   # 07:30 - 09:30
            "start_date": "2026-11-02",
            "total_sessions": 2,
            "instructor_id": "inst-101",
            "room_id": "P201",
        }

        resp = client.post(
            "/api/v1/classes/class-new/schedules/preview",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["has_conflicts"] is True
        assert len(data["conflicts"]) >= 1

        # Kiểm tra chi tiết thông tin xung đột (AC 2)
        conflict = data["conflicts"][0]
        assert conflict["session_number"] == 1
        assert conflict["conflicting_class_code"] == "L01-JAVA"
        assert conflict["conflicting_session_number"] == 5
        assert "TS. Nguyễn Văn A" in conflict["message"]

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    def test_generate_schedule_blocks_when_conflict_detected_without_override(
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
        """AC 3: Trùng là lỗi chặn, trả về 409 SCHEDULE_CONFLICT_DETECTED nếu chưa xác nhận ghi đè."""
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

        # Có xung đột trong DB
        mock_find_conflicts.return_value = [
            {
                "id": "existing-sched-1",
                "class_id": "class-other",
                "class_code": "L01-JAVA",
                "session_number": 2,
                "topic": "Bài học 2",
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
            "allow_conflict_override": False,  # Chưa xác nhận ghi đè
        }

        resp = client.post(
            "/api/v1/classes/class-new/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 409
        body = resp.get_json()
        assert body["code"] == "SCHEDULE_CONFLICT_DETECTED"
        assert "conflicts" in body["data"]
        assert len(body["data"]["conflicts"]) >= 1

    @patch("app.utils.rbac_auth.has_permission")
    @patch("app.utils.rbac_auth.get_session_by_id")
    @patch("app.utils.rbac_auth.get_jwt_identity")
    @patch("app.utils.rbac_auth.get_jwt")
    @patch("app.utils.rbac_auth.verify_jwt_in_request")
    @patch("app.repositories.class_repository.get_class_by_id")
    @patch("app.repositories.class_schedule_repository.count_schedules_by_class_id")
    @patch("app.repositories.class_schedule_repository.find_conflicts_for_slot")
    @patch("app.repositories.class_schedule_repository.insert_schedules_batch")
    def test_generate_schedule_saves_when_override_confirmed_by_manager(
        self,
        mock_insert_batch,
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
        """AC 3: Cho phép lưu khi Quản lý đào tạo xác nhận ghi đè (allow_conflict_override=True)."""
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

        # Có xung đột nhưng người dùng chủ động cho phép ghi đè
        mock_find_conflicts.return_value = [
            {
                "id": "existing-sched-1",
                "class_id": "class-other",
                "class_code": "L01-JAVA",
                "session_number": 2,
                "topic": "Bài học 2",
                "learning_date": "2026-11-02",
                "start_time": "07:30:00",
                "end_time": "09:30:00",
                "room_id": "P101",
                "instructor_id": "inst-101",
                "instructor_name": "ThS. Lê Văn B",
                "status": "scheduled",
            }
        ]

        def fake_insert(schedules):
            return schedules
        mock_insert_batch.side_effect = fake_insert

        payload = {
            "days_of_week": [2],
            "shift": "shift_1",
            "start_date": "2026-11-02",
            "total_sessions": 1,
            "instructor_id": "inst-101",
            "allow_conflict_override": True,  # Quản lý đào tạo xác nhận ghi đè
        }

        resp = client.post(
            "/api/v1/classes/class-new/schedules/generate",
            data=json.dumps(payload),
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["total_saved"] == 1
        assert data["overridden_conflicts_count"] >= 1
        mock_insert_batch.assert_called_once()
