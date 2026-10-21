"""
Unit tests cho Nhật ký sửa điểm (Audit Log) - SCRUM-267.
"""

from unittest.mock import patch
from app.services.submission_service import grade_submission_service
from app.models.submission import AssignmentSubmission


def test_grade_submission_triggers_audit():
    """Kiểm tra hàm grade_submission_service truyền đầy đủ thông tin vào repository."""
    mock_sub = AssignmentSubmission(
        id="sub-1",
        assignment_id="asgn-1",
        student_id="std-1",
        score=7.0,
        assignment_max_score=10.0,
    )

    mock_updated = AssignmentSubmission(
        id="sub-1",
        assignment_id="asgn-1",
        student_id="std-1",
        score=8.5,
        feedback="Sửa lại điểm sau khi phúc khảo",
        assignment_max_score=10.0,
    )

    with patch("app.repositories.submission_repository.get_submission_by_id", return_value=mock_sub), \
         patch("app.repositories.submission_repository.grade_submission_with_audit", return_value=mock_updated) as mock_repo, \
         patch("app.repositories.submission_repository.get_speed_grading_navigation", return_value={"prev_id": None, "next_id": None, "index": 1, "total": 1}):

        res = grade_submission_service(
            "sub-1",
            {"score": 8.5, "feedback": "Sửa lại điểm sau khi phúc khảo", "change_reason": "Chấm phúc khảo"},
            graded_by="trainer-1",
        )

        assert res["score"] == 8.5
        mock_repo.assert_called_once_with(
            submission_id="sub-1",
            new_score=8.5,
            feedback="Sửa lại điểm sau khi phúc khảo",
            performed_by="trainer-1",
            change_reason="Chấm phúc khảo",
        )
