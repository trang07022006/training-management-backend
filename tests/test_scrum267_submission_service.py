"""
Unit tests cho Submission Service - SCRUM-267.
- Kiểm tra validation điểm số từ 0 đến max_score
- Kiểm tra tính năng chuyển bài nhanh (speed grading navigation)
"""

from unittest.mock import MagicMock, patch
import pytest
from app.services.submission_service import (
    ValidationError,
    grade_submission_service,
    get_submission_detail_service,
)
from app.models.submission import AssignmentSubmission


def test_grade_submission_score_out_of_range():
    """Điểm vượt quá max_score (ví dụ 12/10) hoặc âm -> ValidationError."""
    mock_sub = AssignmentSubmission(
        id="sub-1",
        assignment_id="asgn-1",
        student_id="std-1",
        assignment_max_score=10.0,
    )

    with patch("app.repositories.submission_repository.get_submission_by_id", return_value=mock_sub):
        # Điểm quá 10
        with pytest.raises(ValidationError) as exc:
            grade_submission_service("sub-1", {"score": 11.5}, graded_by="trainer-1")
        assert "từ 0 đến 10.0" in str(exc.value)

        # Điểm âm
        with pytest.raises(ValidationError):
            grade_submission_service("sub-1", {"score": -1.0}, graded_by="trainer-1")


def test_speed_grading_navigation_returns_next_prev():
    """Kiểm tra get_submission_detail_service trả về next_id và prev_id."""
    mock_sub = AssignmentSubmission(
        id="sub-2",
        assignment_id="asgn-1",
        student_id="std-2",
        assignment_max_score=10.0,
    )
    mock_nav = {"prev_id": "sub-1", "next_id": "sub-3", "index": 2, "total": 25}

    with patch("app.repositories.submission_repository.get_submission_by_id", return_value=mock_sub), \
         patch("app.repositories.submission_repository.get_speed_grading_navigation", return_value=mock_nav):

        data = get_submission_detail_service("sub-2")
        assert data["id"] == "sub-2"
        assert data["navigation"]["prev_id"] == "sub-1"
        assert data["navigation"]["next_id"] == "sub-3"
        assert data["navigation"]["index"] == 2
        assert data["navigation"]["total"] == 25
