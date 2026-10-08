"""
Service layer cho quản lý buổi học của môn học (SCRUM-129 - Subject Sessions).
Bao gồm:
- Định nghĩa các Exception chuẩn hóa (SubjectSessionServiceError và các lớp con).
- get_subject_sessions_service: Lấy danh sách buổi học theo môn học.
- get_subject_session_detail_service: Lấy chi tiết một buổi học (bảo vệ chống IDOR).
"""

from typing import Any
import uuid

from app.models.subject import SUBJECT_STATUS_ARCHIVED
from app.models.subject_session import SubjectSession
from app.repositories import subject_repository, subject_session_repository


def is_valid_uuid(val: str) -> bool:
    """Kiểm tra chuỗi có đúng định dạng UUID hay không."""
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        parsed = uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError, AttributeError):
        return False


class SubjectSessionServiceError(Exception):
    """Ngoại lệ cơ sở cho nghiệp vụ buổi học."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class SubjectNotFoundError(SubjectSessionServiceError):
    """Ngoại lệ khi không tìm thấy môn học (404)."""

    def __init__(self, message: str = "Không tìm thấy môn học."):
        super().__init__(code="SUBJECT_NOT_FOUND", message=message, status_code=404)


class SubjectSessionNotFoundError(SubjectSessionServiceError):
    """Ngoại lệ khi không tìm thấy buổi học trong môn học (404)."""

    def __init__(self, message: str = "Không tìm thấy buổi học của môn học."):
        super().__init__(code="SUBJECT_SESSION_NOT_FOUND", message=message, status_code=404)


class SubjectSessionValidationError(SubjectSessionServiceError):
    """Ngoại lệ khi dữ liệu đầu vào không hợp lệ (400)."""

    def __init__(self, message: str, code: str = "INVALID_PARAMS"):
        super().__init__(code=code, message=message, status_code=400)


class DuplicateSessionNumberError(SubjectSessionServiceError):
    """Ngoại lệ khi số thứ tự buổi học bị trùng trong môn học (409)."""

    def __init__(self, message: str = "Số thứ tự buổi học đã tồn tại trong môn học."):
        super().__init__(code="DUPLICATE_SESSION_NUMBER", message=message, status_code=409)


class SubjectArchivedError(SubjectSessionServiceError):
    """Ngoại lệ khi môn học đã lưu trữ, không cho sửa đổi buổi học (400)."""

    def __init__(self, message: str = "Môn học đã lưu trữ, không thể thay đổi buổi học."):
        super().__init__(code="SUBJECT_ARCHIVED", message=message, status_code=400)


class TotalSessionsExceededError(SubjectSessionServiceError):
    """Ngoại lệ khi số thứ tự buổi học vượt quá tổng số buổi cấu hình (400)."""

    def __init__(self, message: str = "Số thứ tự buổi học vượt quá tổng số buổi của môn học."):
        super().__init__(code="TOTAL_SESSIONS_EXCEEDED", message=message, status_code=400)


def get_subject_sessions_service(subject_id: str) -> dict:
    """
    Lấy danh sách các buổi học của một môn học (SCRUM-129 - Activity A2 / SCRUM-174).
    - Validate subject_id đúng UUID (400 INVALID_PARAMS).
    - Kiểm tra môn học có tồn tại không (404 SUBJECT_NOT_FOUND).
    - Sắp xếp tăng dần theo session_number.
    - Trả về thông tin tóm tắt môn học và danh sách buổi học.
    """
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise SubjectSessionValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    cleaned_subject_id = subject_id.strip().lower()
    subject = subject_repository.get_subject_by_id(cleaned_subject_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    sessions = subject_session_repository.list_subject_sessions_by_subject(cleaned_subject_id)

    return {
        "subject": {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "status": subject.status,
            "total_sessions": subject.total_sessions,
        },
        "items": [sess.to_dict() for sess in sessions],
    }


def get_subject_session_detail_service(subject_id: str, session_id: str) -> dict:
    """
    Lấy chi tiết một buổi học theo subject_id và session_id (SCRUM-129 - Activity A2).
    - Validate subject_id và session_id đúng UUID (400 INVALID_PARAMS).
    - Kiểm tra môn học tồn tại (404 SUBJECT_NOT_FOUND).
    - Kiểm tra buổi học tồn tại và thuộc môn học (404 SUBJECT_SESSION_NOT_FOUND - chống IDOR).
    """
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise SubjectSessionValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(session_id, str) or not is_valid_uuid(session_id):
        raise SubjectSessionValidationError(
            "Mã định danh buổi học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    cleaned_subject_id = subject_id.strip().lower()
    cleaned_session_id = session_id.strip().lower()

    subject = subject_repository.get_subject_by_id(cleaned_subject_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    session = subject_session_repository.get_subject_session_by_id(cleaned_session_id)
    if session is None or session.subject_id != cleaned_subject_id:
        raise SubjectSessionNotFoundError("Không tìm thấy buổi học của môn học.")

    return session.to_dict()


def create_subject_session_service(subject_id: str, payload: Any) -> dict:
    """
    Thêm một buổi học mới cho môn học (SCRUM-129 - Activity A3 / SCRUM-175).
    - Validate subject_id đúng UUID (400 INVALID_PARAMS).
    - Môn học phải tồn tại (404 SUBJECT_NOT_FOUND).
    - Môn học ở trạng thái archived -> từ chối (400 SUBJECT_ARCHIVED).
    - session_number: bắt buộc, số nguyên, >= 1.
    - session_number <= total_sessions (nếu total_sessions != None).
    - topic: bắt buộc, string, 1..255 ký tự.
    - objective: bắt buộc, string, 1..5000 ký tự.
    - Trùng (subject_id, session_number) -> 409 DUPLICATE_SESSION_NUMBER.
    - Sinh UUID cho id, server-controlled timestamps UTC.
    """
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise SubjectSessionValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(payload, dict):
        raise SubjectSessionValidationError(
            "Dữ liệu yêu cầu phải là đối tượng JSON.",
            code="INVALID_PARAMS",
        )

    cleaned_subject_id = subject_id.strip().lower()
    subject = subject_repository.get_subject_by_id(cleaned_subject_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    # Kiểm tra trạng thái archived
    if subject.status == SUBJECT_STATUS_ARCHIVED:
        raise SubjectArchivedError("Môn học đã lưu trữ, không thể thêm buổi học.")

    # 1. Validate session_number
    if "session_number" not in payload or payload["session_number"] is None:
        raise SubjectSessionValidationError(
            "Số thứ tự buổi học (session_number) là bắt buộc.",
            code="INVALID_PARAMS",
        )

    raw_num = payload["session_number"]
    if isinstance(raw_num, bool) or not isinstance(raw_num, int):
        raise SubjectSessionValidationError(
            "Số thứ tự buổi học phải là số nguyên hợp lệ.",
            code="INVALID_PARAMS",
        )

    session_number = int(raw_num)
    if session_number < 1:
        raise SubjectSessionValidationError(
            "Số thứ tự buổi học phải lớn hơn hoặc bằng 1.",
            code="INVALID_PARAMS",
        )

    if subject.total_sessions is not None:
        if session_number > subject.total_sessions:
            raise TotalSessionsExceededError(
                f"Số thứ tự buổi học vượt quá tổng số buổi của môn học (tối đa {subject.total_sessions})."
            )

    # 2. Validate topic
    if "topic" not in payload or payload["topic"] is None:
        raise SubjectSessionValidationError(
            "Chủ đề buổi học (topic) là bắt buộc.",
            code="INVALID_PARAMS",
        )

    if not isinstance(payload["topic"], str):
        raise SubjectSessionValidationError(
            "Chủ đề buổi học phải là chuỗi ký tự.",
            code="INVALID_PARAMS",
        )

    topic = payload["topic"].strip()
    if not topic:
        raise SubjectSessionValidationError(
            "Chủ đề buổi học không được để trống.",
            code="INVALID_PARAMS",
        )

    if len(topic) > 255:
        raise SubjectSessionValidationError(
            "Chủ đề buổi học không được vượt quá 255 ký tự.",
            code="INVALID_PARAMS",
        )

    # 3. Validate objective
    if "objective" not in payload or payload["objective"] is None:
        raise SubjectSessionValidationError(
            "Mục tiêu buổi học (objective) là bắt buộc.",
            code="INVALID_PARAMS",
        )

    if not isinstance(payload["objective"], str):
        raise SubjectSessionValidationError(
            "Mục tiêu buổi học phải là chuỗi ký tự.",
            code="INVALID_PARAMS",
        )

    objective = payload["objective"].strip()
    if not objective:
        raise SubjectSessionValidationError(
            "Mục tiêu buổi học không được để trống.",
            code="INVALID_PARAMS",
        )

    if len(objective) > 5000:
        raise SubjectSessionValidationError(
            "Mục tiêu buổi học không được vượt quá 5000 ký tự.",
            code="INVALID_PARAMS",
        )

    # 4. Check duplicate
    if subject_session_repository.exists_session_number(cleaned_subject_id, session_number):
        raise DuplicateSessionNumberError("Số thứ tự buổi học đã tồn tại trong môn học.")

    # 5. Insert
    new_id = str(uuid.uuid4())
    session = SubjectSession(
        id=new_id,
        subject_id=cleaned_subject_id,
        session_number=session_number,
        topic=topic,
        objective=objective,
    )

    try:
        inserted = subject_session_repository.insert_subject_session(session)
        return inserted.to_dict()
    except Exception as exc:
        # Bắt trường hợp race condition khi 2 request cùng insert cùng session_number
        from mysql.connector.errors import IntegrityError
        if isinstance(exc, IntegrityError) and (1062 in exc.args or "1062" in str(exc) or "Duplicate entry" in str(exc)):
            raise DuplicateSessionNumberError("Số thứ tự buổi học đã tồn tại trong môn học.")
        raise


def update_subject_session_service(subject_id: str, session_id: str, payload: Any) -> dict:
    """
    Cập nhật thông tin buổi học (topic, objective) (SCRUM-129 - Activity A4 / SCRUM-175).
    - Không cho phép cập nhật session_number trực tiếp qua PATCH thường (dùng API reorder).
    - Không cho phép sửa subject_id.
    - Reject empty payload hoặc chỉ chứa trường không hợp lệ (400 INVALID_PARAMS).
    - Subject đã lưu trữ -> 400 SUBJECT_ARCHIVED.
    - Chống IDOR: session_id phải thuộc subject_id.
    """
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise SubjectSessionValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(session_id, str) or not is_valid_uuid(session_id):
        raise SubjectSessionValidationError(
            "Mã định danh buổi học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(payload, dict):
        raise SubjectSessionValidationError(
            "Dữ liệu yêu cầu phải là đối tượng JSON.",
            code="INVALID_PARAMS",
        )

    cleaned_subject_id = subject_id.strip().lower()
    cleaned_session_id = session_id.strip().lower()

    subject = subject_repository.get_subject_by_id(cleaned_subject_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    if subject.status == SUBJECT_STATUS_ARCHIVED:
        raise SubjectArchivedError("Môn học đã lưu trữ, không thể chỉnh sửa buổi học.")

    session = subject_session_repository.get_subject_session_by_id(cleaned_session_id)
    if session is None or session.subject_id != cleaned_subject_id:
        raise SubjectSessionNotFoundError("Không tìm thấy buổi học của môn học.")

    # Lọc và validate các trường được phép sửa: topic, objective
    updates = {}

    if "topic" in payload:
        if payload["topic"] is None or not isinstance(payload["topic"], str):
            raise SubjectSessionValidationError(
                "Chủ đề buổi học phải là chuỗi ký tự.",
                code="INVALID_PARAMS",
            )
        topic = payload["topic"].strip()
        if not topic:
            raise SubjectSessionValidationError(
                "Chủ đề buổi học không được để trống.",
                code="INVALID_PARAMS",
            )
        if len(topic) > 255:
            raise SubjectSessionValidationError(
                "Chủ đề buổi học không được vượt quá 255 ký tự.",
                code="INVALID_PARAMS",
            )
        updates["topic"] = topic

    if "objective" in payload:
        if payload["objective"] is None or not isinstance(payload["objective"], str):
            raise SubjectSessionValidationError(
                "Mục tiêu buổi học phải là chuỗi ký tự.",
                code="INVALID_PARAMS",
            )
        objective = payload["objective"].strip()
        if not objective:
            raise SubjectSessionValidationError(
                "Mục tiêu buổi học không được để trống.",
                code="INVALID_PARAMS",
            )
        if len(objective) > 5000:
            raise SubjectSessionValidationError(
                "Mục tiêu buổi học không được vượt quá 5000 ký tự.",
                code="INVALID_PARAMS",
            )
        updates["objective"] = objective

    if not updates:
        raise SubjectSessionValidationError(
            "Không có trường hợp lệ nào để cập nhật (chỉ hỗ trợ 'topic', 'objective').",
            code="INVALID_PARAMS",
        )

    updated_session = subject_session_repository.update_subject_session_fields(
        cleaned_session_id, updates
    )
    if updated_session is None:
        raise SubjectSessionNotFoundError("Không tìm thấy buổi học sau khi cập nhật.")

    return updated_session.to_dict()


def reorder_subject_sessions_service(subject_id: str, payload: Any) -> list[dict]:
    """
    Sắp xếp lại thứ tự các buổi học của một môn học (SCRUM-129 - Activity A4).
    - Payload: {"session_ids": ["<id1>", "<id2>", ...]}
    - Tất cả session_ids phải thuộc cùng môn học.
    - Không thiếu, không thừa buổi học nào so với danh sách hiện tại.
    - Gán thứ tự 1..N trong transaction atomic.
    """
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise SubjectSessionValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(payload, dict):
        raise SubjectSessionValidationError(
            "Dữ liệu yêu cầu phải là đối tượng JSON.",
            code="INVALID_PARAMS",
        )

    cleaned_subject_id = subject_id.strip().lower()
    subject = subject_repository.get_subject_by_id(cleaned_subject_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    if subject.status == SUBJECT_STATUS_ARCHIVED:
        raise SubjectArchivedError("Môn học đã lưu trữ, không thể sắp xếp lại buổi học.")

    if "session_ids" not in payload or not isinstance(payload["session_ids"], list):
        raise SubjectSessionValidationError(
            "Danh sách 'session_ids' là bắt buộc và phải là mảng.",
            code="INVALID_PARAMS",
        )

    raw_ids = payload["session_ids"]
    if not raw_ids:
        raise SubjectSessionValidationError(
            "Danh sách 'session_ids' không được để trống.",
            code="INVALID_PARAMS",
        )

    cleaned_ids = []
    for sid in raw_ids:
        if not isinstance(sid, str) or not is_valid_uuid(sid):
            raise SubjectSessionValidationError(
                f"Mã định danh buổi học '{sid}' không đúng định dạng UUID.",
                code="INVALID_PARAMS",
            )
        cleaned_ids.append(sid.strip().lower())

    if len(cleaned_ids) != len(set(cleaned_ids)):
        raise SubjectSessionValidationError(
            "Danh sách 'session_ids' không được chứa các mã trùng lặp.",
            code="INVALID_PARAMS",
        )

    existing_sessions = subject_session_repository.list_subject_sessions_by_subject(cleaned_subject_id)
    existing_id_set = {s.id for s in existing_sessions}

    if set(cleaned_ids) != existing_id_set:
        raise SubjectSessionValidationError(
            "Danh sách 'session_ids' phải chứa đúng và đủ tất cả các buổi học của môn học.",
            code="INVALID_PARAMS",
        )

    reordered = subject_session_repository.bulk_update_session_numbers(
        cleaned_subject_id, cleaned_ids
    )
    return [sess.to_dict() for sess in reordered]


def delete_subject_session_service(subject_id: str, session_id: str) -> dict:
    """
    Xóa một buổi học của môn học (SCRUM-129 - Activity A4 / SCRUM-175).
    - Chỉ xóa subject_session, KHÔNG xóa môn học (subject).
    - Tự động chuẩn hóa lại session_number 1..N sau khi xóa.
    - Subject đã lưu trữ -> 400 SUBJECT_ARCHIVED.
    - Chống IDOR: session_id phải thuộc subject_id.
    """
    if not isinstance(subject_id, str) or not is_valid_uuid(subject_id):
        raise SubjectSessionValidationError(
            "Mã định danh môn học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    if not isinstance(session_id, str) or not is_valid_uuid(session_id):
        raise SubjectSessionValidationError(
            "Mã định danh buổi học không đúng định dạng UUID.",
            code="INVALID_PARAMS",
        )

    cleaned_subject_id = subject_id.strip().lower()
    cleaned_session_id = session_id.strip().lower()

    subject = subject_repository.get_subject_by_id(cleaned_subject_id)
    if subject is None:
        raise SubjectNotFoundError("Không tìm thấy môn học.")

    if subject.status == SUBJECT_STATUS_ARCHIVED:
        raise SubjectArchivedError("Môn học đã lưu trữ, không thể xóa buổi học.")

    session = subject_session_repository.get_subject_session_by_id(cleaned_session_id)
    if session is None or session.subject_id != cleaned_subject_id:
        raise SubjectSessionNotFoundError("Không tìm thấy buổi học của môn học.")

    deleted = subject_session_repository.delete_subject_session(cleaned_session_id)
    if not deleted:
        raise SubjectSessionNotFoundError("Không tìm thấy buổi học để xóa.")

    # Chuẩn hóa lại thứ tự 1..N
    subject_session_repository.normalize_session_numbers(cleaned_subject_id)

    return {
        "message": "Xóa buổi học thành công.",
        "id": cleaned_session_id,
        "subject_id": cleaned_subject_id,
    }
