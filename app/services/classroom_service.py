import uuid
from typing import Any
from app.models.classroom import Classroom
from app.repositories import classroom_repository, class_repository


class ClassroomServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def create_classroom_service(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Khai báo phòng học vật lý hoặc phòng học trực tuyến (SCRUM-221 - 221-01).
    - Phòng vật lý: room_code, room_name, capacity > 0.
    - Phòng trực tuyến: room_code, room_name, online_link hợp lệ. Không yêu cầu capacity.
    """
    if not isinstance(payload, dict):
        raise ClassroomServiceError("INVALID_PAYLOAD", "Dữ liệu yêu cầu không hợp lệ.", 400)

    room_code = str(payload.get("room_code") or "").strip()
    if not room_code:
        raise ClassroomServiceError("MISSING_ROOM_CODE", "Vui lòng nhập mã phòng học.", 400)

    # Kiểm tra mã phòng duy nhất
    existing = classroom_repository.get_classroom_by_code(room_code)
    if existing:
        raise ClassroomServiceError("ROOM_CODE_EXISTS", f"Mã phòng học '{room_code}' đã tồn tại trong hệ thống.", 409)

    room_name = str(payload.get("room_name") or "").strip()
    if not room_name:
        raise ClassroomServiceError("MISSING_ROOM_NAME", "Vui lòng nhập tên phòng học.", 400)

    raw_type = str(payload.get("room_type") or "physical").strip().lower()
    if raw_type not in ("physical", "online"):
        raise ClassroomServiceError("INVALID_ROOM_TYPE", "Loại phòng học phải là 'physical' (vật lý) hoặc 'online' (trực tuyến).", 400)

    capacity = None
    online_link = None

    if raw_type == "physical":
        raw_capacity = payload.get("capacity")
        if raw_capacity is None:
            raise ClassroomServiceError("MISSING_CAPACITY", "Phòng vật lý bắt buộc phải có sức chứa.", 400)
        try:
            capacity = int(raw_capacity)
        except (ValueError, TypeError):
            raise ClassroomServiceError("INVALID_CAPACITY", "Sức chứa phòng học phải là một số nguyên dương hợp lệ.", 400)
        if capacity <= 0:
            raise ClassroomServiceError("INVALID_CAPACITY", "Sức chứa phòng vật lý phải lớn hơn 0.", 400)
    else:  # online
        online_link = str(payload.get("online_link") or "").strip()
        if not online_link:
            raise ClassroomServiceError("MISSING_ONLINE_LINK", "Phòng trực tuyến bắt buộc phải có liên kết phòng học.", 400)
        # Phòng trực tuyến không áp đặt capacity vật lý
        capacity = None

    classroom = Classroom(
        id=str(uuid.uuid4()),
        room_code=room_code,
        room_name=room_name,
        room_type=raw_type,
        capacity=capacity,
        online_link=online_link,
        status="active",
    )

    created = classroom_repository.insert_classroom(classroom)
    return created.to_dict()


def list_classrooms_service(
    room_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Lấy danh sách phòng học có phân trang và lọc."""
    items, total = classroom_repository.list_classrooms(
        room_type=room_type,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [item.to_dict() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_classroom_detail_service(classroom_id: str) -> dict[str, Any]:
    """Lấy chi tiết phòng học theo ID."""
    room = classroom_repository.get_classroom_by_id(classroom_id)
    if not room:
        raise ClassroomServiceError("ROOM_NOT_FOUND", "Không tìm thấy phòng học.", 404)
    return room.to_dict()


def check_room_capacity_service(classroom_id: str, class_id: str) -> dict[str, Any]:
    """
    Kiểm tra và cảnh báo sĩ số lớp vượt sức chứa phòng học (SCRUM-221 - 221-02).
    - Jira: Cảnh báo khi sĩ số lớp vượt sức chứa phòng (warning only, không chặn).
    - Basis so sánh: CLASS_MAX_CAPACITY (hoặc current enrollment nếu lớn hơn).
    - Phòng online: không áp cảnh báo sức chứa vật lý.
    """
    room = classroom_repository.get_classroom_by_id(classroom_id)
    if not room:
        raise ClassroomServiceError("ROOM_NOT_FOUND", "Không tìm thấy phòng học.", 404)

    cls = class_repository.get_class_by_id(class_id)
    if not cls:
        raise ClassroomServiceError("CLASS_NOT_FOUND", "Không tìm thấy lớp học.", 404)

    # Với phòng online: không có capacity -> không cảnh báo
    if room.room_type == "online" or room.capacity is None:
        return {
            "room_id": room.id,
            "room_code": room.room_code,
            "room_type": room.room_type,
            "room_capacity": None,
            "class_id": cls.id,
            "class_code": cls.class_code,
            "class_size": cls.max_capacity,
            "basis": "CLASS_MAX_CAPACITY",
            "is_exceeded": False,
            "warning": False,
            "warning_message": None,
        }

    # Với phòng vật lý: so sánh class size với room capacity
    class_size = cls.max_capacity
    enrolled_count = cls.enrolled_count or 0
    effective_size = max(class_size, enrolled_count)

    is_exceeded = effective_size > room.capacity
    warning_message = None
    if is_exceeded:
        warning_message = f"Sĩ số lớp vượt sức chứa phòng. (Lớp: {effective_size} học viên – Phòng: {room.capacity} chỗ)"

    return {
        "room_id": room.id,
        "room_code": room.room_code,
        "room_type": room.room_type,
        "room_capacity": room.capacity,
        "class_id": cls.id,
        "class_code": cls.class_code,
        "class_size": effective_size,
        "basis": "CLASS_MAX_CAPACITY",
        "is_exceeded": is_exceeded,
        "warning": is_exceeded,
        "warning_message": warning_message,
    }
