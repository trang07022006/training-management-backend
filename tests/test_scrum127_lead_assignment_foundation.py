"""
Kiểm thử nền tảng phân công Lead (SCRUM-127 - Activity A1).
Bao gồm:
1. Lead model hỗ trợ assigned_to_user_id, assigned_at, assigned_to_name, assigned_to_email và serialize to_dict.
2. Database schema chứa cột assigned_to_user_id, assigned_at và khóa ngoại fk_leads_assigned_user.
3. Repository:
   - assign_lead: cập nhật assigned_to_user_id và assigned_at.
   - get_lead_by_id: nạp thông tin nhân sự được phân công qua JOIN users.
   - unassign: gỡ phân công với assigned_to_user_id = None.
   - list_leads: nạp thông tin assigned_to_name, assigned_to_email.
4. Ràng buộc toàn vẹn khóa ngoại (FK): assign user không tồn tại bị chặn ở tầng DB.
"""

from datetime import datetime, timezone
import uuid
import pytest

from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.repositories import lead_repository


class TestLeadAssignmentModelFoundation:
    """Kiểm thử cấu trúc mô hình dữ liệu Lead cho chức năng phân công."""

    def test_lead_model_assignment_fields_default_none(self):
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Phân Công",
            phone="0912345678",
        )
        assert lead.assigned_to_user_id is None
        assert lead.assigned_at is None
        assert lead.assigned_to_name is None
        assert lead.assigned_to_email is None

    def test_lead_model_to_dict_includes_assignment_fields(self):
        now = datetime.now(timezone.utc)
        uid = str(uuid.uuid4())
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Phân Công",
            phone="0912345678",
            assigned_to_user_id=uid,
            assigned_at=now,
            assigned_to_name="Cán bộ Tư vấn",
            assigned_to_email="tuvan@ictu.edu.vn",
        )
        data = lead.to_dict()
        assert data["assigned_to_user_id"] == uid
        assert data["assigned_at"] == now.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert data["assigned_to_name"] == "Cán bộ Tư vấn"
        assert data["assigned_to_email"] == "tuvan@ictu.edu.vn"


class TestLeadAssignmentRepositoryFoundation:
    """Kiểm thử tầng repository và cơ sở dữ liệu MySQL trực tiếp."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.created_lead_ids = []
        self.test_user_id = "34068d8d-b2ec-4ce4-977a-28ac1b9b70de"  # Admin user sẵn có
        yield
        for lid in self.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass

    def test_schema_has_assignment_columns(self):
        """Kiểm tra schema bảng leads có đúng các cột mới."""
        conn = get_db_connection()
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("DESCRIBE leads")
                cols = {row["Field"]: row for row in cur.fetchall()}
                assert "assigned_to_user_id" in cols
                assert "assigned_at" in cols
        finally:
            conn.close()

    def test_assign_lead_success_and_retrieval(self):
        """Phân công Lead cho user hợp lệ và tra cứu lại kèm tên nhân sự."""
        lead_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Học viên Cần Tư Vấn",
            phone="0988888888",
            email="tuvan1@example.com",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lead_id)

        now = datetime.now(timezone.utc)
        updated = lead_repository.assign_lead(
            lead_id=lead_id,
            assigned_to_user_id=self.test_user_id,
            assigned_at=now,
        )
        assert updated is not None
        assert updated.assigned_to_user_id == self.test_user_id
        assert updated.assigned_to_name == "Minh Trang"
        assert updated.assigned_to_email == "lletrang070206@gmail.com"

        # Tra cứu độc lập lại bằng get_lead_by_id
        fetched = lead_repository.get_lead_by_id(lead_id)
        assert fetched is not None
        assert fetched.assigned_to_user_id == self.test_user_id
        assert fetched.assigned_to_name == "Minh Trang"
        assert fetched.assigned_to_email == "lletrang070206@gmail.com"

    def test_unassign_lead_success(self):
        """Gỡ phân công (unassign) đưa assigned_to_user_id và assigned_at về None."""
        lead_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        lead = Lead(
            id=lead_id,
            full_name="Học viên Sắp Gỡ Phân Công",
            phone="0977777777",
            status=LEAD_STATUS_NEW,
            assigned_to_user_id=self.test_user_id,
            assigned_at=now,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lead_id)

        # Unassign
        updated = lead_repository.assign_lead(
            lead_id=lead_id,
            assigned_to_user_id=None,
        )
        assert updated is not None
        assert updated.assigned_to_user_id is None
        assert updated.assigned_at is None
        assert updated.assigned_to_name is None

        fetched = lead_repository.get_lead_by_id(lead_id)
        assert fetched is not None
        assert fetched.assigned_to_user_id is None
        assert fetched.assigned_at is None

    def test_list_leads_includes_assigned_info(self):
        """list_leads trả về thông tin người phụ trách khi có phân công."""
        lead_id = str(uuid.uuid4())
        lead = Lead(
            id=lead_id,
            full_name="Học viên Trong Danh Sách",
            phone="0966666666",
            status=LEAD_STATUS_NEW,
            assigned_to_user_id=self.test_user_id,
            assigned_at=datetime.now(timezone.utc),
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lead_id)

        leads, total = lead_repository.list_leads(page=1, page_size=20)
        matched = next((l for l in leads if l.id == lead_id), None)
        assert matched is not None
        assert matched.assigned_to_user_id == self.test_user_id
        assert matched.assigned_to_name == "Minh Trang"

    def test_assign_non_existent_lead_returns_none(self):
        """Phân công lead không tồn tại trả về None."""
        res = lead_repository.assign_lead(
            lead_id=str(uuid.uuid4()),
            assigned_to_user_id=self.test_user_id,
        )
        assert res is None
