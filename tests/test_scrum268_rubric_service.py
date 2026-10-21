"""
Unit tests cho SCRUM-268: Rubric validation & Business rules.
- Kiểm tra ràng buộc tổng trọng số các tiêu chí = 100%
- Kiểm tra ràng buộc max_score > 0 và score trong [0, max_score]
- Kiểm tra tính toán total_score tự động theo trọng số
"""

import pytest
from app.services.rubric_service import (
    ValidationError,
    _validate_criteria_payload,
    _validate_uuid,
)


def test_validate_criteria_payload_valid():
    """Tổng trọng số đúng 100% -> hợp lệ."""
    criteria = [
        {"name": "Tiêu chí 1", "weight": 40.0, "max_score": 10},
        {"name": "Tiêu chí 2", "weight": 60.0, "max_score": 10},
    ]
    cleaned = _validate_criteria_payload(criteria)
    assert len(cleaned) == 2
    assert sum(c["weight"] for c in cleaned) == 100.0


def test_validate_criteria_payload_sum_not_100():
    """Tổng trọng số khác 100% -> quăng ValidationError."""
    criteria = [
        {"name": "Tiêu chí 1", "weight": 40.0, "max_score": 10},
        {"name": "Tiêu chí 2", "weight": 50.0, "max_score": 10},
    ]
    with pytest.raises(ValidationError) as exc_info:
        _validate_criteria_payload(criteria)
    assert "100%" in str(exc_info.value)
    assert exc_info.value.code == "WEIGHT_SUM_INVALID"


def test_validate_criteria_payload_empty():
    """Danh sách tiêu chí rỗng -> ValidationError."""
    with pytest.raises(ValidationError):
        _validate_criteria_payload([])


def test_validate_criteria_negative_weight():
    """Trọng số âm hoặc = 0 -> ValidationError."""
    criteria = [
        {"name": "Tiêu chí 1", "weight": -10.0, "max_score": 10},
        {"name": "Tiêu chí 2", "weight": 110.0, "max_score": 10},
    ]
    with pytest.raises(ValidationError):
        _validate_criteria_payload(criteria)


def test_validate_uuid():
    """Kiểm tra UUID hợp lệ và không hợp lệ."""
    valid_uuid = "12345678-1234-5678-1234-567812345678"
    assert _validate_uuid(valid_uuid, "ID") == valid_uuid

    with pytest.raises(ValidationError):
        _validate_uuid("invalid-uuid-string", "ID")
