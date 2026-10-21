"""
Unit test cho công thức tính điểm rubric SCRUM-268:
total_score = Σ(score_i / max_score_i * weight_i) / 10
"""

def calculate_rubric_total(criteria_scores, rubric_criteria):
    weight_map = {c["id"]: (float(c["weight"]), float(c["max_score"])) for c in rubric_criteria}
    score_map = {s["criteria_id"]: s for s in criteria_scores}

    total = 0.0
    for crit_id, (weight, max_score) in weight_map.items():
        entry = score_map.get(crit_id)
        score = float(entry["score"]) if entry else 0.0
        total += (score / max_score * weight) if max_score > 0 else 0.0

    return round(total / 10.0, 2)


def test_rubric_grade_full_points():
    """Học viên đạt điểm tối đa tất cả tiêu chí -> tổng 10.0."""
    criteria = [
        {"id": "c1", "weight": 30.0, "max_score": 10.0},
        {"id": "c2", "weight": 70.0, "max_score": 10.0},
    ]
    scores = [
        {"criteria_id": "c1", "score": 10.0},
        {"criteria_id": "c2", "score": 10.0},
    ]
    assert calculate_rubric_total(scores, criteria) == 10.0


def test_rubric_grade_weighted_points():
    """Kiểm tra tính điểm theo trọng số khác nhau."""
    criteria = [
        {"id": "c1", "weight": 40.0, "max_score": 10.0},
        {"id": "c2", "weight": 60.0, "max_score": 10.0},
    ]
    # c1: 8/10 * 40 = 32%
    # c2: 5/10 * 60 = 30%
    # total = 62 / 10 = 6.2
    scores = [
        {"criteria_id": "c1", "score": 8.0},
        {"criteria_id": "c2", "score": 5.0},
    ]
    assert calculate_rubric_total(scores, criteria) == 6.2
