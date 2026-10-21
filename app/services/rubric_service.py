"""
Service layer cho Rubric và chấm điểm bài tập - SCRUM-268.

Business rules:
- Tổng weight các tiêu chí trong 1 rubric phải = 100 (±0.01 cho floating point)
- score_i phải trong [0, max_score_i]
- Không được xóa template đang được gắn với bài tập
- Học viên chỉ xem điểm của chính mình (grade.view_own)
- Giảng viên chỉ chấm điểm lớp mình phụ trách
"""

from typing import Any
import uuid

from app.repositories import rubric_repository, assignment_repository
from app.models.rubric import RubricTemplate, RubricCriteria
from app.models.assignment import Assignment


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RubricServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(RubricServiceError):
    def __init__(self, message: str, code: str = "NOT_FOUND"):
        super().__init__(code=code, message=message, status_code=404)


class ValidationError(RubricServiceError):
    def __init__(self, message: str, code: str = "INVALID_PARAMS"):
        super().__init__(code=code, message=message, status_code=400)


class ConflictError(RubricServiceError):
    def __init__(self, message: str, code: str = "CONFLICT"):
        super().__init__(code=code, message=message, status_code=409)


class ForbiddenError(RubricServiceError):
    def __init__(self, message: str = "Bạn không có quyền thực hiện thao tác này."):
        super().__init__(code="FORBIDDEN", message=message, status_code=403)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_uuid(val: str) -> bool:
    if not isinstance(val, str) or len(val.strip()) != 36:
        return False
    try:
        import uuid as _uuid
        parsed = _uuid.UUID(val.strip())
        return str(parsed) == val.strip().lower()
    except (ValueError, TypeError):
        return False


def _validate_uuid(val: str, label: str) -> str:
    if not _is_valid_uuid(val):
        raise ValidationError(f"{label} không đúng định dạng UUID.")
    return val.strip().lower()


def _validate_criteria_payload(criteria_list: list) -> list[dict]:
    """
    Validate danh sách tiêu chí rubric:
    - Mỗi tiêu chí có: name (str), weight (float > 0), max_score (float > 0)
    - Tổng weight = 100 (±0.01)
    """
    if not isinstance(criteria_list, list) or len(criteria_list) == 0:
        raise ValidationError("Danh sách tiêu chí (criteria) không được để trống.")

    cleaned = []
    for i, item in enumerate(criteria_list):
        if not isinstance(item, dict):
            raise ValidationError(f"Tiêu chí thứ {i+1} phải là object JSON.")

        # name
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(f"Tiêu chí thứ {i+1}: 'name' là bắt buộc và không được để trống.")
        name = name.strip()
        if len(name) > 255:
            raise ValidationError(f"Tiêu chí thứ {i+1}: 'name' không vượt quá 255 ký tự.")

        # weight
        weight = item.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValidationError(f"Tiêu chí '{name}': 'weight' phải là số.")
        weight = float(weight)
        if weight <= 0 or weight > 100:
            raise ValidationError(f"Tiêu chí '{name}': 'weight' phải > 0 và <= 100.")

        # max_score
        max_score = item.get("max_score", 10)
        if isinstance(max_score, bool) or not isinstance(max_score, (int, float)):
            raise ValidationError(f"Tiêu chí '{name}': 'max_score' phải là số.")
        max_score = float(max_score)
        if max_score <= 0:
            raise ValidationError(f"Tiêu chí '{name}': 'max_score' phải > 0.")

        description = item.get("description")
        if description is not None and not isinstance(description, str):
            raise ValidationError(f"Tiêu chí '{name}': 'description' phải là chuỗi.")
        description = description.strip() if description else None

        order_index = item.get("order_index", i)
        if isinstance(order_index, bool) or not isinstance(order_index, int):
            order_index = i

        cleaned.append({
            "name": name,
            "weight": weight,
            "max_score": max_score,
            "description": description,
            "order_index": order_index,
        })

    total_weight = round(sum(c["weight"] for c in cleaned), 2)
    if abs(total_weight - 100.0) > 0.01:
        raise ValidationError(
            f"Tổng trọng số các tiêu chí phải bằng 100% (hiện tại: {total_weight}%).",
            code="WEIGHT_SUM_INVALID",
        )

    return cleaned


# ---------------------------------------------------------------------------
# Rubric Template Services
# ---------------------------------------------------------------------------

def create_rubric_template_service(payload: Any, created_by: str) -> dict:
    """
    Tạo mẫu rubric mới kèm tiêu chí - SCRUM-268.
    Payload: { name, description?, criteria: [{name, weight, max_score, description?}] }
    """
    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu phải là JSON object.")

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Tên mẫu rubric (name) là bắt buộc.")
    name = name.strip()
    if len(name) > 255:
        raise ValidationError("Tên mẫu rubric không vượt quá 255 ký tự.")

    description = payload.get("description")
    if description is not None:
        description = str(description).strip() or None

    criteria_payload = payload.get("criteria")
    cleaned_criteria = _validate_criteria_payload(criteria_payload)

    template_id = str(uuid.uuid4())
    template = RubricTemplate(
        id=template_id,
        name=name,
        description=description,
        created_by=created_by,
    )

    inserted = rubric_repository.insert_rubric_template(template)
    if not inserted:
        raise RubricServiceError("DB_ERROR", "Không thể tạo mẫu rubric.", 500)

    # Tạo tiêu chí
    criteria_objs = [
        RubricCriteria(
            id=str(uuid.uuid4()),
            template_id=template_id,
            name=c["name"],
            description=c["description"],
            max_score=c["max_score"],
            weight=c["weight"],
            order_index=c["order_index"],
        )
        for c in cleaned_criteria
    ]
    rubric_repository.replace_criteria_batch(template_id, criteria_objs)

    result = rubric_repository.get_rubric_template_by_id(template_id)
    return result.to_dict()


def list_rubric_templates_service(created_by: str | None = None) -> list[dict]:
    """Danh sách mẫu rubric (không xóa mềm)."""
    templates = rubric_repository.list_rubric_templates(created_by=created_by)
    return [t.to_dict() for t in templates]


def get_rubric_template_service(template_id: str) -> dict:
    """Chi tiết mẫu rubric kèm tiêu chí."""
    _validate_uuid(template_id, "Mã rubric template")
    t = rubric_repository.get_rubric_template_by_id(template_id.strip().lower())
    if not t:
        raise NotFoundError("Không tìm thấy mẫu rubric.")
    return t.to_dict()


def update_rubric_template_service(
    template_id: str, payload: Any, current_user_id: str
) -> dict:
    """
    Cập nhật mẫu rubric (name/description) và/hoặc toàn bộ tiêu chí.
    Nếu payload có 'criteria' -> thay thế toàn bộ tiêu chí (replace all).
    """
    tid = _validate_uuid(template_id, "Mã rubric template")

    template = rubric_repository.get_rubric_template_by_id(tid)
    if not template:
        raise NotFoundError("Không tìm thấy mẫu rubric.")

    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu phải là JSON object.")

    updates: dict[str, Any] = {}
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Tên mẫu rubric không được để trống.")
        name = name.strip()
        if len(name) > 255:
            raise ValidationError("Tên mẫu rubric không vượt quá 255 ký tự.")
        updates["name"] = name

    if "description" in payload:
        desc = payload["description"]
        updates["description"] = str(desc).strip() if desc else None

    if updates:
        rubric_repository.update_rubric_template(tid, updates)

    if "criteria" in payload:
        cleaned = _validate_criteria_payload(payload["criteria"])
        criteria_objs = [
            RubricCriteria(
                id=str(uuid.uuid4()),
                template_id=tid,
                name=c["name"],
                description=c["description"],
                max_score=c["max_score"],
                weight=c["weight"],
                order_index=c["order_index"],
            )
            for c in cleaned
        ]
        rubric_repository.replace_criteria_batch(tid, criteria_objs)

    result = rubric_repository.get_rubric_template_by_id(tid)
    return result.to_dict()


def delete_rubric_template_service(template_id: str) -> dict:
    """Xóa mềm mẫu rubric. Từ chối nếu đang được dùng bởi bài tập."""
    tid = _validate_uuid(template_id, "Mã rubric template")

    template = rubric_repository.get_rubric_template_by_id(tid)
    if not template:
        raise NotFoundError("Không tìm thấy mẫu rubric.")

    if rubric_repository.template_in_use(tid):
        raise ConflictError(
            "Không thể xóa mẫu rubric đang được sử dụng bởi bài tập.",
            code="TEMPLATE_IN_USE",
        )

    rubric_repository.soft_delete_rubric_template(tid)
    return {"message": "Đã xóa mẫu rubric thành công.", "id": tid}


# ---------------------------------------------------------------------------
# Assignment Services
# ---------------------------------------------------------------------------

def create_assignment_service(class_id: str, payload: Any, created_by: str) -> dict:
    """
    Tạo bài tập mới cho lớp - SCRUM-268.
    Payload: { title, description?, rubric_template_id?, max_score? }
    """
    cid = _validate_uuid(class_id, "Mã lớp học")
    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu phải là JSON object.")

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("Tên bài tập (title) là bắt buộc.")
    title = title.strip()
    if len(title) > 255:
        raise ValidationError("Tên bài tập không vượt quá 255 ký tự.")

    description = payload.get("description")
    description = str(description).strip() if description else None

    rubric_template_id = payload.get("rubric_template_id")
    if rubric_template_id:
        rtid = _validate_uuid(rubric_template_id, "Mã rubric template")
        template = rubric_repository.get_rubric_template_by_id(rtid)
        if not template:
            raise NotFoundError("Không tìm thấy mẫu rubric.", code="RUBRIC_NOT_FOUND")
        rubric_template_id = rtid
    else:
        rubric_template_id = None

    max_score = payload.get("max_score", 10)
    if isinstance(max_score, bool) or not isinstance(max_score, (int, float)):
        raise ValidationError("max_score phải là số.")
    max_score = float(max_score)
    if max_score <= 0:
        raise ValidationError("max_score phải > 0.")

    a = Assignment(
        id=str(uuid.uuid4()),
        class_id=cid,
        title=title,
        description=description,
        rubric_template_id=rubric_template_id,
        max_score=max_score,
        created_by=created_by,
    )
    inserted = assignment_repository.insert_assignment(a)
    if not inserted:
        raise RubricServiceError("DB_ERROR", "Không thể tạo bài tập.", 500)
    return inserted.to_dict()


def list_assignments_service(class_id: str) -> list[dict]:
    """Danh sách bài tập của lớp."""
    cid = _validate_uuid(class_id, "Mã lớp học")
    assignments = assignment_repository.list_assignments_by_class(cid)
    return [a.to_dict() for a in assignments]


def get_assignment_service(assignment_id: str) -> dict:
    _validate_uuid(assignment_id, "Mã bài tập")
    a = assignment_repository.get_assignment_by_id(assignment_id.strip().lower())
    if not a:
        raise NotFoundError("Không tìm thấy bài tập.")
    return a.to_dict()


def update_assignment_service(assignment_id: str, payload: Any) -> dict:
    aid = _validate_uuid(assignment_id, "Mã bài tập")
    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu phải là JSON object.")

    a = assignment_repository.get_assignment_by_id(aid)
    if not a:
        raise NotFoundError("Không tìm thấy bài tập.")

    updates: dict[str, Any] = {}
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValidationError("Tên bài tập không được để trống.")
        title = title.strip()
        if len(title) > 255:
            raise ValidationError("Tên bài tập không vượt quá 255 ký tự.")
        updates["title"] = title

    if "description" in payload:
        updates["description"] = str(payload["description"]).strip() if payload["description"] else None

    if "rubric_template_id" in payload:
        rtid = payload["rubric_template_id"]
        if rtid is None:
            updates["rubric_template_id"] = None
        else:
            rtid = _validate_uuid(rtid, "Mã rubric template")
            if not rubric_repository.get_rubric_template_by_id(rtid):
                raise NotFoundError("Không tìm thấy mẫu rubric.", code="RUBRIC_NOT_FOUND")
            updates["rubric_template_id"] = rtid

    if "max_score" in payload:
        ms = payload["max_score"]
        if isinstance(ms, bool) or not isinstance(ms, (int, float)):
            raise ValidationError("max_score phải là số.")
        ms = float(ms)
        if ms <= 0:
            raise ValidationError("max_score phải > 0.")
        updates["max_score"] = ms

    if not updates:
        raise ValidationError("Không có trường hợp lệ nào để cập nhật.")

    updated = assignment_repository.update_assignment(aid, updates)
    return updated.to_dict()


def delete_assignment_service(assignment_id: str) -> dict:
    aid = _validate_uuid(assignment_id, "Mã bài tập")
    a = assignment_repository.get_assignment_by_id(aid)
    if not a:
        raise NotFoundError("Không tìm thấy bài tập.")
    assignment_repository.soft_delete_assignment(aid)
    return {"message": "Đã xóa bài tập thành công.", "id": aid}


# ---------------------------------------------------------------------------
# Grading Services
# ---------------------------------------------------------------------------

def grade_student_service(
    assignment_id: str,
    student_id: str,
    payload: Any,
    graded_by: str,
) -> dict:
    """
    Giảng viên chấm điểm học viên theo rubric - SCRUM-268.
    Payload: {
        criteria_scores: [{criteria_id, score, comment?}, ...],
        feedback?: str
    }
    Tự động tính total_score từ điểm từng tiêu chí.
    """
    aid = _validate_uuid(assignment_id, "Mã bài tập")
    sid = _validate_uuid(student_id, "Mã học viên")

    if not isinstance(payload, dict):
        raise ValidationError("Dữ liệu phải là JSON object.")

    a = assignment_repository.get_assignment_by_id(aid)
    if not a:
        raise NotFoundError("Không tìm thấy bài tập.")

    if not a.rubric_template_id:
        raise ValidationError(
            "Bài tập này không gắn rubric. Vui lòng gắn mẫu rubric trước khi chấm điểm.",
            code="NO_RUBRIC",
        )

    template = rubric_repository.get_rubric_template_by_id(a.rubric_template_id)
    if not template or not template.criteria:
        raise NotFoundError("Không tìm thấy mẫu rubric hoặc rubric chưa có tiêu chí.", code="RUBRIC_NOT_FOUND")

    # Validate criteria_scores
    criteria_scores_raw = payload.get("criteria_scores")
    if not isinstance(criteria_scores_raw, list) or not criteria_scores_raw:
        raise ValidationError("Danh sách 'criteria_scores' là bắt buộc và không được trống.")

    rubric_crit_map = {c.id: c for c in template.criteria}
    cleaned_scores = []
    provided_ids = set()

    for i, entry in enumerate(criteria_scores_raw):
        if not isinstance(entry, dict):
            raise ValidationError(f"criteria_scores[{i}] phải là object JSON.")

        crit_id = entry.get("criteria_id")
        crit_id = _validate_uuid(crit_id, f"criteria_scores[{i}].criteria_id")

        if crit_id not in rubric_crit_map:
            raise ValidationError(
                f"Tiêu chí '{crit_id}' không thuộc rubric của bài tập này.",
                code="CRITERIA_MISMATCH",
            )
        if crit_id in provided_ids:
            raise ValidationError(f"Tiêu chí '{crit_id}' bị trùng trong danh sách chấm điểm.")
        provided_ids.add(crit_id)

        criteria = rubric_crit_map[crit_id]
        score = entry.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValidationError(f"Tiêu chí '{criteria.name}': 'score' phải là số.")
        score = float(score)
        if score < 0 or score > criteria.max_score:
            raise ValidationError(
                f"Tiêu chí '{criteria.name}': điểm phải trong khoảng [0, {criteria.max_score}]."
            )

        comment = entry.get("comment")
        cleaned_scores.append({
            "criteria_id": crit_id,
            "score": score,
            "comment": str(comment).strip() if comment else None,
        })

    # Phải chấm đủ tất cả tiêu chí
    all_crit_ids = set(rubric_crit_map.keys())
    if provided_ids != all_crit_ids:
        missing = all_crit_ids - provided_ids
        raise ValidationError(
            f"Còn {len(missing)} tiêu chí chưa được chấm điểm.",
            code="CRITERIA_INCOMPLETE",
        )

    feedback = payload.get("feedback")
    feedback = str(feedback).strip() if feedback else None

    rubric_criteria_dicts = [
        {"id": c.id, "weight": c.weight, "max_score": c.max_score}
        for c in template.criteria
    ]

    grade = assignment_repository.upsert_grade_with_criteria(
        assignment_id=aid,
        student_id=sid,
        graded_by=graded_by,
        feedback=feedback,
        criteria_scores=cleaned_scores,
        rubric_criteria=rubric_criteria_dicts,
    )
    return grade.to_dict()


def list_grades_service(assignment_id: str) -> list[dict]:
    """Giảng viên xem điểm tất cả học viên của bài tập."""
    aid = _validate_uuid(assignment_id, "Mã bài tập")
    a = assignment_repository.get_assignment_by_id(aid)
    if not a:
        raise NotFoundError("Không tìm thấy bài tập.")
    grades = assignment_repository.list_grades_by_assignment(aid)
    return [g.to_dict() for g in grades]


def get_my_grade_service(assignment_id: str, student_id: str) -> dict:
    """
    Học viên xem điểm của chính mình (SCRUM-268).
    Trả về điểm tổng + chi tiết từng tiêu chí.
    """
    aid = _validate_uuid(assignment_id, "Mã bài tập")
    sid = _validate_uuid(student_id, "Mã học viên")

    a = assignment_repository.get_assignment_by_id(aid)
    if not a:
        raise NotFoundError("Không tìm thấy bài tập.")

    grade = assignment_repository.get_grade_by_assignment_and_student(aid, sid)
    if not grade:
        raise NotFoundError("Chưa có điểm cho bài tập này.", code="GRADE_NOT_FOUND")

    return grade.to_dict()
