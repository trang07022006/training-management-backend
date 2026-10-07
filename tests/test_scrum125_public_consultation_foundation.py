"""
Các bài kiểm thử nền tảng cho Lead / Yêu cầu tư vấn (SCRUM-125 - Activity A1).
Kiểm tra:
- Mô hình Lead (Model) và serialization (to_dict, to_public_dict)
- Giá trị mặc định (status='new', source='public_form')
- Các trường bắt buộc và tùy chọn (nullable email, message, interested_program_id)
- Repository insert_lead và get_lead_by_id
- Ràng buộc khóa ngoại với training_programs (ON DELETE SET NULL)
- An toàn transaction và dọn dẹp kết nối
"""

import uuid
from datetime import datetime, timezone
import pytest
from mysql.connector.errors import IntegrityError

from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.repositories import lead_repository


@pytest.fixture
def test_training_program():
    """Tạo chương trình đào tạo mẫu phục vụ kiểm thử khóa ngoại của lead."""
    program_id = str(uuid.uuid4())
    code = f"PROG-T-{uuid.uuid4().hex[:6].upper()}"
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            INSERT INTO training_programs (
                id, code, name, description, duration_semesters, status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, 8, 'active', NOW(), NOW())
            """,
            (program_id, code, "Chương trình kiểm thử Lead", "Mô tả kiểm thử"),
        )
        conn.commit()
        yield {"id": program_id, "code": code}
    finally:
        cur.execute("DELETE FROM leads WHERE interested_program_id = %s", (program_id,))
        cur.execute("DELETE FROM training_programs WHERE id = %s", (program_id,))
        conn.commit()
        cur.close()
        conn.close()


class TestLeadModel:
    """Kiểm tra mô hình Lead và các phương thức chuyển đổi dữ liệu."""

    def test_lead_model_instantiation_defaults(self):
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn A",
            phone="0912345678",
        )
        assert lead.full_name == "Nguyễn Văn A"
        assert lead.phone == "0912345678"
        assert lead.email is None
        assert lead.interested_program_id is None
        assert lead.message is None
        assert lead.source == LEAD_SOURCE_PUBLIC_FORM
        assert lead.status == LEAD_STATUS_NEW

    def test_lead_serialization_to_dict(self):
        now = datetime.now(timezone.utc)
        lead_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Trần Thị B",
            phone="0987654321",
            email="tranthib@example.com",
            interested_program_id="prog-123",
            message="Tôi muốn tìm hiểu khóa học",
            source="public_form",
            status="new",
            created_at=now,
            updated_at=now,
            interested_program_code="CNTT-K21",
            interested_program_name="Công nghệ thông tin",
        )

        data = lead.to_dict()
        assert data["id"] == lead_id
        assert data["full_name"] == "Trần Thị B"
        assert data["phone"] == "0987654321"
        assert data["email"] == "tranthib@example.com"
        assert data["interested_program_id"] == "prog-123"
        assert data["message"] == "Tôi muốn tìm hiểu khóa học"
        assert data["source"] == "public_form"
        assert data["status"] == "new"
        assert data["created_at"] == now.isoformat()
        assert data["interested_program_code"] == "CNTT-K21"
        assert data["interested_program_name"] == "Công nghệ thông tin"

    def test_lead_to_public_dict_preserves_privacy(self):
        now = datetime.now(timezone.utc)
        lead = Lead(
            id="lead-safe-id",
            full_name="Nguyễn Văn Bảo Mật",
            phone="0909090909",
            email="secret@example.com",
            message="Nội dung riêng tư",
            created_at=now,
        )

        public_data = lead.to_public_dict()
        assert public_data["id"] == "lead-safe-id"
        assert public_data["created_at"] == now.isoformat()
        assert "phone" not in public_data
        assert "email" not in public_data
        assert "full_name" not in public_data
        assert "message" not in public_data
        assert "status" not in public_data


class TestLeadRepository:
    """Kiểm tra tương tác cơ sở dữ liệu thật trong Lead repository."""

    def test_insert_lead_minimal_fields(self):
        lead_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Lê Văn C",
            phone="0933334444",
        )

        try:
            inserted = lead_repository.insert_lead(lead)
            assert inserted is not None
            assert inserted.id == lead_id
            assert inserted.full_name == "Lê Văn C"
            assert inserted.phone == "0933334444"
            assert inserted.email is None
            assert inserted.interested_program_id is None
            assert inserted.status == LEAD_STATUS_NEW
            assert inserted.source == LEAD_SOURCE_PUBLIC_FORM
            assert inserted.created_at is not None

            # Tra cứu lại
            fetched = lead_repository.get_lead_by_id(lead_id)
            assert fetched is not None
            assert fetched.full_name == "Lê Văn C"
            assert fetched.phone == "0933334444"
        finally:
            lead_repository.delete_lead_for_testing(lead_id)

    def test_insert_lead_full_fields_with_valid_program(self, test_training_program):
        lead_id = str(uuid.uuid4())
        program_id = test_training_program["id"]
        lead = Lead(
            id=lead_id,
            full_name="Phạm Hoàng D",
            phone="0944445555",
            email="phamhoangd@example.com",
            interested_program_id=program_id,
            message="Xin tư vấn học phí và lộ trình",
        )

        try:
            inserted = lead_repository.insert_lead(lead)
            assert inserted.id == lead_id
            assert inserted.email == "phamhoangd@example.com"
            assert inserted.interested_program_id == program_id
            assert inserted.message == "Xin tư vấn học phí và lộ trình"

            # Tra cứu kèm thông tin JOIN training_programs
            fetched = lead_repository.get_lead_by_id(lead_id)
            assert fetched is not None
            assert fetched.interested_program_code == test_training_program["code"]
            assert fetched.interested_program_name == "Chương trình kiểm thử Lead"
        finally:
            lead_repository.delete_lead_for_testing(lead_id)

    def test_insert_lead_invalid_program_fk_raises_integrity_error(self):
        lead_id = str(uuid.uuid4())
        non_existent_program_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Người Thử Nghiệm FK",
            phone="0977778888",
            interested_program_id=non_existent_program_id,
        )

        with pytest.raises(IntegrityError):
            lead_repository.insert_lead(lead)

    def test_foreign_key_on_delete_set_null(self):
        """Xóa training_program thì interested_program_id của lead được SET NULL tự động."""
        program_id = str(uuid.uuid4())
        lead_id = str(uuid.uuid4())

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            # 1. Tạo program
            cur.execute(
                """
                INSERT INTO training_programs (id, code, name, duration_semesters, status, created_at, updated_at)
                VALUES (%s, %s, 'Temp Prog', 8, 'active', NOW(), NOW())
                """,
                (program_id, f"TEMP-{uuid.uuid4().hex[:6].upper()}"),
            )
            conn.commit()

            # 2. Tạo lead gắn với program
            lead = Lead(
                id=lead_id,
                full_name="Nguyễn Học Viên",
                phone="0911223344",
                interested_program_id=program_id,
            )
            lead_repository.insert_lead(lead)

            # 3. Xóa program
            cur.execute("DELETE FROM training_programs WHERE id = %s", (program_id,))
            conn.commit()

            # 4. Kiểm tra lead vẫn còn và interested_program_id đã thành NULL
            fetched = lead_repository.get_lead_by_id(lead_id)
            assert fetched is not None
            assert fetched.interested_program_id is None
        finally:
            lead_repository.delete_lead_for_testing(lead_id)
            cur.execute("DELETE FROM training_programs WHERE id = %s", (program_id,))
            conn.commit()
            cur.close()
            conn.close()

    def test_get_non_existent_lead_returns_none(self):
        res = lead_repository.get_lead_by_id(str(uuid.uuid4()))
        assert res is None
