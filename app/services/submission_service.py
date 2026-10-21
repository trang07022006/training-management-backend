"""
Service layer cho Bài nộp, Chấm điểm nhanh và Nhật ký sửa điểm - SCRUM-267.
"""

from typing import Any
from app.repositories import submission_repository


class SubmissionServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(SubmissionServiceError):
    def __init__(self, message: str = "Không tìm thấy dữ liệu yêu cầu."):
        super().__init__(code="NOT_FOUND", message=message, status_code=404)


class ValidationError(SubmissionServiceError):
    def __init__(self, message: str, code: str = "INVALID_PARAMS"):
        super().__init__(code=code, message=message, status_code=400)


def get_submission_detail_service(submission_id: str) -> dict[str, Any]:
    """
    Lấy chi tiết bài nộp kèm thông tin điều hướng nhanh (Speed Grading Navigation: prev/next).
    """
    sub = submission_repository.get_submission_by_id(submission_id)
    if not sub:
        raise NotFoundError("Không tìm thấy bài nộp.")

    nav = submission_repository.get_speed_grading_navigation(sub.assignment_id, sub.id)

    res = sub.to_dict(is_student_view=False)
    res["navigation"] = nav
    return res


def list_submissions_service(assignment_id: str) -> dict[str, Any]:
    """
    Danh sách bài nộp của bài tập kèm thống kê tiến độ chấm điểm.
    """
    submissions = submission_repository.list_submissions_by_assignment(assignment_id)
    total = len(submissions)
    graded_count = sum(1 for s in submissions if s.score is not None)

    return {
        "assignment_id": assignment_id,
        "total": total,
        "graded_count": graded_count,
        "pending_count": total - graded_count,
        "submissions": [s.to_dict(is_student_view=False) for s in submissions],
    }


def grade_submission_service(
    submission_id: str,
    payload: Any,
    graded_by: str,
) -> dict[str, Any]:
    """
    Chấm điểm hoặc sửa điểm bài nộp - SCRUM-267.
    Ràng buộc:
      - score trong khoảng [0, max_score]
      - Ghi nhật ký audit log kèm người sửa và thời điểm
    """
    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu phải là JSON object.")

    sub = submission_repository.get_submission_by_id(submission_id)
    if not sub:
        raise NotFoundError("Không tìm thấy bài nộp.")

    score_val = payload.get("score")
    if score_val is None or isinstance(score_val, bool) or not isinstance(score_val, (int, float)):
        raise ValidationError("Điểm số (score) là bắt buộc và phải là số.")

    score = float(score_val)
    max_score = sub.assignment_max_score or 10.0

    if score < 0 or score > max_score:
        raise ValidationError(f"Điểm số phải trong khoảng từ 0 đến {max_score}.")

    feedback = payload.get("feedback")
    feedback = str(feedback).strip() if feedback else None

    change_reason = payload.get("change_reason")
    change_reason = str(change_reason).strip() if change_reason else None

    # Nếu sửa điểm đã có sẵn -> ghi rõ lý do sửa
    if sub.score is not None and not change_reason:
        change_reason = "Cập nhật lại điểm số bài nộp"

    updated = submission_repository.grade_submission_with_audit(
        submission_id=submission_id,
        new_score=score,
        feedback=feedback,
        performed_by=graded_by,
        change_reason=change_reason,
    )

    if not updated:
        raise SubmissionServiceError("DB_ERROR", "Không thể lưu điểm bài nộp.", 500)

    # Lấy thông tin bài tiếp theo để hỗ trợ chuyển bài nhanh
    nav = submission_repository.get_speed_grading_navigation(updated.assignment_id, updated.id)

    res = updated.to_dict(is_student_view=False)
    res["navigation"] = nav
    return res


def publish_grades_service(assignment_id: str, published_by: str) -> dict[str, Any]:
    """
    Công bố điểm bài tập cho cả lớp - SCRUM-267.
    Sau khi công bố, học viên mới có thể xem điểm và nhận xét.
    """
    ok = submission_repository.publish_assignment_grades(assignment_id, published_by)
    if not ok:
        raise NotFoundError("Không tìm thấy bài tập hoặc không thể công bố điểm.")
    return {
        "assignment_id": assignment_id,
        "is_published": True,
        "message": "Đã công bố điểm bài tập thành công cho toàn bộ học viên.",
    }


def list_audit_logs_service(submission_id: str) -> list[dict[str, Any]]:
    """
    Lấy danh sách nhật ký sửa điểm của một bài nộp.
    """
    logs = submission_repository.list_audit_logs_by_submission(submission_id)
    return [l.to_dict() for l in logs]


def get_my_submission_service(assignment_id: str, student_id: str) -> dict[str, Any]:
    """
    Học viên xem bài nộp của chính mình.
    Tuân thủ quy tắc: Nếu chưa công bố điểm, ẩn điểm và feedback.
    """
    sub = submission_repository.get_student_submission(assignment_id, student_id)
    if not sub:
        raise NotFoundError("Bạn chưa nộp bài cho bài tập này.")

    return sub.to_dict(is_student_view=True)
