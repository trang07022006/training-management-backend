"""
Unit tests cho Assignment Repository - SCRUM-268.
Kiểm tra các hàm CRUD bài tập và chấm điểm.
"""

from unittest.mock import MagicMock, patch
from app.models.assignment import Assignment
from app.repositories import assignment_repository


def test_map_assignment():
    """Kiểm tra mapping từ row database sang đối tượng Assignment."""
    row = {
        "id": "asgn-123",
        "class_id": "cls-456",
        "title": "Bài tập lớn môn Kiến trúc phần mềm",
        "description": "Xây dựng hệ thống microservices",
        "rubric_template_id": "rt-789",
        "rubric_template_name": "Rubric Đồ án",
        "max_score": 10.0,
        "created_by": "usr-1",
        "is_deleted": 0,
        "class_code": "SE01",
        "created_at": None,
        "updated_at": None,
    }
    model = assignment_repository._map_assignment(row)
    assert model.id == "asgn-123"
    assert model.title == "Bài tập lớn môn Kiến trúc phần mềm"
    assert model.max_score == 10.0
    assert model.rubric_template_name == "Rubric Đồ án"


def test_soft_delete_assignment():
    """Kiểm tra hàm xóa mềm cập nhật is_deleted = 1."""
    with patch("app.repositories.assignment_repository._cursor") as mock_cursor:
        cur_instance = MagicMock()
        cur_instance.rowcount = 1
        mock_cursor.return_value.__enter__.return_value = cur_instance

        res = assignment_repository.soft_delete_assignment("asgn-123")
        assert res is True
        cur_instance.execute.assert_called_once()
