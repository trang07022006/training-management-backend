"""
Test suite cho SCRUM-125: Anti-Spam Rate Limit cho Public Consultation Form.
Bao gồm:
- TC125-SPAM-01: Submit hợp lệ lần đầu -> Thành công 201, tạo 1 Lead
- TC125-SPAM-02: Submit lại cùng phone/email ngay lập tức -> HTTP 429, không tạo Lead thứ 2
- TC125-SPAM-03: Submit lần thứ 3 trong cooldown -> Tiếp tục 429, DB vẫn chỉ 1 Lead
- TC125-SPAM-04: Sau 60s cooldown -> Submit lại thành công, tạo Lead mới
- TC125-SPAM-05: Rate limit theo IP nguồn (cùng IP gửi dồn dập -> bị chặn 429)
- Headers Retry-After & error response format
"""

from datetime import datetime, timedelta, timezone
import random
from unittest.mock import patch
import uuid
import pytest

from app.database.connection import get_db_connection
from app.main import app
from app.repositories import lead_repository
from app.services.lead_service import (
    CONSULTATION_COOLDOWN_SECONDS,
    CONSULTATION_RATE_LIMIT_MESSAGE,
    clear_consultation_rate_limits,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_test_environment():
    clear_consultation_rate_limits()
    yield
    clear_consultation_rate_limits()


class TestScrum125ConsultationRateLimit:
    """Kiểm thử tính năng chống spam rate limit (SCRUM-125)."""

    def test_tc125_spam_01_first_valid_submit_succeeds(self, client):
        """TC125-SPAM-01: Submit hợp lệ lần đầu -> Thành công 201, tạo 1 Lead."""
        unique_phone = f"0988{random.randint(100000, 999999)}"
        unique_email = f"spam01_{uuid.uuid4().hex[:6]}@example.com"
        payload = {
            "full_name": "QA SCRUM 125",
            "phone": unique_phone,
            "email": unique_email,
            "message": "Cần tư vấn khóa học CNTT.",
        }

        res = client.post("/api/v1/public/consultations", json=payload)
        assert res.status_code == 201
        data = res.get_json()
        assert data["status"] == "success"
        lead_id = data["data"]["id"]

        try:
            lead = lead_repository.get_lead_by_id(lead_id)
            assert lead is not None
            assert lead.full_name == "QA SCRUM 125"
            assert lead.phone == unique_phone
            assert lead.email == unique_email
            assert lead.status == "new"
            assert lead.source == "public_form"
        finally:
            lead_repository.delete_lead_for_testing(lead_id)

    def test_tc125_spam_02_quick_resubmit_same_phone_is_blocked_429(self, client):
        """TC125-SPAM-02: Submit lại cùng phone/email ngay lập tức -> HTTP 429, không tạo Lead thứ 2."""
        unique_phone = f"0977{random.randint(100000, 999999)}"
        unique_email = f"spam02_{uuid.uuid4().hex[:6]}@example.com"
        payload = {
            "full_name": "QA SCRUM 125",
            "phone": unique_phone,
            "email": unique_email,
        }

        # Lần 1: Thành công
        res1 = client.post("/api/v1/public/consultations", json=payload)
        assert res1.status_code == 201
        lead_id_1 = res1.get_json()["data"]["id"]

        try:
            # Lần 2 ngay lập tức với cùng SĐT / Email
            res2 = client.post("/api/v1/public/consultations", json=payload)
            assert res2.status_code == 429

            data2 = res2.get_json()
            assert data2["code"] == "CONSULTATION_RATE_LIMITED"
            assert data2["error"]["code"] == "CONSULTATION_RATE_LIMITED"
            assert "gần đây" in data2["message"] or "chờ" in data2["message"]
            assert "Retry-After" in res2.headers
            assert int(res2.headers["Retry-After"]) > 0

            # Kiểm tra trong DB: chỉ có 1 lead
            recent = lead_repository.get_recent_lead_by_phone_or_email(
                phone=unique_phone,
                email=unique_email,
                since=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            assert recent is not None
            assert recent.id == lead_id_1
        finally:
            lead_repository.delete_lead_for_testing(lead_id_1)

    def test_tc125_spam_03_third_submit_in_cooldown_still_blocked_no_duplicate(self, client):
        """TC125-SPAM-03: Submit lần thứ 3 trong cooldown -> tiếp tục bị chặn 429, vẫn chỉ có 1 Lead."""
        unique_phone = f"0966{random.randint(100000, 999999)}"
        unique_email = f"spam03_{uuid.uuid4().hex[:6]}@example.com"
        payload = {
            "full_name": "QA SCRUM 125",
            "phone": unique_phone,
            "email": unique_email,
        }

        # Submit lần 1 -> 201
        res1 = client.post("/api/v1/public/consultations", json=payload)
        assert res1.status_code == 201
        lead_id = res1.get_json()["data"]["id"]

        try:
            # Submit lần 2 -> 429
            res2 = client.post("/api/v1/public/consultations", json=payload)
            assert res2.status_code == 429

            # Submit lần 3 -> 429
            res3 = client.post("/api/v1/public/consultations", json=payload)
            assert res3.status_code == 429
            data3 = res3.get_json()
            assert data3["code"] == "CONSULTATION_RATE_LIMITED"

            # Đếm số lượng lead trong database có phone này
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT COUNT(*) AS cnt FROM leads WHERE phone = %s", (unique_phone,))
            row = cur.fetchone()
            cur.close()
            conn.close()

            assert row["cnt"] == 1
        finally:
            lead_repository.delete_lead_for_testing(lead_id)

    def test_tc125_spam_04_submit_after_cooldown_succeeds(self, client):
        """TC125-SPAM-04: Sau 60s cooldown -> submit lại thành công và tạo lead mới."""
        unique_phone = f"0955{random.randint(100000, 999999)}"
        unique_email = f"spam04_{uuid.uuid4().hex[:6]}@example.com"
        payload = {
            "full_name": "QA SCRUM 125",
            "phone": unique_phone,
            "email": unique_email,
        }

        # Lần 1: Thành công
        res1 = client.post("/api/v1/public/consultations", json=payload)
        assert res1.status_code == 201
        lead_id_1 = res1.get_json()["data"]["id"]

        try:
            # Lần 2 ngay sau đó: Bị chặn 429
            res2 = client.post("/api/v1/public/consultations", json=payload)
            assert res2.status_code == 429

            # Giả lập đã trôi qua 65 giây bằng cách dịch lùi created_at trong DB và cập nhật rate limit
            clear_consultation_rate_limits()
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE leads SET created_at = created_at - INTERVAL 65 SECOND WHERE id = %s",
                (lead_id_1,),
            )
            conn.commit()
            cur.close()
            conn.close()

            # Lần 3: Sau cooldown 60s -> Thành công 201
            res3 = client.post("/api/v1/public/consultations", json=payload)
            assert res3.status_code == 201
            lead_id_2 = res3.get_json()["data"]["id"]

            try:
                assert lead_id_1 != lead_id_2
                lead1 = lead_repository.get_lead_by_id(lead_id_1)
                lead2 = lead_repository.get_lead_by_id(lead_id_2)
                assert lead1 is not None
                assert lead2 is not None
            finally:
                lead_repository.delete_lead_for_testing(lead_id_2)
        finally:
            lead_repository.delete_lead_for_testing(lead_id_1)

    def test_tc125_spam_05_rate_limit_by_ip_address(self, client):
        """TC125-SPAM-05: Rate limit theo IP (cùng IP gửi liên tiếp với phone khác -> bị chặn 429)."""
        custom_ip = "198.51.100.77"
        headers = {"X-Forwarded-For": custom_ip}

        payload1 = {
            "full_name": "User One",
            "phone": f"0944{random.randint(100000, 999999)}",
        }
        payload2 = {
            "full_name": "User Two",
            "phone": f"0933{random.randint(100000, 999999)}",
        }

        # Request 1 từ IP 198.51.100.77 -> Thành công
        res1 = client.post("/api/v1/public/consultations", json=payload1, headers=headers)
        assert res1.status_code == 201
        lead_id = res1.get_json()["data"]["id"]

        try:
            # Request 2 từ cùng IP ngay lập tức (dù phone/name khác) -> Bị chặn 429 do cùng nguồn gửi
            res2 = client.post("/api/v1/public/consultations", json=payload2, headers=headers)
            assert res2.status_code == 429
            data2 = res2.get_json()
            assert data2["code"] == "CONSULTATION_RATE_LIMITED"
        finally:
            lead_repository.delete_lead_for_testing(lead_id)

    def test_tc125_spam_different_sources_allowed(self, client):
        """Hai người dùng khác nhau từ 2 IP khác nhau gửi đồng thời đều thành công."""
        payload1 = {
            "full_name": "Người dùng A",
            "phone": f"0911{random.randint(100000, 999999)}",
            "email": f"usera_{uuid.uuid4().hex[:6]}@example.com",
        }
        payload2 = {
            "full_name": "Người dùng B",
            "phone": f"0922{random.randint(100000, 999999)}",
            "email": f"userb_{uuid.uuid4().hex[:6]}@example.com",
        }

        res1 = client.post(
            "/api/v1/public/consultations",
            json=payload1,
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        assert res1.status_code == 201
        lead_id_1 = res1.get_json()["data"]["id"]

        try:
            res2 = client.post(
                "/api/v1/public/consultations",
                json=payload2,
                headers={"X-Forwarded-For": "203.0.113.20"},
            )
            assert res2.status_code == 201
            lead_id_2 = res2.get_json()["data"]["id"]

            try:
                assert lead_id_1 != lead_id_2
            finally:
                lead_repository.delete_lead_for_testing(lead_id_2)
        finally:
            lead_repository.delete_lead_for_testing(lead_id_1)
