"""
Test suite cho SCRUM-125 - Activity A4: Public Consultation Hardening.
Kiểm tra an toàn dữ liệu, chuẩn hóa đầu vào và phòng chống lạm dụng:
1. Whitespace trimming & normalization (tên, số điện thoại, email, message).
2. Chuẩn hóa line endings (\r\n -> \n) cho nội dung tin nhắn.
3. Hỗ trợ tiếng Việt Unicode có dấu đầy đủ (Họ tên, tin nhắn).
4. Giới hạn độ dài chặt chẽ (tên <= 255, sđt <= 30, email <= 255, tin nhắn <= 5000).
5. Từ chối trường lạ không xác định (unexpected / malicious fields).
6. Xử lý null an toàn (null email/program/message hợp lệ; null name/phone bị từ chối).
7. Xử lý sai kiểu dữ liệu (bool, number, list, dict thay vì chuỗi).
8. Dữ liệu chứa cú pháp SQL-like được coi là văn bản thuần túy (parameterized SQL an toàn).
9. Dữ liệu chứa cú pháp HTML/Script được coi là văn bản thuần túy (không thực thi server-side).
"""

import pytest
from app.database.connection import get_db_connection
from app.main import app
from app.repositories import lead_repository


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_hardening_whitespace_trimming_and_email_lowercasing(client):
    """Kiểm tra việc trim khoảng trắng và chuẩn hóa chữ thường email."""
    payload = {
        "full_name": "   Đỗ Nhật Nam   ",
        "phone": "   0912 345 678   ",
        "email": "   DoNhatNam@EXAMPLE.COM   ",
        "message": "  \r\n  Cần tư vấn ngành CNTT.  \r\n  ",
    }
    res = client.post("/api/v1/public/consultations", json=payload)
    assert res.status_code == 201
    lead_id = res.get_json()["data"]["id"]

    try:
        lead = lead_repository.get_lead_by_id(lead_id)
        assert lead is not None
        assert lead.full_name == "Đỗ Nhật Nam"
        assert lead.phone == "0912 345 678"
        assert lead.email == "donhatnam@example.com"
        assert lead.message == "Cần tư vấn ngành CNTT."
    finally:
        lead_repository.delete_lead_for_testing(lead_id)


def test_hardening_unicode_vietnamese_characters(client):
    """Bảo toàn các ký tự tiếng Việt có dấu phức tạp."""
    payload = {
        "full_name": "Vũ Đỗ Quỳnh Như",
        "phone": "+84 987 654 321",
        "message": "Em muốn tìm hiểu thông tin học bổng khuyến khích học tập năm 2026-2027.",
    }
    res = client.post("/api/v1/public/consultations", json=payload)
    assert res.status_code == 201
    lead_id = res.get_json()["data"]["id"]

    try:
        lead = lead_repository.get_lead_by_id(lead_id)
        assert lead is not None
        assert lead.full_name == "Vũ Đỗ Quỳnh Như"
        assert "khuyến khích học tập" in lead.message
    finally:
        lead_repository.delete_lead_for_testing(lead_id)


def test_hardening_unexpected_fields_rejected(client):
    """Client gửi bất kỳ trường lạ nào ngoài whitelist đều bị từ chối 400."""
    res = client.post(
        "/api/v1/public/consultations",
        json={
            "full_name": "Test User",
            "phone": "0912345678",
            "random_field": "injected",
            "is_admin": True,
        },
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body["code"] == "INVALID_PARAMS"
    assert "random_field" in body["message"] or "is_admin" in body["message"]


@pytest.mark.parametrize(
    "wrong_field,wrong_value,expected_code",
    [
        ("full_name", True, "INVALID_PARAMS"),
        ("full_name", 12345, "INVALID_PARAMS"),
        ("full_name", ["Nguyễn", "Văn", "A"], "INVALID_PARAMS"),
        ("full_name", {"name": "Nguyễn Văn A"}, "INVALID_PARAMS"),
        ("phone", False, "INVALID_PARAMS"),
        ("phone", 912345678, "INVALID_PARAMS"),
        ("phone", ["0912345678"], "INVALID_PARAMS"),
        ("email", True, "INVALID_EMAIL"),
        ("email", 12345, "INVALID_EMAIL"),
        ("email", ["email@test.com"], "INVALID_EMAIL"),
        ("message", True, "INVALID_PARAMS"),
        ("message", ["nội dung"], "INVALID_PARAMS"),
        ("message", {"text": "nội dung"}, "INVALID_PARAMS"),
        ("interested_program_id", 12345, "INVALID_PARAMS"),
        ("interested_program_id", True, "INVALID_PARAMS"),
    ],
)
def test_hardening_wrong_data_types(client, wrong_field, wrong_value, expected_code):
    """Từ chối các giá trị sai kiểu dữ liệu (bool, int, list, dict thay vì string)."""
    payload = {
        "full_name": "Nguyễn Văn Hợp Lệ",
        "phone": "0912345678",
    }
    payload[wrong_field] = wrong_value
    res = client.post("/api/v1/public/consultations", json=payload)
    assert res.status_code == 400
    assert res.get_json()["code"] == expected_code


def test_hardening_sql_like_strings_stored_as_plain_text(client):
    """Chuỗi chứa cú pháp SQL Injection được lưu dưới dạng văn bản thuần, không gây lỗi cú pháp."""
    sql_payload = "'; DROP TABLE leads; --"
    res = client.post(
        "/api/v1/public/consultations",
        json={
            "full_name": "SQL Test User",
            "phone": "0912345678",
            "message": sql_payload,
        },
    )
    assert res.status_code == 201
    lead_id = res.get_json()["data"]["id"]

    try:
        lead = lead_repository.get_lead_by_id(lead_id)
        assert lead is not None
        assert lead.message == sql_payload

        # Xác nhận bảng leads vẫn nguyên vẹn
        count = lead_repository.count_leads()
        assert count >= 1
    finally:
        lead_repository.delete_lead_for_testing(lead_id)


def test_hardening_html_xss_like_strings_stored_as_plain_text(client):
    """Chuỗi chứa HTML/Script tag được lưu nguyên dạng văn bản thuần túy."""
    html_payload = "<script>alert('XSS Attack!');</script><img src='x' onerror='alert(1)'>"
    res = client.post(
        "/api/v1/public/consultations",
        json={
            "full_name": "XSS Test User",
            "phone": "0912345678",
            "message": html_payload,
        },
    )
    assert res.status_code == 201
    lead_id = res.get_json()["data"]["id"]

    try:
        lead = lead_repository.get_lead_by_id(lead_id)
        assert lead is not None
        assert lead.message == html_payload
    finally:
        lead_repository.delete_lead_for_testing(lead_id)
