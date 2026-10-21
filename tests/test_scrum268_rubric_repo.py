"""
Unit tests cho Rubric Repository - SCRUM-268.
Kiểm tra ràng buộc template_in_use và mapping dữ liệu.
"""

from unittest.mock import MagicMock, patch
from app.repositories import rubric_repository


def test_map_criteria():
    """Kiểm tra mapping rubric_criteria row sang đối tượng RubricCriteria."""
    row = {
        "id": "crit-101",
        "template_id": "tpl-202",
        "name": "Chất lượng mã nguồn",
        "description": "Tuân thủ clean code",
        "max_score": 10.0,
        "weight": 35.0,
        "order_index": 1,
        "created_at": None,
        "updated_at": None,
    }
    crit = rubric_repository._map_criteria(row)
    assert crit.id == "crit-101"
    assert crit.name == "Chất lượng mã nguồn"
    assert crit.weight == 35.0
    assert crit.max_score == 10.0


def test_template_in_use_true():
    """Kiểm tra khi template đang được gán cho bài tập -> trả về True."""
    with patch("app.repositories.rubric_repository._cursor") as mock_cursor:
        cur_instance = MagicMock()
        cur_instance.fetchone.return_value = {"1": 1}
        mock_cursor.return_value.__enter__.return_value = cur_instance

        in_use = rubric_repository.template_in_use("tpl-202")
        assert in_use is True


def test_template_in_use_false():
    """Kiểm tra khi template chưa gán cho bài tập nào -> trả về False."""
    with patch("app.repositories.rubric_repository._cursor") as mock_cursor:
        cur_instance = MagicMock()
        cur_instance.fetchone.return_value = None
        mock_cursor.return_value.__enter__.return_value = cur_instance

        in_use = rubric_repository.template_in_use("tpl-unused")
        assert in_use is False
