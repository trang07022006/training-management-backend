"""
Dịch vụ nghiệp vụ Quản lý Bài tập và Yêu cầu làm lại (Assignment Service) - SCRUM-269.
Xử lý:
- AC1: Giảng viên yêu cầu làm lại bài tập kèm nhận xét bắt buộc, chuyển trạng thái "Cần làm lại" (needs_rework).
- AC2: Học viên nộp lại bài tập theo hạn mới (resubmit), kiểm tra thời hạn và bảo toàn lịch sử cũ.
- AC3: Lưu trữ và thống kê số lần yêu cầu làm lại (rework_count) cùng toàn bộ tiến trình lịch sử.
"""

from datetime import datetime, timezone
import logging
from typing import Any
import uuid

from app.database.connection import get_db_connection
from app.models.assignment import (
    Assignment,
    AssignmentSubmission,
    SubmissionReworkRequest,
    SubmissionVersion,
    SUBMISSION_STATUS_NEEDS_REWORK,
    SUBMISSION_STATUS_RESUBMITTED,
    SUBMISSION_STATUS_SUBMITTED,
    REWORK_STATUS_OPEN,
    REWORK_STATUS_FULFILLED,
)
from app.repositories import assignment_repository

logger = logging.getLogger(__name__)


class AssignmentServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _parse_iso_datetime(dt_str: Any) -> datetime:
    if isinstance(dt_str, datetime):
        if dt_str.tzinfo is None:
            return dt_str.replace(tzinfo=timezone.utc)
        return dt_str
    if not isinstance(dt_str, str) or not dt_str.strip():
        raise ValueError("Datetime string cannot be empty")
    
    # Chuẩn hóa 'Z' sang '+00:00' để tương thích fromisoformat
    normalized = dt_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def request_rework_service(
    submission_id: str,
    instructor_user_id: str,
    payload: dict[str, Any],
    is_admin_or_manager: bool = False,
) -> dict[str, Any]:
    """
    AC1: Giảng viên yêu cầu học viên làm lại bài tập kèm nhận xét bắt buộc.
    Chuyển bài nộp sang trạng thái 'Cần làm lại' (needs_rework).
    """
    # 1. Validation nhận xét
    comment = payload.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        raise AssignmentServiceError(
            code="COMMENT_REQUIRED",
            message="Nhận xét yêu cầu làm lại là bắt buộc và không được để trống.",
            status_code=400,
        )
    comment = comment.strip()
    if len(comment) > 2000:
        raise AssignmentServiceError(
            code="COMMENT_TOO_LONG",
            message="Nhận xét không được vượt quá 2000 ký tự.",
            status_code=400,
        )

    # 2. Validation hạn nộp mới (AC2 foundation)
    raw_deadline = payload.get("new_deadline")
    if not raw_deadline:
        raise AssignmentServiceError(
            code="DEADLINE_REQUIRED",
            message="Hạn nộp mới là bắt buộc khi yêu cầu làm lại bài.",
            status_code=400,
        )
    try:
        new_deadline_dt = _parse_iso_datetime(raw_deadline)
    except Exception:
        raise AssignmentServiceError(
            code="INVALID_DEADLINE_FORMAT",
            message="Định dạng hạn nộp mới không hợp lệ. Vui lòng sử dụng chuẩn ISO 8601.",
            status_code=400,
        )

    now_utc = datetime.now(timezone.utc)
    if new_deadline_dt <= now_utc:
        raise AssignmentServiceError(
            code="DEADLINE_MUST_BE_FUTURE",
            message="Hạn nộp mới phải ở tương lai so với thời điểm hiện tại.",
            status_code=400,
        )

    # 3. Kiểm tra bài nộp tồn tại
    submission = assignment_repository.get_submission_by_id(submission_id)
    if not submission:
        raise AssignmentServiceError(
            code="SUBMISSION_NOT_FOUND",
            message="Không tìm thấy bài nộp yêu cầu.",
            status_code=404,
        )

    # 4. Kiểm tra quyền của giảng viên đối với lớp học
    assignment = assignment_repository.get_assignment_by_id(submission.assignment_id)
    if not assignment:
        raise AssignmentServiceError(
            code="ASSIGNMENT_NOT_FOUND",
            message="Không tìm thấy bài tập tương ứng.",
            status_code=404,
        )

    if not is_admin_or_manager:
        is_assigned = assignment_repository.is_instructor_assigned_to_class(
            instructor_user_id, assignment.class_id
        )
        if not is_assigned:
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Giảng viên không có quyền yêu cầu làm lại bài nộp của lớp học này.",
                status_code=403,
            )

    # 5. Thực hiện trong Transaction an toàn với SELECT ... FOR UPDATE chống concurrency conflict
    conn = get_db_connection()
    try:
        locked_sub = assignment_repository.get_submission_for_update(submission_id, conn)
        if not locked_sub:
            raise AssignmentServiceError(
                code="SUBMISSION_NOT_FOUND",
                message="Không tìm thấy bài nộp.",
                status_code=404,
            )

        # Điều kiện: Bài nộp phải có ít nhất một lần nộp thực tế (không phải bài chưa nộp)
        if not locked_sub.versions:
            raise AssignmentServiceError(
                code="CANNOT_REWORK_EMPTY_SUBMISSION",
                message="Không thể yêu cầu làm lại bài chưa có lần nộp nào.",
                status_code=400,
            )

        # Điều kiện: Tối đa một yêu cầu làm lại đang mở (open)
        if locked_sub.current_rework_request and locked_sub.current_rework_request.status == REWORK_STATUS_OPEN:
            raise AssignmentServiceError(
                code="REWORK_ALREADY_OPEN",
                message="Bài nộp đang có một yêu cầu làm lại chưa hoàn thành.",
                status_code=409,
            )

        latest_version = locked_sub.versions[-1]
        new_request_number = locked_sub.rework_count + 1

        rework_request = SubmissionReworkRequest(
            id=str(uuid.uuid4()),
            submission_id=submission_id,
            submission_version_id=latest_version.id,
            request_number=new_request_number,
            comment=comment,
            new_deadline=new_deadline_dt,
            requested_by=instructor_user_id,
            status=REWORK_STATUS_OPEN,
            created_at=now_utc,
        )

        # Lưu bản ghi yêu cầu làm lại
        assignment_repository.insert_rework_request(rework_request, conn)

        # Chuyển trạng thái sang Cần làm lại và tăng bộ đếm rework_count trong cùng transaction
        assignment_repository.update_submission_status_and_rework_count(
            submission_id,
            SUBMISSION_STATUS_NEEDS_REWORK,
            new_request_number,
            conn,
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    updated = assignment_repository.get_submission_by_id(submission_id)
    return updated.to_dict() if updated else {}


def resubmit_service(
    submission_id: str,
    student_user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    AC2: Học viên nộp lại bài tập theo hạn nộp mới.
    Bảo toàn toàn bộ các lần nộp cũ và thông tin lịch sử.
    """
    # 1. Xác định hồ sơ học viên
    student = assignment_repository.get_student_by_user_id(student_user_id)
    if not student:
        raise AssignmentServiceError(
            code="STUDENT_PROFILE_NOT_FOUND",
            message="Không tìm thấy hồ sơ học viên liên kết với tài khoản này.",
            status_code=403,
        )

    # 2. Validation nội dung nộp
    content = payload.get("content")
    file_url = payload.get("file_url")
    file_name = payload.get("file_name")
    file_size = payload.get("file_size")
    repo_url = payload.get("repo_url")
    submission_type = payload.get("submission_type") or "text"

    has_content = any([
        isinstance(content, str) and content.strip(),
        isinstance(file_url, str) and file_url.strip(),
        isinstance(repo_url, str) and repo_url.strip(),
    ])
    if not has_content:
        raise AssignmentServiceError(
            code="EMPTY_SUBMISSION_CONTENT",
            message="Vui lòng cung cấp nội dung, tệp đính kèm hoặc liên kết nộp bài.",
            status_code=400,
        )

    # 3. Transaction kiểm tra thời hạn và nộp bài
    now_utc = datetime.now(timezone.utc)
    conn = get_db_connection()
    try:
        locked_sub = assignment_repository.get_submission_for_update(submission_id, conn)
        if not locked_sub:
            raise AssignmentServiceError(
                code="SUBMISSION_NOT_FOUND",
                message="Không tìm thấy bài nộp.",
                status_code=404,
            )

        # Kiểm tra quyền sở hữu bài nộp của học viên
        if locked_sub.student_id != student["id"]:
            raise AssignmentServiceError(
                code="FORBIDDEN_STUDENT_OWNERSHIP",
                message="Bạn không có quyền nộp bài cho học viên khác.",
                status_code=403,
            )

        # Kiểm tra trạng thái bài nộp phải là 'needs_rework'
        if locked_sub.status != SUBMISSION_STATUS_NEEDS_REWORK:
            raise AssignmentServiceError(
                code="INVALID_SUBMISSION_STATUS",
                message="Bài nộp hiện không ở trạng thái Cần làm lại.",
                status_code=400,
            )

        # Kiểm tra yêu cầu làm lại đang mở
        open_request = locked_sub.current_rework_request
        if not open_request or open_request.status != REWORK_STATUS_OPEN:
            raise AssignmentServiceError(
                code="NO_ACTIVE_REWORK_REQUEST",
                message="Không có yêu cầu làm lại nào đang mở cho bài nộp này.",
                status_code=400,
            )

        # Kiểm tra thời hạn backend (AC2)
        request_deadline = open_request.new_deadline
        if request_deadline.tzinfo is None:
            request_deadline = request_deadline.replace(tzinfo=timezone.utc)

        if now_utc > request_deadline:
            raise AssignmentServiceError(
                code="REWORK_SUBMISSION_OVERDUE",
                message="Đã quá hạn nộp lại bài tập theo yêu cầu của giảng viên.",
                status_code=400,
            )

        # Tạo phiên bản nộp mới (version tiếp theo)
        next_version_num = len(locked_sub.versions) + 1
        new_version_id = str(uuid.uuid4())

        new_version = SubmissionVersion(
            id=new_version_id,
            submission_id=submission_id,
            version_number=next_version_num,
            submission_type=submission_type,
            content=content.strip() if isinstance(content, str) else None,
            file_url=file_url.strip() if isinstance(file_url, str) else None,
            file_name=file_name.strip() if isinstance(file_name, str) else None,
            file_size=int(file_size) if file_size is not None else None,
            repo_url=repo_url.strip() if isinstance(repo_url, str) else None,
            submitted_at=now_utc,
            rework_request_id=open_request.id,
        )

        assignment_repository.insert_submission_version(new_version, conn)

        # Đánh dấu yêu cầu làm lại đã được đáp ứng (fulfilled)
        assignment_repository.fulfill_rework_request(
            open_request.id, new_version_id, conn
        )

        # Chuyển trạng thái bài nộp sang 'resubmitted' (Đã nộp lại)
        # Giữ nguyên rework_count không thay đổi khi học viên nộp lại (AC3 counter rule)
        assignment_repository.update_submission_status_and_rework_count(
            submission_id,
            SUBMISSION_STATUS_RESUBMITTED,
            locked_sub.rework_count,
            conn,
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    updated = assignment_repository.get_submission_by_id(submission_id)
    return updated.to_dict() if updated else {}


def get_submission_detail_service(
    submission_id: str,
    user_id: str,
    user_roles: list[str],
) -> dict[str, Any]:
    """
    AC3: Lấy chi tiết bài nộp kèm số lần làm lại (rework_count), danh sách các lần nộp
    và lịch sử yêu cầu làm lại của giảng viên.
    """
    submission = assignment_repository.get_submission_by_id(submission_id)
    if not submission:
        raise AssignmentServiceError(
            code="SUBMISSION_NOT_FOUND",
            message="Không tìm thấy bài nộp.",
            status_code=404,
        )

    # Phân quyền truy cập
    is_admin_or_mgr = any(r in ("admin", "training_manager") for r in user_roles)
    if "trainee" in user_roles and not is_admin_or_mgr:
        student = assignment_repository.get_student_by_user_id(user_id)
        if not student or student["id"] != submission.student_id:
            raise AssignmentServiceError(
                code="FORBIDDEN",
                message="Bạn không có quyền xem bài nộp của học viên khác.",
                status_code=403,
            )
    elif "trainer" in user_roles and not is_admin_or_mgr:
        assignment = assignment_repository.get_assignment_by_id(submission.assignment_id)
        if not assignment or not assignment_repository.is_instructor_assigned_to_class(
            user_id, assignment.class_id
        ):
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Bạn không phụ trách lớp học của bài nộp này.",
                status_code=403,
            )

    return submission.to_dict()


def list_assignment_submissions_service(
    assignment_id: str,
    instructor_user_id: str,
    is_admin_or_mgr: bool = False,
) -> dict[str, Any]:
    """Lấy danh sách bài nộp của một bài tập phục vụ Giảng viên."""
    assignment = assignment_repository.get_assignment_by_id(assignment_id)
    if not assignment:
        raise AssignmentServiceError(
            code="ASSIGNMENT_NOT_FOUND",
            message="Không tìm thấy bài tập.",
            status_code=404,
        )

    if not is_admin_or_mgr:
        is_assigned = assignment_repository.is_instructor_assigned_to_class(
            instructor_user_id, assignment.class_id
        )
        if not is_assigned:
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Bạn không có quyền xem danh sách bài nộp của lớp học này.",
                status_code=403,
            )

    submissions = assignment_repository.list_submissions_by_assignment(assignment_id)
    return {
        "assignment_id": assignment_id,
        "assignment_title": assignment.title,
        "class_id": assignment.class_id,
        "total": len(submissions),
        "submissions": [s.to_dict() for s in submissions],
    }


def get_my_submission_service(
    assignment_id: str,
    student_user_id: str,
) -> dict[str, Any]:
    """Lấy bài nộp của chính học viên đang đăng nhập."""
    student = assignment_repository.get_student_by_user_id(student_user_id)
    if not student:
        raise AssignmentServiceError(
            code="STUDENT_PROFILE_NOT_FOUND",
            message="Không tìm thấy hồ sơ học viên cho tài khoản này.",
            status_code=404,
        )

    submission = assignment_repository.get_submission_by_assignment_and_student(
        assignment_id, student["id"]
    )
    if not submission:
        raise AssignmentServiceError(
            code="SUBMISSION_NOT_FOUND",
            message="Bạn chưa nộp bài cho bài tập này.",
            status_code=404,
        )

    return submission.to_dict()


def create_assignment_service(
    class_id: str,
    instructor_user_id: str,
    payload: dict[str, Any],
    is_admin_or_mgr: bool = False,
) -> dict[str, Any]:
    """Giảng viên giao bài tập mới cho lớp học."""
    # 1. Validation tiêu đề
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AssignmentServiceError(
            code="TITLE_REQUIRED",
            message="Tiêu đề bài tập là bắt buộc và không được để trống.",
            status_code=400,
        )
    title = title.strip()
    if len(title) > 255:
        raise AssignmentServiceError(
            code="TITLE_TOO_LONG",
            message="Tiêu đề bài tập không được vượt quá 255 ký tự.",
            status_code=400,
        )

    # 2. Description
    description = payload.get("description")
    if description is not None:
        description = str(description).strip()

    # 3. Due date
    raw_due_date = payload.get("due_date")
    due_date_dt = None
    if raw_due_date:
        try:
            due_date_dt = _parse_iso_datetime(raw_due_date)
        except Exception:
            raise AssignmentServiceError(
                code="INVALID_DUE_DATE",
                message="Định dạng hạn nộp bài tập không hợp lệ (ISO 8601).",
                status_code=400,
            )

    # 4. Max score
    raw_max_score = payload.get("max_score", 10.0)
    try:
        max_score = float(raw_max_score)
        if max_score <= 0 or max_score > 100:
            raise ValueError()
    except (TypeError, ValueError):
        raise AssignmentServiceError(
            code="INVALID_MAX_SCORE",
            message="Thang điểm bài tập phải là số lớn hơn 0 và nhỏ hơn hoặc bằng 100.",
            status_code=400,
        )

    # 5. Kiểm tra phân công giảng viên
    if not is_admin_or_mgr:
        if not assignment_repository.is_instructor_assigned_to_class(instructor_user_id, class_id):
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Bạn không phụ trách giảng dạy lớp học này để giao bài tập.",
                status_code=403,
            )

    now_utc = datetime.now(timezone.utc)
    new_assignment = Assignment(
        id=f"asg-{uuid.uuid4().hex[:12]}",
        class_id=class_id,
        title=title,
        description=description,
        due_date=due_date_dt,
        max_score=max_score,
        status="active",
        created_by=instructor_user_id,
        created_at=now_utc,
        updated_at=now_utc,
    )

    created = assignment_repository.create_assignment(new_assignment)
    return created.to_dict()


def list_class_assignments_service(
    class_id: str,
    user_id: str,
    user_roles: list[str],
) -> list[dict[str, Any]]:
    """Lấy danh sách các bài tập của một lớp học."""
    is_admin_or_mgr = any(r in ("admin", "training_manager") for r in user_roles)
    if "trainer" in user_roles and not is_admin_or_mgr:
        if not assignment_repository.is_instructor_assigned_to_class(user_id, class_id):
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Bạn không phụ trách giảng dạy lớp học này.",
                status_code=403,
            )
    elif "trainee" in user_roles and not is_admin_or_mgr:
        student = assignment_repository.get_student_by_user_id(user_id)
        if not student or not assignment_repository.is_student_enrolled_in_class(student["id"], class_id):
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Bạn không theo học lớp học này.",
                status_code=403,
            )

    assignments = assignment_repository.list_assignments_by_class(class_id)
    return [a.to_dict() for a in assignments]


def grade_submission_service(
    submission_id: str,
    instructor_user_id: str,
    payload: dict[str, Any],
    is_admin_or_mgr: bool = False,
) -> dict[str, Any]:
    """Giảng viên đánh giá, chấm điểm và xác nhận bài nộp của học viên."""
    submission = assignment_repository.get_submission_by_id(submission_id)
    if not submission:
        raise AssignmentServiceError(
            code="SUBMISSION_NOT_FOUND",
            message="Không tìm thấy bài nộp.",
            status_code=404,
        )

    # Kiểm tra phân công giảng dạy
    assignment = assignment_repository.get_assignment_by_id(submission.assignment_id)
    if not is_admin_or_mgr:
        if not assignment or not assignment_repository.is_instructor_assigned_to_class(
            instructor_user_id, assignment.class_id
        ):
            raise AssignmentServiceError(
                code="FORBIDDEN_CLASS",
                message="Bạn không phụ trách lớp học của bài nộp này.",
                status_code=403,
            )
        max_score = assignment.max_score
    else:
        max_score = assignment.max_score if assignment else 10.0

    raw_score = payload.get("score")
    if raw_score is None:
        raise AssignmentServiceError(
            code="SCORE_REQUIRED",
            message="Điểm số đánh giá là bắt buộc.",
            status_code=400,
        )
    try:
        score = float(raw_score)
        if score < 0 or score > max_score:
            raise ValueError()
    except (TypeError, ValueError):
        raise AssignmentServiceError(
            code="INVALID_SCORE",
            message=f"Điểm số phải là số từ 0 đến thang điểm tối đa ({max_score}).",
            status_code=400,
        )

    feedback = payload.get("feedback")
    if feedback is not None:
        feedback = str(feedback).strip()
        if len(feedback) > 2000:
            raise AssignmentServiceError(
                code="FEEDBACK_TOO_LONG",
                message="Nhận xét đánh giá không được vượt quá 2000 ký tự.",
                status_code=400,
            )

    updated = assignment_repository.grade_submission(
        submission_id=submission_id,
        score=score,
        feedback=feedback,
        graded_by=instructor_user_id,
    )
    return updated.to_dict() if updated else {}

