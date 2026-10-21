"""
Unit tests cho cơ chế Công bố điểm - SCRUM-267.
Acceptance Criteria: "Điểm chỉ hiển thị cho học viên sau khi giảng viên bấm Công bố".
"""

from app.models.submission import AssignmentSubmission


def test_student_view_hides_unpublished_grade():
    """Học viên xem bài nộp khi CHƯA công bố -> score và feedback là None."""
    sub = AssignmentSubmission(
        id="sub-1",
        assignment_id="asgn-1",
        student_id="std-1",
        score=9.0,
        feedback="Làm rất tốt",
        assignment_is_published=False,  # Chưa công bố
    )

    data = sub.to_dict(is_student_view=True)
    assert data["score"] is None
    assert data["feedback"] is None
    assert data["is_published"] is False


def test_student_view_shows_published_grade():
    """Học viên xem bài nộp khi ĐÃ công bố -> hiển thị đầy đủ điểm và feedback."""
    sub = AssignmentSubmission(
        id="sub-1",
        assignment_id="asgn-1",
        student_id="std-1",
        score=9.0,
        feedback="Làm rất tốt",
        assignment_is_published=True,  # Đã công bố
    )

    data = sub.to_dict(is_student_view=True)
    assert data["score"] == 9.0
    assert data["feedback"] == "Làm rất tốt"
    assert data["is_published"] is True
