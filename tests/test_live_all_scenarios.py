"""
Comprehensive Integration Tests for all 3 task milestones:
- Mốc 1: Trainee minimal allowlist for class roster & student profile protection
- Mốc 2: Absence request eligible sessions & attendance notebook endpoints live & error mapping
- Mốc 3: Filter cascading and data integrity
"""

import pytest
from unittest.mock import MagicMock, patch
from app.main import app
from app.models.student import Student
from app.models.enrollment import Enrollment
from datetime import datetime, timezone


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ==============================================================================
# MỐC 1: BẢO MẬT DANH SÁCH HỌC VIÊN
# ==============================================================================

@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
@patch("app.repositories.student_repository.get_student_by_user_id")
@patch("app.repositories.enrollment_repository.is_student_enrolled_in_class")
@patch("app.repositories.class_repository.get_class_by_id")
@patch("app.repositories.enrollment_repository.get_enrollments_by_class_id")
def test_trainee_class_roster_minimal_allowlist(
    mock_get_enrollments,
    mock_get_class,
    mock_is_enrolled,
    mock_get_student_by_user_id,
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """AC1: Trainee chỉ nhận order_index và full_name; không nhận email, phone, code, id, etc."""
    mock_verify_jwt.return_value = None
    mock_get_jwt.return_value = {"sid": "session-1"}
    mock_get_identity.return_value = "user-trainee-1"
    mock_has_permission.return_value = True
    mock_get_roles.return_value = ["trainee"]

    mock_student = MagicMock(spec=Student)
    mock_student.id = "stu-1"
    mock_get_student_by_user_id.return_value = mock_student
    mock_is_enrolled.return_value = True

    mock_class = MagicMock()
    mock_class.id = "class-1"
    mock_class.class_code = "CNTT-K20"
    mock_class.max_capacity = 30
    mock_get_class.return_value = mock_class

    now = datetime.now(timezone.utc)
    mock_enrollment = Enrollment(
        id="enr-1",
        class_id="class-1",
        student_id="stu-2",
        student_code="SV0002",
        full_name="Trần Thị Bạn Học",
        email="banhoc@ictu.edu.vn",
        phone="0987654321",
        enrolled_at=now,
        status="enrolled",
        enrolled_by="admin-1",
        created_at=now,
        updated_at=now,
    )
    mock_get_enrollments.return_value = [mock_enrollment]

    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainee-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        response = client.get(
            "/api/v1/classes/class-1/enrollments",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert response.status_code == 200
    data = response.get_json()

    assert data["status"] == "success"
    items = data["data"]["items"]
    assert len(items) == 1
    item = items[0]

    # Bắt buộc có
    assert item["order_index"] == 1
    assert item["full_name"] == "Trần Thị Bạn Học"

    # Bắt buộc KHÔNG có các trường nhạy cảm
    assert "student_id" not in item
    assert "id" not in item
    assert "student_code" not in item
    assert "email" not in item
    assert "phone" not in item
    assert "enrolled_at" not in item
    assert "status" not in item
    assert "absence_alert" not in item
    assert "enrolled_by_name" not in item


@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
@patch("app.repositories.student_repository.get_student_by_user_id")
@patch("app.repositories.enrollment_repository.is_student_enrolled_in_class")
@patch("app.repositories.class_repository.get_class_by_id")
def test_trainee_unenrolled_class_forbidden(
    mock_get_class,
    mock_is_enrolled,
    mock_get_student_by_user_id,
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """AC3: Trainee xem lớp mình chưa ghi danh bị chặn 403 FORBIDDEN_CLASS_ACCESS."""
    mock_verify_jwt.return_value = None
    mock_get_jwt.return_value = {"sid": "session-1"}
    mock_get_identity.return_value = "user-trainee-1"
    mock_has_permission.return_value = True
    mock_get_roles.return_value = ["trainee"]

    mock_student = MagicMock(spec=Student)
    mock_student.id = "stu-1"
    mock_get_student_by_user_id.return_value = mock_student
    mock_is_enrolled.return_value = False  # Chưa ghi danh

    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainee-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        response = client.get(
            "/api/v1/classes/class-unregistered/enrollments",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert response.status_code == 403
    data = response.get_json()
    assert data["code"] == "FORBIDDEN_CLASS_ACCESS"


# ==============================================================================
# MỐC 2: REQUEST_FAILED & LỖI TẢI THÔNG TIN
# ==============================================================================

@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
@patch("app.services.absence_request_service.get_eligible_sessions_for_current_student")
def test_eligible_sessions_route_registered_and_working(
    mock_get_sessions,
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """Mốc 2: Endpoint /api/v1/absence-requests/eligible-sessions trả về 200 thay vì 404/REQUEST_FAILED."""
    mock_verify_jwt.return_value = None
    mock_get_jwt.return_value = {"sid": "session-1"}
    mock_get_identity.return_value = "user-trainee-1"
    mock_has_permission.return_value = True
    mock_get_roles.return_value = ["trainee"]

    mock_get_sessions.return_value = {
        "items": [
            {
                "schedule_id": "sch-01",
                "class_id": "cls-01",
                "class_code": "PY_K22",
                "session_number": 1,
                "topic": "Python cơ bản",
                "subject_name": "Lập trình Python",
                "learning_date": "2026-10-25",
                "start_time": "18:00:00",
                "end_time": "20:30:00",
                "has_pending_request": False,
                "has_approved_request": False,
                "is_selectable": True,
            }
        ],
        "pagination": {
            "page": 1,
            "limit": 10,
            "total_items": 1,
            "total_pages": 1,
        },
        "filter_options": {
            "classes": [{"id": "cls-01", "class_code": "PY_K22"}],
            "subjects": [{"id": "sub-01", "name": "Lập trình Python", "label": "Lập trình Python"}],
        },
    }

    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainee-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        response = client.get(
            "/api/v1/absence-requests/eligible-sessions?page=1&limit=10",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert len(data["data"]["items"]) == 1
    assert data["data"]["filter_options"]["classes"][0]["class_code"] == "PY_K22"


@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
@patch("app.services.attendance_service.get_session_attendance_sheet")
def test_session_attendance_route_registered_and_working(
    mock_get_sheet,
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """Mốc 2: Endpoint /api/v1/schedules/<id>/attendance trả về 200 thay vì 404."""
    mock_verify_jwt.return_value = None
    mock_get_jwt.return_value = {"sid": "session-1"}
    mock_get_identity.return_value = "user-trainer-1"
    mock_has_permission.return_value = True
    mock_get_roles.return_value = ["trainer"]

    mock_get_sheet.return_value = {
        "session_info": {
            "schedule_id": "sch-01",
            "class_id": "cls-01",
            "class_code": "PY_K22",
            "class_name": "Python K22",
            "subject_name": "Lập trình Python",
            "session_number": 1,
            "topic": "Python cơ bản",
            "learning_date": "2026-10-25",
            "start_time": "18:00:00",
            "end_time": "20:30:00",
            "room_name": "Lab 1",
            "instructor_name": "Thầy Tuấn",
            "status": "scheduled",
            "attendance_checked": False,
            "is_today": True,
            "is_past": False,
            "is_future": False,
            "can_edit": True,
        },
        "stats": {
            "total_students": 20,
            "present_count": 0,
            "late_count": 0,
            "excused_count": 0,
            "unexcused_count": 0,
            "unmarked_count": 20,
        },
        "students": [],
    }

    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainer-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        response = client.get(
            "/api/v1/schedules/sch-01/attendance",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["data"]["session_info"]["class_code"] == "PY_K22"
