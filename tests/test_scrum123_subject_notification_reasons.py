"""
Kiểm thử chi tiết thông báo nghiệp vụ và lý do phụ thuộc khi quản lý môn học (SCRUM-123).
Bao quát:
- Phân biệt các dependency thực tế: PROGRAM_ASSOCIATION, CLASS_EXISTS, SESSION_EXISTS, PREREQUISITE_EXISTS.
- Backward compatibility: code vẫn là SUBJECT_IN_USE, bổ sung reason rõ ràng.
- Thông báo lỗi trùng mã: "Mã môn học này đã tồn tại. Vui lòng sử dụng mã khác."
- Thông báo không tìm thấy môn học: "Không tìm thấy môn học. Dữ liệu có thể đã được thay đổi hoặc xóa."
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch
import uuid

from app.models.subject import SUBJECT_STATUS_ACTIVE, Subject
from app.repositories import subject_repository
from app.services import subject_service
from app.services.subject_service import (
    DuplicateSubjectCodeError,
    SubjectInUseError,
    SubjectNotFoundError,
    delete_subject_service,
)


class Scrum123SubjectNotificationReasonsUnitTests(unittest.TestCase):
    """Kiểm thử đơn vị phân loại thông báo lý do phụ thuộc của môn học."""

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.subject_id = str(uuid.uuid4())
        self.sample_subject = Subject(
            id=self.subject_id,
            code="CS101",
            name="Khoa học máy tính",
            credits=3,
            description="Môn cơ sở",
            total_sessions=15,
            status=SUBJECT_STATUS_ACTIVE,
            created_at=self.now,
            updated_at=self.now,
        )

    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.get_subject_usage_info")
    def test_01_delete_blocked_by_class_dependency(
        self, mock_usage_info, mock_in_use, mock_get_by_id
    ):
        """Case B: Môn đã có lớp học -> reason CLASS_EXISTS."""
        mock_get_by_id.return_value = self.sample_subject
        mock_in_use.return_value = True
        mock_usage_info.return_value = {"reason": "CLASS_EXISTS", "table": "classes"}

        with self.assertRaises(SubjectInUseError) as ctx:
            delete_subject_service(self.subject_id)

        err = ctx.exception
        self.assertEqual(err.code, "SUBJECT_IN_USE")
        self.assertEqual(err.reason, "CLASS_EXISTS")
        self.assertIn("Không thể xóa môn học vì môn đã có lớp học", err.message)
        self.assertIn("Đã lưu trữ", err.message)

    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.get_subject_usage_info")
    def test_02_delete_blocked_by_program_association(
        self, mock_usage_info, mock_in_use, mock_get_by_id
    ):
        """Case A: Môn đang thuộc chương trình đào tạo -> reason PROGRAM_ASSOCIATION."""
        mock_get_by_id.return_value = self.sample_subject
        mock_in_use.return_value = True
        mock_usage_info.return_value = {"reason": "PROGRAM_ASSOCIATION", "program_count": 2}

        with self.assertRaises(SubjectInUseError) as ctx:
            delete_subject_service(self.subject_id)

        err = ctx.exception
        self.assertEqual(err.code, "SUBJECT_IN_USE")
        self.assertEqual(err.reason, "PROGRAM_ASSOCIATION")
        self.assertIn("Không thể xóa môn học vì môn đang được sử dụng trong 2 chương trình đào tạo", err.message)
        self.assertIn("Hãy gỡ môn khỏi các chương trình liên quan trước khi xóa", err.message)

    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.get_subject_usage_info")
    def test_03_delete_blocked_by_sessions(
        self, mock_usage_info, mock_in_use, mock_get_by_id
    ):
        """Case C: Môn còn buổi học -> reason SESSION_EXISTS."""
        mock_get_by_id.return_value = self.sample_subject
        mock_in_use.return_value = True
        mock_usage_info.return_value = {"reason": "SESSION_EXISTS", "session_count": 5}

        with self.assertRaises(SubjectInUseError) as ctx:
            delete_subject_service(self.subject_id)

        err = ctx.exception
        self.assertEqual(err.code, "SUBJECT_IN_USE")
        self.assertEqual(err.reason, "SESSION_EXISTS")
        self.assertIn("Không thể xóa môn học vì môn vẫn còn các buổi học", err.message)
        self.assertIn("Hãy xử lý các buổi học liên quan trước khi xóa", err.message)

    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.get_subject_usage_info")
    def test_04_delete_blocked_by_prerequisite(
        self, mock_usage_info, mock_in_use, mock_get_by_id
    ):
        """Case D: Môn đang làm tiên quyết -> reason PREREQUISITE_EXISTS."""
        mock_get_by_id.return_value = self.sample_subject
        mock_in_use.return_value = True
        mock_usage_info.return_value = {"reason": "PREREQUISITE_EXISTS", "prerequisite_count": 1}

        with self.assertRaises(SubjectInUseError) as ctx:
            delete_subject_service(self.subject_id)

        err = ctx.exception
        self.assertEqual(err.code, "SUBJECT_IN_USE")
        self.assertEqual(err.reason, "PREREQUISITE_EXISTS")
        self.assertIn("Không thể xóa môn học vì môn đang được sử dụng làm môn tiên quyết", err.message)
        self.assertIn("Hãy gỡ các quan hệ tiên quyết liên quan trước khi xóa", err.message)

    @patch("app.repositories.subject_repository.get_subject_by_id")
    @patch("app.repositories.subject_repository.is_subject_in_use")
    @patch("app.repositories.subject_repository.get_subject_usage_info")
    def test_05_delete_blocked_unknown_fallback_to_standard_message(
        self, mock_usage_info, mock_in_use, mock_get_by_id
    ):
        """Fallback: Nếu không nhận diện được dependency cụ thể, giữ thông báo chuẩn."""
        mock_get_by_id.return_value = self.sample_subject
        mock_in_use.return_value = True
        mock_usage_info.return_value = None

        with self.assertRaises(SubjectInUseError) as ctx:
            delete_subject_service(self.subject_id)

        err = ctx.exception
        self.assertEqual(err.code, "SUBJECT_IN_USE")
        self.assertIn("Không thể xóa môn học vì đang có dữ liệu liên quan", err.message)
        self.assertIn("Đã lưu trữ", err.message)

    def test_06_duplicate_code_message(self):
        """Thông báo lỗi trùng mã môn học rõ ràng, thân thiện."""
        err = DuplicateSubjectCodeError()
        self.assertEqual(err.code, "DUPLICATE_CODE")
        self.assertEqual(err.message, "Mã môn học này đã tồn tại. Vui lòng sử dụng mã khác.")

    def test_07_not_found_message(self):
        """Thông báo lỗi không tìm thấy môn học thân thiện."""
        err = SubjectNotFoundError()
        self.assertEqual(err.code, "SUBJECT_NOT_FOUND")
        self.assertEqual(err.message, "Không tìm thấy môn học. Dữ liệu có thể đã được thay đổi hoặc xóa.")


if __name__ == "__main__":
    unittest.main()
