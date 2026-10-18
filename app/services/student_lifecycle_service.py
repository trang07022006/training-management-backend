"""
Dịch vụ nghiệp vụ Quản lý Vòng đời học viên (Student Lifecycle Service) - SCRUM-252.
Xử lý các nghiệp vụ:
- Lát cắt 252.1: Bảo lưu theo ngày hiệu lực
- Lát cắt 252.2: Chuyển lớp và giữ lịch sử
- Lát cắt 252.3: Thôi học theo ngày hiệu lực
- Lát cắt 252.4: Tra cứu lịch sử vòng đời
"""

from datetime import date, datetime
import logging
from typing import Any

from app.repositories import (
    class_repository,
    student_lifecycle_repository,
    student_repository,
)

logger = logging.getLogger(__name__)


class StudentLifecycleError(Exception):
    """Lỗi nghiệp vụ xử lý vòng đời học viên."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _parse_date(date_str: Any, field_name: str = "effective_date") -> date:
    """Kiểm tra và chuẩn hóa chuỗi ngày YYYY-MM-DD thành date object."""
    if not date_str or not isinstance(date_str, str):
        raise StudentLifecycleError(
            f"MISSING_{field_name.upper()}",
            f"{field_name} là bắt buộc và phải có định dạng YYYY-MM-DD.",
            400,
        )
    trimmed = date_str.strip()
    try:
        return datetime.strptime(trimmed, "%Y-%m-%d").date()
    except ValueError:
        raise StudentLifecycleError(
            f"INVALID_{field_name.upper()}_FORMAT",
            f"{field_name} không hợp lệ, yêu cầu định dạng YYYY-MM-DD.",
            400,
        )


def _validate_reason(reason_val: Any) -> str:
    """Kiểm tra lý do bắt buộc và không được chỉ chứa khoảng trắng."""
    if not reason_val or not isinstance(reason_val, str) or not reason_val.strip():
        raise StudentLifecycleError(
            "MISSING_REASON",
            "Lý do thao tác là bắt buộc và không được chỉ chứa khoảng trắng.",
            400,
        )
    return reason_val.strip()


def reserve_student_service(student_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """
    Xử lý bảo lưu học viên theo ngày hiệu lực (SCRUM-252 - Lát cắt 252.1).
    - Quản lý đào tạo chọn học viên và lớp/ghi danh thuộc phạm vi.
    - Nhập lý do bắt buộc và ngày hiệu lực bắt buộc.
    - Kiểm tra tính hợp lệ: sinh viên tồn tại, lớp tồn tại, đang ghi danh.
    - Ngày hiệu lực: hôm nay, tương lai hoặc quá khứ (không trước ngày khai giảng lớp).
    - Lưu nguyên tử thay đổi vào class_enrollments và student_lifecycle_history.
    """
    # 1. Kiểm tra học viên tồn tại
    student = student_repository.get_student_by_id(student_id)
    if not student:
        raise StudentLifecycleError("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học viên.", 404)

    # 2. Kiểm tra dữ liệu đầu vào
    if not isinstance(payload, dict):
        raise StudentLifecycleError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không hợp lệ.", 400)

    class_id = payload.get("class_id")
    if not class_id or not isinstance(class_id, str) or not class_id.strip():
        raise StudentLifecycleError("MISSING_CLASS_ID", "Vui lòng chọn lớp học cần bảo lưu.", 400)
    class_id = class_id.strip()

    reason = _validate_reason(payload.get("reason"))
    effective_date_val = _parse_date(payload.get("effective_date"), "effective_date")

    # 3. Kiểm tra bản ghi ghi danh hiện tại
    enrollment = student_lifecycle_repository.get_enrollment_by_class_and_student(class_id, student_id)
    if not enrollment:
        raise StudentLifecycleError(
            "ENROLLMENT_NOT_FOUND",
            "Học viên chưa được ghi danh vào lớp học này.",
            404,
        )

    # Kiểm tra trạng thái ghi danh
    curr_lifecycle = enrollment.get("lifecycle_status")
    if curr_lifecycle == "reserved":
        raise StudentLifecycleError("ALREADY_RESERVED", "Học viên đã được bảo lưu ở lớp học này.", 400)
    if curr_lifecycle in ("transferred", "dropped"):
        raise StudentLifecycleError(
            "INVALID_LIFECYCLE_STATE",
            f"Học viên đang ở trạng thái {curr_lifecycle}, không thể thực hiện bảo lưu.",
            400,
        )

    # 4. Kiểm tra ranh giới ngày hiệu lực không được trước ngày khai giảng lớp (nếu có)
    expected_start = enrollment.get("expected_start_date")
    if expected_start:
        start_date_val = expected_start if isinstance(expected_start, date) else datetime.strptime(str(expected_start)[:10], "%Y-%m-%d").date()
        if effective_date_val < start_date_val:
            raise StudentLifecycleError(
                "EFFECTIVE_DATE_BEFORE_START",
                f"Ngày hiệu lực bảo lưu ({effective_date_val.strftime('%d/%m/%Y')}) không được trước ngày khai giảng lớp ({start_date_val.strftime('%d/%m/%Y')}).",
                400,
            )

    # 5. Thực hiện giao dịch nguyên tử trong repository
    try:
        result = student_lifecycle_repository.record_reservation_atomic(
            student_id=student_id,
            class_id=class_id,
            effective_date_val=effective_date_val,
            reason=reason,
            actor_id=actor_id,
        )
    except RuntimeError as err:
        err_msg = str(err)
        if "ALREADY_RESERVED" in err_msg:
            raise StudentLifecycleError("ALREADY_RESERVED", "Học viên đã được bảo lưu ở lớp học này.", 400)
        if "ENROLLMENT_NOT_FOUND" in err_msg:
            raise StudentLifecycleError("ENROLLMENT_NOT_FOUND", "Không tìm thấy bản ghi ghi danh.", 404)
        if "INVALID_LIFECYCLE_STATE" in err_msg:
            raise StudentLifecycleError("INVALID_LIFECYCLE_STATE", err_msg, 400)
        raise StudentLifecycleError("RESERVATION_FAILED", f"Lỗi xử lý bảo lưu: {err_msg}", 500)

    result["student_name"] = student.full_name
    result["student_code"] = student.student_code
    result["class_code"] = enrollment.get("class_code")

    return result


def get_eligible_attendance_students_service(class_id: str, session_date_str: str) -> dict[str, Any]:
    """
    Lấy danh sách học viên đủ điều kiện điểm danh cho buổi học tại một ngày cụ thể (SCRUM-252 AC 2).
    """
    session_date_val = _parse_date(session_date_str, "session_date")
    cls_obj = class_repository.get_class_by_id(class_id)
    if not cls_obj:
        raise StudentLifecycleError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", 404)

    students = student_lifecycle_repository.get_eligible_attendance_students(class_id, session_date_val)
    return {
        "class_id": class_id,
        "class_code": cls_obj.class_code,
        "session_date": session_date_val.isoformat(),
        "total_eligible": len(students),
        "students": students,
    }


def get_student_lifecycle_history_service(student_id: str) -> list[dict[str, Any]]:
    """
    Lấy toàn bộ lịch sử biến động vòng đời học viên (SCRUM-252 - Lát cắt 252.4).
    """
    student = student_repository.get_student_by_id(student_id)
    if not student:
        raise StudentLifecycleError("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học viên.", 404)

    history_items = student_lifecycle_repository.get_student_lifecycle_history(student_id)
    return [item.to_dict() for item in history_items]
