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
