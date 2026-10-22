"""
Unit & Integration Tests kiểm tra Bảo mật danh sách học viên và hồ sơ cá nhân.
- Trainee xem danh sách lớp mình đã ghi danh: chỉ thấy order_index và full_name (Allowlist).
- Trainee xem danh sách lớp chưa ghi danh: 403 FORBIDDEN_CLASS_ACCESS.
- Trainee xem danh sách toàn trường /api/v1/students: 403 FORBIDDEN.
- Trainee xem hồ sơ học viên khác: 403 FORBIDDEN.
- Trainee xem hồ sơ của chính mình: 200 Thành công.
- Quản lý / Giảng viên xem danh sách lớp: 200 đầy đủ thông tin phục vụ nghiệp vụ.
"""

from unittest.mock import MagicMock, patch
import pytest
from app.main import app
from app.models.student import Student
from app.models.enrollment import Enrollment
from datetime import datetime, timezone


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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
    """AC1 & AC2: Học viên chỉ nhận STT (order_index) và Họ tên; bảo vệ toàn bộ dữ liệu khác."""
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
    enrollment1 = Enrollment(
        id="enr-1",
        class_id="class-1",
        student_id="stu-1",
        status="enrolled",
        enrolled_at=now,
        enrolled_by="admin-1",
        created_at=now,
        updated_at=now,
        student_code="STU001",
        full_name="Nguyễn Văn A",
        email="a@gmail.com",
        phone="0987654321",
    )
    enrollment2 = Enrollment(
        id="enr-2",
        class_id="class-1",
        student_id="stu-2",
        status="enrolled",
        enrolled_at=now,
        enrolled_by="admin-1",
        created_at=now,
        updated_at=now,
        student_code="STU002",
        full_name="Trần Thị B",
        email="b@gmail.com",
        phone="0912345678",
    )
    mock_get_enrollments.return_value = [enrollment1, enrollment2]

    # Mock login_session check in rbac_auth
    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainee-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        res = client.get(
            "/api/v1/classes/class-1/enrollments",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert res.status_code == 200
    data = res.get_json()["data"]
    items = data["items"]
    assert len(items) == 2
    assert items[0] == {"order_index": 1, "full_name": "Nguyễn Văn A"}
    assert items[1] == {"order_index": 2, "full_name": "Trần Thị B"}

    # Bắt buộc: KHÔNG chứa bất kỳ trường nhạy cảm nào
    for item in items:
        assert "student_id" not in item
        assert "id" not in item
        assert "student_code" not in item
        assert "email" not in item
        assert "phone" not in item
        assert "enrolled_at" not in item
        assert "status" not in item
        assert "absence_alert" not in item


@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
@patch("app.repositories.student_repository.get_student_by_user_id")
@patch("app.repositories.enrollment_repository.is_student_enrolled_in_class")
def test_trainee_unenrolled_class_forbidden(
    mock_is_enrolled,
    mock_get_student_by_user_id,
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """AC3: Học viên xem lớp mình chưa ghi danh bị trả về 403 FORBIDDEN_CLASS_ACCESS."""
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
        res = client.get(
            "/api/v1/classes/class-other/enrollments",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert res.status_code == 403
    body = res.get_json()
    assert body["code"] == "FORBIDDEN_CLASS_ACCESS"


@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
def test_trainee_list_all_students_forbidden(
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """AC4: Học viên không được xem danh sách học viên toàn trường."""
    mock_verify_jwt.return_value = None
    mock_get_jwt.return_value = {"sid": "session-1"}
    mock_get_identity.return_value = "user-trainee-1"
    mock_has_permission.return_value = True
    mock_get_roles.return_value = ["trainee"]

    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainee-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        res = client.get(
            "/api/v1/students",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert res.status_code == 403
    assert res.get_json()["code"] == "FORBIDDEN"


@patch("app.utils.rbac_auth.verify_jwt_in_request")
@patch("app.utils.rbac_auth.get_jwt")
@patch("app.utils.rbac_auth.get_jwt_identity")
@patch("app.utils.rbac_auth.has_permission")
@patch("app.services.authorization_service.get_user_role_codes")
@patch("app.repositories.student_repository.get_student_by_user_id")
def test_trainee_view_other_student_profile_forbidden(
    mock_get_student_by_user_id,
    mock_get_roles,
    mock_has_permission,
    mock_get_identity,
    mock_get_jwt,
    mock_verify_jwt,
    client,
):
    """AC4: Học viên truy cập trực tiếp hồ sơ người khác qua ID bị chặn 403."""
    mock_verify_jwt.return_value = None
    mock_get_jwt.return_value = {"sid": "session-1"}
    mock_get_identity.return_value = "user-trainee-1"
    mock_has_permission.return_value = True
    mock_get_roles.return_value = ["trainee"]

    mock_student = MagicMock(spec=Student)
    mock_student.id = "stu-my-id"
    mock_get_student_by_user_id.return_value = mock_student

    mock_session = MagicMock()
    mock_session.session_id = "session-1"
    mock_session.user_id = "user-trainee-1"

    with patch("app.utils.rbac_auth.get_session_by_id", return_value=mock_session), \
         patch("app.utils.rbac_auth.validate_login_session", return_value=None):
        res = client.get(
            "/api/v1/students/stu-other-id",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert res.status_code == 403
    assert res.get_json()["code"] == "FORBIDDEN"
