"""
Service xử lý nghiệp vụ Lịch sử điểm danh cá nhân của Học viên (SCRUM-258).
Bảo vệ quyền sở hữu dữ liệu từ phiên đăng nhập, kiểm tra phân quyền truy cập lớp và định dạng dữ liệu trả về.
"""

from datetime import date
import logging
from typing import Any, Optional

from app.repositories import attendance_history_repository

logger = logging.getLogger(__name__)


class AttendanceHistoryError(Exception):
    """Lỗi nghiệp vụ cơ bản của lịch sử điểm danh."""
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class StudentProfileNotFoundError(AttendanceHistoryError):
    def __init__(self, message: str = "Tài khoản của bạn chưa được liên kết với hồ sơ học viên. Vui lòng liên hệ Quản lý đào tạo."):
        super().__init__("STUDENT_PROFILE_NOT_FOUND", message, status_code=404)


class ForbiddenClassAccessError(AttendanceHistoryError):
    def __init__(self, message: str = "Bạn không có quyền truy cập thông tin điểm danh của lớp học này."):
        super().__init__("FORBIDDEN_CLASS_ACCESS", message, status_code=403)


class ClassNotFoundError(AttendanceHistoryError):
    def __init__(self, message: str = "Không tìm thấy thông tin lớp học yêu cầu."):
        super().__init__("CLASS_NOT_FOUND", message, status_code=404)


class InvalidQueryParamsError(AttendanceHistoryError):
    def __init__(self, message: str = "Tham số truy vấn không hợp lệ."):
        super().__init__("INVALID_QUERY_PARAMS", message, status_code=400)


def get_my_attendance_history_service(
    user_id: str,
    class_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "learning_date",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """
    Xử lý xem lịch sử điểm danh cá nhân cho học viên đăng nhập.
    - Ánh xạ nghiêm ngặt user_id từ JWT sang hồ sơ học viên (SCRUM-258 Mục 4).
    - Không tin cậy bất kỳ student_id do client gửi lên.
    - Kiểm tra quan hệ ghi danh / lịch sử lớp hợp lệ (SCRUM-258 Mục 5).
    - Tính toán tổng quan chuyên cần toàn lớp và cảnh báo vắng độc lập với bộ lọc hiển thị.
    """
    if not user_id:
        raise AttendanceHistoryError("UNAUTHORIZED", "Yêu cầu đăng nhập để truy cập lịch sử điểm danh.", status_code=401)

    # 1. Tìm hồ sơ học viên
    student = attendance_history_repository.get_student_by_user_id(user_id)
    if not student:
        raise StudentProfileNotFoundError()

    student_id = student["id"]

    # 2. Lấy danh sách lớp học viên đã ghi danh
    enrolled_classes = attendance_history_repository.get_student_enrolled_classes(student_id)

    # 3. Xác định lớp học cần xem
    target_class_id = class_id.strip() if class_id and class_id.strip() else None

    if not target_class_id:
        if not enrolled_classes:
            return {
                "student": {
                    "id": student_id,
                    "student_code": student.get("student_code"),
                    "full_name": student.get("full_name"),
                    "email": student.get("email"),
                    "program_name": student.get("program_name"),
                },
                "enrolled_classes": [],
                "selected_class_id": None,
                "class_info": None,
                "summary": None,
                "absence_warning": None,
                "sessions": [],
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total_items": 0,
                    "total_pages": 1,
                },
                "message": "Học viên chưa ghi danh vào lớp học nào.",
            }
        target_class_id = enrolled_classes[0]["class_id"]
    else:
        # Kiểm tra quyền xem của học viên đối với lớp này
        is_allowed = attendance_history_repository.is_student_enrolled_in_class(student_id, target_class_id)
        if not is_allowed:
            raise ForbiddenClassAccessError()

    # 4. Validate query parameters
    try:
        page = int(page)
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        raise InvalidQueryParamsError("Tham số 'page' phải là số nguyên dương >= 1.")

    try:
        page_size = int(page_size)
        if page_size < 1:
            page_size = 20
        elif page_size > 100:
            page_size = 100
    except (ValueError, TypeError):
        raise InvalidQueryParamsError("Tham số 'page_size' phải là số nguyên từ 1 đến 100.")

    valid_statuses = {"all", "present", "late", "excused", "unexcused", "not_recorded", "future", "cancelled"}
    norm_status = status_filter.strip().lower() if status_filter and status_filter.strip() else None
    if norm_status and norm_status not in valid_statuses:
        raise InvalidQueryParamsError(f"Trạng thái lọc '{status_filter}' không hợp lệ. Các giá trị cho phép: {', '.join(sorted(valid_statuses))}")

    if date_from and date_from.strip():
        try:
            date.fromisoformat(date_from.strip())
        except ValueError:
            raise InvalidQueryParamsError("Tham số 'date_from' không đúng định dạng YYYY-MM-DD.")

    if date_to and date_to.strip():
        try:
            date.fromisoformat(date_to.strip())
        except ValueError:
            raise InvalidQueryParamsError("Tham số 'date_to' không đúng định dạng YYYY-MM-DD.")

    norm_sort_order = "asc" if sort_order and sort_order.strip().lower() == "asc" else "desc"

    # 5. Truy xuất lịch sử điểm danh
    history_data = attendance_history_repository.get_student_attendance_history(
        student_id=student_id,
        class_id=target_class_id,
        status_filter=norm_status,
        date_from=date_from.strip() if date_from else None,
        date_to=date_to.strip() if date_to else None,
        page=page,
        page_size=page_size,
        sort_by="learning_date",
        sort_order=norm_sort_order,
    )

    if not history_data:
        raise ClassNotFoundError()

    return {
        "student": {
            "id": student_id,
            "student_code": student.get("student_code"),
            "full_name": student.get("full_name"),
            "email": student.get("email"),
            "program_name": student.get("program_name"),
        },
        "enrolled_classes": enrolled_classes,
        "selected_class_id": target_class_id,
        **history_data,
    }
