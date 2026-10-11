"""
Các bài kiểm thử cho API gửi yêu cầu tư vấn công khai (SCRUM-125 - Activity A2).
Kiểm tra:
- POST /api/v1/public/consultations và POST /api/public/consultations
- Hoàn toàn không yêu cầu đăng nhập (No Authentication)
- Validation: Họ tên, Số điện thoại, Email, Chương trình quan tâm, Tin nhắn
- Chặn các trường do hệ thống quản lý (status, assigned_to, source, id)
- Tính bảo mật của phản hồi (Privacy, không lộ PII)
- Xử lý lỗi cơ sở dữ liệu
"""

import uuid
import pytest

from app.database.connection import get_db_connection
from app.main import app
from app.repositories import lead_repository


@pytest.fixture
def client():
    """Khởi tạo Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def active_training_program():
    """Tạo chương trình đào tạo đang hoạt động (active) để kiểm thử."""
    program_id = str(uuid.uuid4())
    code = f"PROG-A2-{uuid.uuid4().hex[:6].upper()}"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            INSERT INTO training_programs (
                id, code, name, description, duration_semesters, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, 8, 'active', NOW(), NOW())
            """,
            (program_id, code, "Chương trình CNTT Active", "Mô tả chuẩn"),
        )
        conn.commit()
        yield {"id": program_id, "code": code}
    finally:
        cur.execute("DELETE FROM leads WHERE interested_program_id = %s", (program_id,))
        cur.execute("DELETE FROM training_programs WHERE id = %s", (program_id,))
        conn.commit()
        cur.close()
        conn.close()


@pytest.fixture
def draft_training_program():
    """Tạo chương trình đào tạo bản nháp (draft) để kiểm thử."""
    program_id = str(uuid.uuid4())
    code = f"PROG-DRAFT-{uuid.uuid4().hex[:6].upper()}"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            INSERT INTO training_programs (
                id, code, name, description, duration_semesters, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, 8, 'draft', NOW(), NOW())
            """,
            (program_id, code, "Chương trình Bản Nháp", "Mô tả nháp"),
        )
        conn.commit()
        yield {"id": program_id, "code": code}
    finally:
        cur.execute("DELETE FROM leads WHERE interested_program_id = %s", (program_id,))
        cur.execute("DELETE FROM training_programs WHERE id = %s", (program_id,))
        conn.commit()
        cur.close()
        conn.close()


class TestPublicConsultationCreateApi:
    """Kiểm thử API tạo yêu cầu tư vấn công khai."""

    def test_create_consultation_minimal_success_no_auth(self, client):
        """Gửi yêu cầu chỉ với các trường bắt buộc, không cần token."""
        payload = {
            "full_name": "Nguyễn Văn An",
            "phone": "0912345678",
        }

        response = client.post("/api/v1/public/consultations", json=payload)
        assert response.status_code == 201

        data = response.get_json()
        assert data["status"] == "success"
        assert "id" in data["data"]
        lead_id = data["data"]["id"]

        # Kiểm tra tính bảo mật của phản hồi: không trả PII
        assert "phone" not in data["data"]
        assert "email" not in data["data"]
        assert "status" not in data["data"]

        # Kiểm tra database thực tế
        lead = lead_repository.get_lead_by_id(lead_id)
        assert lead is not None
        assert lead.full_name == "Nguyễn Văn An"
        assert lead.phone == "0912345678"
        assert lead.status == "new"
        assert lead.source == "public_form"

        # Dọn dẹp
        lead_repository.delete_lead_for_testing(lead_id)

    def test_create_consultation_full_success(self, client, active_training_program):
        """Gửi yêu cầu đầy đủ các trường hợp lệ."""
        payload = {
            "full_name": "Trần Thị Mai",
            "phone": "0987654321",
            "email": "tranthimai@example.com",
            "interested_program_id": active_training_program["id"],
            "message": "Tôi muốn đăng ký tư vấn xét tuyển học bạ.",
        }

        response = client.post("/api/v1/public/consultations", json=payload)
        assert response.status_code == 201

        data = response.get_json()
        lead_id = data["data"]["id"]

        lead = lead_repository.get_lead_by_id(lead_id)
        assert lead is not None
        assert lead.email == "tranthimai@example.com"
        assert lead.interested_program_id == active_training_program["id"]
        assert lead.message == "Tôi muốn đăng ký tư vấn xét tuyển học bạ."

        lead_repository.delete_lead_for_testing(lead_id)

    def test_create_consultation_alias_route(self, client):
        """Kiểm tra alias route /api/public/consultations."""
        payload = {
            "full_name": "Lê Văn Bình",
            "phone": "0905123456",
        }

        response = client.post("/api/public/consultations", json=payload)
        assert response.status_code == 201
        lead_id = response.get_json()["data"]["id"]
        lead_repository.delete_lead_for_testing(lead_id)

    def test_create_consultation_missing_json(self, client):
        """Gửi body không phải JSON hợp lệ."""
        response = client.post(
            "/api/v1/public/consultations",
            data="not-a-json",
            content_type="text/plain",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["code"] == "INVALID_JSON"

    def test_create_consultation_name_missing_or_whitespace(self, client):
        """Thiếu hoặc rỗng họ tên trả về NAME_REQUIRED (400)."""
        # Thiếu field
        res1 = client.post("/api/v1/public/consultations", json={"phone": "0912345678"})
        assert res1.status_code == 400
        assert res1.get_json()["code"] == "NAME_REQUIRED"

        # Rỗng hoặc khoảng trắng
        res2 = client.post(
            "/api/v1/public/consultations",
            json={"full_name": "   ", "phone": "0912345678"},
        )
        assert res2.status_code == 400
        assert res2.get_json()["code"] == "NAME_REQUIRED"

    def test_create_consultation_phone_missing_or_whitespace(self, client):
        """Thiếu hoặc rỗng số điện thoại trả về PHONE_REQUIRED (400)."""
        res1 = client.post("/api/v1/public/consultations", json={"full_name": "Nguyễn Văn A"})
        assert res1.status_code == 400
        assert res1.get_json()["code"] == "PHONE_REQUIRED"

        res2 = client.post(
            "/api/v1/public/consultations",
            json={"full_name": "Nguyễn Văn A", "phone": "  "},
        )
        assert res2.status_code == 400
        assert res2.get_json()["code"] == "PHONE_REQUIRED"

    def test_create_consultation_invalid_phone_format(self, client):
        """Số điện thoại chứa chữ cái hoặc quá dài trả về INVALID_PARAMS."""
        res = client.post(
            "/api/v1/public/consultations",
            json={"full_name": "Nguyễn Văn A", "phone": "invalid-phone-abc"},
        )
        assert res.status_code == 400
        assert res.get_json()["code"] == "INVALID_PARAMS"

    def test_create_consultation_invalid_email_format(self, client):
        """Email sai định dạng trả về INVALID_EMAIL (400)."""
        res = client.post(
            "/api/v1/public/consultations",
            json={
                "full_name": "Nguyễn Văn A",
                "phone": "0912345678",
                "email": "not-an-email",
            },
        )
        assert res.status_code == 400
        assert res.get_json()["code"] == "INVALID_EMAIL"

    def test_create_consultation_invalid_program_uuid(self, client):
        """Mã chương trình không đúng định dạng UUID trả về INVALID_PARAMS (400)."""
        res = client.post(
            "/api/v1/public/consultations",
            json={
                "full_name": "Nguyễn Văn A",
                "phone": "0912345678",
                "interested_program_id": "not-a-valid-uuid",
            },
        )
        assert res.status_code == 400
        assert res.get_json()["code"] == "INVALID_PARAMS"

    def test_create_consultation_program_not_found(self, client):
        """Chương trình không tồn tại trong database trả về 404 PROGRAM_NOT_FOUND."""
        non_existent_id = str(uuid.uuid4())
        res = client.post(
            "/api/v1/public/consultations",
            json={
                "full_name": "Nguyễn Văn A",
                "phone": "0912345678",
                "interested_program_id": non_existent_id,
            },
        )
        assert res.status_code in (400, 404)
        assert res.get_json()["code"] in ("PROGRAM_NOT_FOUND", "INVALID_PROGRAM")

    def test_create_consultation_draft_program_rejected(self, client, draft_training_program):
        """Chương trình chưa active (bản nháp) bị từ chối đăng ký tư vấn."""
        res = client.post(
            "/api/v1/public/consultations",
            json={
                "full_name": "Nguyễn Văn A",
                "phone": "0912345678",
                "interested_program_id": draft_training_program["id"],
            },
        )
        assert res.status_code in (400, 404)

    def test_create_consultation_message_too_long(self, client):
        """Tin nhắn vượt quá 5000 ký tự trả về INVALID_PARAMS (400)."""
        res = client.post(
            "/api/v1/public/consultations",
            json={
                "full_name": "Nguyễn Văn A",
                "phone": "0912345678",
                "message": "x" * 5001,
            },
        )
        assert res.status_code == 400
        assert res.get_json()["code"] == "INVALID_PARAMS"

    def test_create_consultation_reject_system_controlled_fields(self, client):
        """Client gửi status, source, id, assigned_to phải bị từ chối 400."""
        for field in ("status", "source", "id", "assigned_to", "created_at"):
            res = client.post(
                "/api/v1/public/consultations",
                json={
                    "full_name": "Hacker",
                    "phone": "0912345678",
                    field: "custom_value",
                },
            )
            assert res.status_code == 400
            assert res.get_json()["code"] == "INVALID_PARAMS"
