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


def transfer_student_service(student_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """
    Xử lý chuyển lớp cho học viên theo ngày hiệu lực (SCRUM-252 - Lát cắt 252.2).
    - Chọn lớp nguồn, lớp đích, lý do, ngày hiệu lực.
    - Kiểm tra lớp đích tồn tại, khác lớp nguồn, đủ điều kiện tiếp nhận và không ghi danh trùng.
    - Kiểm tra tương thích chương trình đào tạo.
    - Kiểm tra sức chứa theo cơ chế ghi danh hiện có.
    - Thay đổi tham gia lớp nguồn/lớp đích theo ngày hiệu lực trong một transaction nguyên tử.
    - Giữ nguyên điểm và điểm danh ở lớp cũ.
    - Ghi lịch sử chuyển lớp.
    """
    # 1. Kiểm tra học viên tồn tại
    student = student_repository.get_student_by_id(student_id)
    if not student:
        raise StudentLifecycleError("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học viên.", 404)

    # 2. Kiểm tra dữ liệu đầu vào
    if not isinstance(payload, dict):
        raise StudentLifecycleError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không hợp lệ.", 400)

    source_class_id = payload.get("source_class_id")
    if not source_class_id or not isinstance(source_class_id, str) or not source_class_id.strip():
        raise StudentLifecycleError("MISSING_SOURCE_CLASS_ID", "Vui lòng chọn lớp nguồn cần chuyển đi.", 400)
    source_class_id = source_class_id.strip()

    target_class_id = payload.get("target_class_id")
    if not target_class_id or not isinstance(target_class_id, str) or not target_class_id.strip():
        raise StudentLifecycleError("MISSING_TARGET_CLASS_ID", "Vui lòng chọn lớp đích cần chuyển đến.", 400)
    target_class_id = target_class_id.strip()

    if source_class_id == target_class_id:
        raise StudentLifecycleError("SAME_CLASS", "Lớp đích phải khác lớp nguồn.", 400)

    reason = _validate_reason(payload.get("reason"))
    effective_date_val = _parse_date(payload.get("effective_date"), "effective_date")

    # 3. Kiểm tra lớp nguồn và lớp đích tồn tại
    src_cls = class_repository.get_class_by_id(source_class_id)
    if not src_cls:
        raise StudentLifecycleError("SOURCE_CLASS_NOT_FOUND", "Không tìm thấy lớp học nguồn.", 404)

    tgt_cls = class_repository.get_class_by_id(target_class_id)
    if not tgt_cls:
        raise StudentLifecycleError("TARGET_CLASS_NOT_FOUND", "Không tìm thấy lớp học đích.", 404)

    # Kiểm tra trạng thái lớp đích
    if tgt_cls.status not in ("preparing", "in_progress"):
        raise StudentLifecycleError("TARGET_CLASS_INACTIVE", "Lớp đích không ở trạng thái sẵn sàng tiếp nhận học viên.", 400)

    # Kiểm tra tương thích chương trình đào tạo
    if src_cls.program_id != tgt_cls.program_id:
        raise StudentLifecycleError("PROGRAM_MISMATCH", "Lớp đích phải thuộc cùng chương trình đào tạo với lớp nguồn.", 400)

    # Kiểm tra ranh giới ngày hiệu lực không được trước ngày khai giảng lớp nguồn
    if src_cls.expected_start_date:
        start_date_val = src_cls.expected_start_date if isinstance(src_cls.expected_start_date, date) else datetime.strptime(str(src_cls.expected_start_date)[:10], "%Y-%m-%d").date()
        if effective_date_val < start_date_val:
            raise StudentLifecycleError(
                "EFFECTIVE_DATE_BEFORE_START",
                f"Ngày hiệu lực chuyển lớp ({effective_date_val.strftime('%d/%m/%Y')}) không được trước ngày khai giảng lớp nguồn ({start_date_val.strftime('%d/%m/%Y')}).",
                400,
            )

    # 4. Thực hiện transaction nguyên tử trong repository
    try:
        result = student_lifecycle_repository.record_transfer_atomic(
            student_id=student_id,
            source_class_id=source_class_id,
            target_class_id=target_class_id,
            effective_date_val=effective_date_val,
            reason=reason,
            actor_id=actor_id,
        )
    except RuntimeError as err:
        err_msg = str(err)
        if "SAME_CLASS" in err_msg:
            raise StudentLifecycleError("SAME_CLASS", "Lớp đích phải khác lớp nguồn.", 400)
        if "SOURCE_ENROLLMENT_NOT_FOUND" in err_msg:
            raise StudentLifecycleError("SOURCE_ENROLLMENT_NOT_FOUND", "Học viên chưa được ghi danh vào lớp nguồn.", 404)
        if "SOURCE_CLASS_RESERVED" in err_msg:
            raise StudentLifecycleError("SOURCE_CLASS_RESERVED", "Học viên đang bảo lưu tại lớp nguồn, không thể chuyển lớp.", 400)
        if "INVALID_LIFECYCLE_STATE" in err_msg:
            raise StudentLifecycleError("INVALID_LIFECYCLE_STATE", err_msg, 400)
        if "ALREADY_ENROLLED_IN_TARGET" in err_msg:
            raise StudentLifecycleError("ALREADY_ENROLLED_IN_TARGET", "Học viên đã có trong danh sách của lớp đích.", 400)
        if "TARGET_CLASS_FULL" in err_msg:
            raise StudentLifecycleError("TARGET_CLASS_FULL", "Lớp đích đã đủ sĩ số tối đa, không thể tiếp nhận thêm học viên.", 400)
        if "PROGRAM_MISMATCH" in err_msg:
            raise StudentLifecycleError("PROGRAM_MISMATCH", "Lớp đích phải thuộc cùng chương trình đào tạo với lớp nguồn.", 400)
        if "TARGET_CLASS_INACTIVE" in err_msg:
            raise StudentLifecycleError("TARGET_CLASS_INACTIVE", "Lớp đích không ở trạng thái sẵn sàng tiếp nhận học viên.", 400)
        raise StudentLifecycleError("TRANSFER_FAILED", f"Lỗi xử lý chuyển lớp: {err_msg}", 500)

    result["student_name"] = student.full_name
    result["student_code"] = student.student_code

    return result


def drop_student_service(student_id: str, payload: dict[str, Any], actor_id: str) -> dict[str, Any]:
    """
    Xử lý thôi học cho học viên theo ngày hiệu lực (SCRUM-252 - Lát cắt 252.3).
    - Scope = 'single' (thôi học 1 lớp) hoặc 'all' (thôi học toàn bộ khóa học).
    - Nhập lý do bắt buộc, ngày hiệu lực bắt buộc.
    - Cập nhật tình trạng tham gia, danh sách điểm danh và sĩ số theo quy tắc.
    - Tuyệt đối không xóa hồ sơ, điểm, điểm danh lịch sử hay tài khoản đăng nhập.
    """
    # 1. Kiểm tra học viên tồn tại
    student = student_repository.get_student_by_id(student_id)
    if not student:
        raise StudentLifecycleError("STUDENT_NOT_FOUND", "Không tìm thấy hồ sơ học viên.", 404)

    # 2. Kiểm tra payload
    if not isinstance(payload, dict):
        raise StudentLifecycleError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không hợp lệ.", 400)

    scope = payload.get("scope", "single")
    if scope not in ("single", "all"):
        raise StudentLifecycleError("INVALID_SCOPE", "Phạm vi thôi học không hợp lệ (yêu cầu 'single' hoặc 'all').", 400)

    class_id = payload.get("class_id")
    if scope == "single":
        if not class_id or not isinstance(class_id, str) or not class_id.strip():
            raise StudentLifecycleError("MISSING_CLASS_ID", "Vui lòng chọn lớp học cần thôi học.", 400)
        class_id = class_id.strip()

        cls_obj = class_repository.get_class_by_id(class_id)
        if not cls_obj:
            raise StudentLifecycleError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", 404)

    reason = _validate_reason(payload.get("reason"))
    effective_date_val = _parse_date(payload.get("effective_date"), "effective_date")

    # Kiểm tra ranh giới ngày hiệu lực không được trước ngày khai giảng nếu thôi học 1 lớp
    if scope == "single" and class_id:
        enrollment = student_lifecycle_repository.get_enrollment_by_class_and_student(class_id, student_id)
        if not enrollment:
            raise StudentLifecycleError("ENROLLMENT_NOT_FOUND", "Học viên chưa được ghi danh vào lớp học này.", 404)
        expected_start = enrollment.get("expected_start_date")
        if expected_start:
            start_date_val = expected_start if isinstance(expected_start, date) else datetime.strptime(str(expected_start)[:10], "%Y-%m-%d").date()
            if effective_date_val < start_date_val:
                raise StudentLifecycleError(
                    "EFFECTIVE_DATE_BEFORE_START",
                    f"Ngày hiệu lực thôi học ({effective_date_val.strftime('%d/%m/%Y')}) không được trước ngày khai giảng lớp ({start_date_val.strftime('%d/%m/%Y')}).",
                    400,
                )

    # 3. Thực hiện transaction nguyên tử trong repository
    try:
        result = student_lifecycle_repository.record_drop_atomic(
            student_id=student_id,
            scope=scope,
            class_id=class_id,
            effective_date_val=effective_date_val,
            reason=reason,
            actor_id=actor_id,
        )
    except RuntimeError as err:
        err_msg = str(err)
        if "ENROLLMENT_NOT_FOUND" in err_msg:
            raise StudentLifecycleError("ENROLLMENT_NOT_FOUND", "Không tìm thấy bản ghi ghi danh.", 404)
        if "ALREADY_DROPPED" in err_msg:
            raise StudentLifecycleError("ALREADY_DROPPED", "Học viên đã thôi học ở lớp này.", 400)
        if "NO_ACTIVE_ENROLLMENTS" in err_msg:
            raise StudentLifecycleError("NO_ACTIVE_ENROLLMENTS", "Học viên không có lớp học nào đang tham gia để thôi học.", 400)
        raise StudentLifecycleError("DROP_FAILED", f"Lỗi xử lý thôi học: {err_msg}", 500)

    result["student_name"] = student.full_name
    result["student_code"] = student.student_code

    return result
